import requests
from decouple import config
from django.conf import settings
from django.http import JsonResponse
from django.db.models import Count, Q
from django.views.decorators.http import require_GET
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from datetime import datetime, timedelta
from .models import SentimentPost, User_Keyword, Sentiment
from .serializers import UserKeywordSerializer, UserSentimentSerializer
from .producers import add_to_sentiment_quene
from platforms.models import UserSocialAccount


class SentimentDashboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        keyword = request.query_params.get("keyword")
        platform = request.query_params.get("platform")
        hours = request.query_params.get("hours")

        # Get current user's keywords
        user_keywords = User_Keyword.objects.filter(user=request.user).values_list("keyword", flat=True)

        if not user_keywords:
            return Response({
                "bar": [],
                "donut": [],
                "cards": [],
                "recentPosts": [],
                "message": "No keywords found for this user."
            })

        # Base queryset for sentiments
        sentiments = Sentiment.objects.filter(keyword__in=user_keywords).select_related("post")

        # Apply Filters
        if keyword:
            sentiments = sentiments.filter(keyword__iexact=keyword)
        
        if platform:
            sentiments = sentiments.filter(post__platform__iexact=platform)

        if hours:
            try:
                hours_int = int(hours)
                time_threshold = timezone.now() - timedelta(hours=hours_int)
                sentiments = sentiments.filter(post__published_at__gte=time_threshold)
            except ValueError:
                pass

        # BAR CHART DATA (Platform-wise)
        # We need to count positive/negative per platform
        bar_queryset = (
            sentiments.values("post__platform")
            .annotate(
                positive=Count("id", filter=Q(sentiment_label__iexact="positive")),
                negative=Count("id", filter=Q(sentiment_label__iexact="negative")),
            )
            .order_by("post__platform")
        )

        bar_data = []
        for item in bar_queryset:
            bar_data.append(
                {
                    "name": item["post__platform"].title(),
                    "pos": item["positive"], # Changed to match frontend expectation
                    "neg": item["negative"], # Changed to match frontend expectation
                }
            )

        # DONUT DATA (Overall)
        positive_count = sentiments.filter(sentiment_label__iexact="positive").count()
        negative_count = sentiments.filter(sentiment_label__iexact="negative").count()

        donut_data = [
            {
                "name": "Positive",
                "value": positive_count,
                "color": "#1E1B4B", # Deep Navy per Figma
            },
            {
                "name": "Negative",
                "value": negative_count,
                "color": "#8C84C4", # Lavender per Figma
            },
        ]

        # CARDS DATA
        cards_data = []
        for item in bar_data:
            cards_data.append(
                {
                    "name": item["name"],
                    "count": item["pos"] + item["neg"],
                    "icon": item["name"],
                }
            )

        # RECENT POSTS
        recent_sentiments = sentiments.order_by("-analyzed_at")[:5]
        recent_posts = []
        for s in recent_sentiments:
            recent_posts.append({
                "id": s.id,
                "platform": s.post.platform.title(),
                "content": s.post.post_text,
                "sentiment": s.sentiment_label,
                "keyword": s.keyword,
                "created_at": s.analyzed_at.strftime("%Y-%m-%d %H:%M:%S"),
            })

        return Response({
            "bar": bar_data,
            "donut": donut_data,
            "cards": cards_data,
            "recentPosts": recent_posts,
        })


class SocialMediaSearchView(APIView):
    permission_classes = [IsAuthenticated]

    def _fetch_instagram(self, keyword):
        if (
            not getattr(settings, 'INSTAGRAM_ACCESS_TOKEN', None)
            or not getattr(settings, 'INSTAGRAM_BUSINESS_ACCOUNT_ID', None)
        ):
            return []

        hashtag = keyword.replace(" ", "").replace("#", "").lower()
        search_url = "https://graph.facebook.com/v22.0/ig_hashtag_search"
        params = {
            "user_id": settings.INSTAGRAM_BUSINESS_ACCOUNT_ID,
            "q": hashtag,
            "access_token": settings.INSTAGRAM_ACCESS_TOKEN,
        }

        try:
            response = requests.get(search_url, params=params)
            data = response.json()
            if "data" not in data or not data["data"]:
                return []
            
            hashtag_id = data["data"][0]["id"]
            posts = []
            seen_ids = set()
            
            for endpoint in ["recent_media", "top_media"]:
                media_url = f"https://graph.facebook.com/v22.0/{hashtag_id}/{endpoint}"
                media_params = {
                    "user_id": settings.INSTAGRAM_BUSINESS_ACCOUNT_ID,
                    "fields": "id,caption,media_type,media_url,permalink,timestamp,username",
                    "access_token": settings.INSTAGRAM_ACCESS_TOKEN,
                }
                media_response = requests.get(media_url, params=media_params)
                media_data = media_response.json()
                if "data" in media_data:
                    for item in media_data["data"]:
                        if item["id"] not in seen_ids:
                            posts.append(item)
                            seen_ids.add(item["id"])
            
            return posts
            
        except Exception as e:
            print(f"❌ [FACEBOOK] Fetch error: {str(e)}")
            import traceback
            traceback.print_exc()
            return []

    def _fetch_facebook(self, keyword, user=None):
        """Fetch Facebook posts using:
        1. Facebook Page Posts Search (all connected pages' feeds, filtered by keyword)
        2. Instagram Hashtag Search via Graph API (also available with FB Business token)
        Returns list of {id, text, created_at, author, permalink}
        """
        results = []
        seen_ids = set()

        # Gather all page tokens to try: from connected platforms + hardcoded fallback
        page_tokens = []  # list of (page_id, access_token)

        # 1. From DB-connected Facebook platforms for this user
        if user:
            try:
                from platforms.models import Platform
                fb_platforms = Platform.objects.filter(
                    user=user, name="facebook", is_active=True
                )
                for fb_plat in fb_platforms:
                    meta = fb_plat.metadata or {}
                    token = meta.get("access_token") or meta.get("page_access_token")
                    page_id = meta.get("page_id") or fb_plat.channel_id
                    if token and page_id:
                        page_tokens.append((page_id, token))
            except Exception as e:
                print(f"Could not load Facebook platforms from DB: {e}")

        # 2. Fallback to .env credentials
        env_token = getattr(settings, 'FACEBOOK_PAGE_ACCESS_TOKEN', config("FACEBOOK_PAGE_ACCESS_TOKEN", default=""))
        env_page_id = getattr(settings, 'FACEBOOK_PAGE_ID', config("FACEBOOK_PAGE_ID", default=""))
        if env_token and env_page_id:
            page_tokens.append((env_page_id, env_token))

        if not page_tokens:
            print("Facebook: No page tokens available.")
            return []

        clean_kw = keyword.replace("#", "").strip()

        for page_id, token in page_tokens:
            # Strategy A: Search page feed for keyword (all posts, not just matching ones with text filter)
            try:
                url = f"https://graph.facebook.com/v22.0/{page_id}/feed"
                params = {
                    "access_token": token,
                    "fields": "id,message,created_time,permalink_url,from,place",
                    "limit": 50
                }
                resp = requests.get(url, params=params, timeout=10)
                data = resp.json()
                if "data" in data:
                    for item in data["data"]:
                        msg = item.get("message") or item.get("story", "")
                        if not msg:
                            continue
                        # Include post if keyword appears in text (case-insensitive), or include all if no keyword
                        if not clean_kw or clean_kw.lower() in msg.lower():
                            post_id = item["id"]
                            if post_id not in seen_ids:
                                seen_ids.add(post_id)
                                # Try to get location from 'place'
                                place = item.get("place", {})
                                location = place.get("name", "") if place else ""
                                results.append({
                                    "id": post_id,
                                    "text": msg,
                                    "created_at": item.get("created_time"),
                                    "author": item.get("from", {}).get("name", "Page"),
                                    "permalink": item.get("permalink_url", ""),
                                    "location": location,
                                })
                elif "error" in data:
                    print(f"Facebook feed error for page {page_id}: {data['error'].get('message')}")
            except Exception as e:
                print(f"Facebook feed fetch error: {e}")

            # Strategy B: Use Graph API hashtag search (works with Business tokens)
            try:
                hashtag_url = "https://graph.facebook.com/v22.0/ig_hashtag_search"
                hashtag_params = {
                    "user_id": page_id,
                    "q": clean_kw,
                    "access_token": token,
                }
                ht_resp = requests.get(hashtag_url, params=hashtag_params, timeout=10)
                ht_data = ht_resp.json()
                if "data" in ht_data and ht_data["data"]:
                    hashtag_id = ht_data["data"][0]["id"]
                    for endpoint in ["recent_media", "top_media"]:
                        media_url = f"https://graph.facebook.com/v22.0/{hashtag_id}/{endpoint}"
                        media_params = {
                            "user_id": page_id,
                            "fields": "id,caption,permalink,timestamp,username,media_type",
                            "access_token": token,
                        }
                        media_resp = requests.get(media_url, params=media_params, timeout=10)
                        media_data = media_resp.json()
                        if "data" in media_data:
                            for item in media_data["data"]:
                                post_id = f"fb_ht_{item['id']}"
                                if post_id not in seen_ids:
                                    seen_ids.add(post_id)
                                    caption = item.get("caption", "") or ""
                                    results.append({
                                        "id": post_id,
                                        "text": caption,
                                        "created_at": item.get("timestamp"),
                                        "author": item.get("username", "Facebook User"),
                                        "permalink": item.get("permalink", ""),
                                        "location": "",
                                    })
            except Exception as e:
                print(f"Facebook hashtag search error: {e}")

        print(f"Facebook: fetched {len(results)} posts for keyword '{keyword}'")
        return results

    def _fetch_youtube(self, keyword, hours=None):
        if not settings.YOUTUBE_API_KEY:
            return []
        url = "https://www.googleapis.com/youtube/v3/search"
        params = {
            "part": "snippet",
            "q": keyword,
            "type": "video",
            "key": settings.YOUTUBE_API_KEY,
            "maxResults": 50, # Increased max results for more data
        }
        
        if hours:
            try:
                hours_int = int(hours)
                # YouTube API expects RFC 3339 formatted date-time with Z or offset
                time_threshold = timezone.now() - timedelta(hours=hours_int)
                params["publishedAfter"] = time_threshold.isoformat().replace("+00:00", "Z")
            except ValueError:
                pass

        try:
            response = requests.get(url, params=params)
            data = response.json()
            results = []
            if "items" in data:
                for item in data["items"]:
                    # Ensure we only process items that are actually videos (contain videoId)
                    if not item.get("id") or "videoId" not in item["id"]:
                        continue
                        
                    snippet = item["snippet"]
                    results.append(
                        {
                            "id": item["id"]["videoId"],
                            "title": snippet["title"],
                            "description": snippet["description"],
                            "author": snippet["channelTitle"],
                            "published_at": snippet["publishedAt"],
                            "permalink": f"https://www.youtube.com/watch?v={item['id']['videoId']}",
                            "extra_details": {
                                "thumbnails": snippet.get("thumbnails"),
                                "channelId": snippet.get("channelId"),
                            },
                        }
                    )
            else:
                if "error" in data:
                    print(f"YouTube API Error: {data['error'].get('message')}")
            return results
        except Exception as e:
            print("error occured", e)
            return []

    def _fetch_twitter(self, keyword, hours=None):
        if not settings.TWITTER_BEARER_TOKEN:
            print("Twitter credentials missing - BEARER_TOKEN: False")
            return []
        url = "https://api.twitter.com/2/tweets/search/recent"
        headers = {"Authorization": f"Bearer {settings.TWITTER_BEARER_TOKEN}"}
        # Added expansions and user.fields to get username
        params = {
            "query": keyword,
            "tweet.fields": "created_at,text,author_id",
            "expansions": "author_id",
            "user.fields": "username,name",
            "max_results": 20, # Increased max results
        }
        
        if hours:
            try:
                hours_int = int(hours)
                time_threshold = timezone.now() - timedelta(hours=hours_int)
                params["start_time"] = time_threshold.strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                pass

        try:
            print(f"Searching Twitter for keyword: {keyword}")
            response = requests.get(url, headers=headers, params=params)
            data = response.json()
            
            # Check for API errors
            if "errors" in data:
                error_msg = data.get("errors", [{}])[0].get("message", "Unknown error")
                print(f"Twitter API error: {error_msg}")
                return []
            
            results = []
            
            # Create a map for user data
            users_map = {}
            if "includes" in data and "users" in data["includes"]:
                for user in data["includes"]["users"]:
                    users_map[user["id"]] = user["username"]

            if "data" in data:
                fetched_count = len(data["data"])
                print(f"Found {fetched_count} Twitter posts for keyword: {keyword}")
                for item in data["data"]:
                    author_id = item.get("author_id")
                    username = users_map.get(author_id, "unknown")
                    results.append(
                        {
                            "id": item["id"],
                            "text": item["text"],
                            "created_at": item.get("created_at"),
                            "author": username,
                            "permalink": f"https://twitter.com/{username}/status/{item['id']}",
                        }
                    )
            else:
                print(f"No Twitter posts found for keyword: {keyword}")
            return results
        except Exception as e:
            print(f"Twitter fetch error: {str(e)}")
            import traceback
            traceback.print_exc()
            return []

    def perform_search(self, keyword, hours=None, user=None):
        all_posts = []
        current_idd = 1
        
        # Heuristic Geo detection
        geo_info = {"lat": None, "lng": None, "name": "", "type": ""}
        clean_kw = keyword.lower().replace("#", "").strip()
        for loc in HEURISTIC_LOCATIONS:
            if loc["name"].lower() == clean_kw:
                geo_info = {
                    "lat": loc["lat"],
                    "lng": loc["lng"],
                    "name": loc["name"],
                    "type": loc["type"]
                }
                break

        twitter_raw = self._fetch_twitter(keyword, hours=hours)
        for post in twitter_raw:
            text = post.get("text", "")
            all_posts.append(
                {
                    "id": current_id,
                    "post_id": post.get("id"),
                    "post_title": text[:50] + "..." if len(text) > 50 else text,
                    "post_text": text,
                    "post_url": post.get("permalink"),
                    "platform": "twitter",
                    "author": post.get("author", ""),
                    "published_at": post.get("created_at"),
                    "latitude": geo_info["lat"],
                    "longitude": geo_info["lng"],
                    "location_name": geo_info["name"],
                    "location_type": geo_info["type"],
                    "extra_details": {},
                }
            )
            current_id += 1

        # Fetch from Instagram
        instagram_raw = self._fetch_instagram(keyword, hours=hours)
        for post in instagram_raw:
            caption = post.get("caption", "")
            all_posts.append(
                {
                    "id": current_id,
                    "post_id": post.get("id"),
                    "post_title": caption[:50].replace("\n", " ") if caption else "Instagram Post",
                    "post_text": caption,
                    "post_url": post.get("permalink"),
                    "platform": "instagram",
                    "author": post.get("username", "N/A"),
                    "published_at": post.get("timestamp"),
                    "latitude": geo_info["lat"],
                    "longitude": geo_info["lng"],
                    "location_name": geo_info["name"],
                    "location_type": geo_info["type"],
                    "extra_details": {
                        "media_type": post.get("media_type"),
                        "media_url": post.get("media_url"),
                    },
                }
            )
            current_id += 1

        # Fetch from Facebook
        facebook_raw = self._fetch_facebook(keyword, hours=hours)
        for post in facebook_raw:
            message = post.get("message", "") or post.get("story", "")
            all_posts.append(
                {
                    "id": current_id,
                    "post_id": post.get("id"),
                    "post_title": message[:50].replace("\n", " ") if message else "Facebook Post",
                    "post_text": message,
                    "post_url": post.get("permalink_url"),
                    "platform": "facebook",
                    "author": "Page",
                    "published_at": post.get("created_time"),
                    "extra_details": {
                        "type": post.get("type"),
                        "likes": post.get("likes", 0),
                        "comments": post.get("comments", 0),
                        "shares": post.get("shares", 0),
                    },
                }
            )
            current_id += 1

        # Fetch from YouTube
        youtube_raw = self._fetch_youtube(keyword, hours=hours)
        for post in youtube_raw:
            all_posts.append(
                {
                    "id": current_id,
                    "post_id": post.get("id"),
                    "post_title": post.get("title"),
                    "post_text": post.get("description"),
                    "post_url": post.get("permalink"),
                    "platform": "youtube",
                    "author": post.get("author"),
                    "published_at": post.get("published_at"),
                    "latitude": geo_info["lat"],
                    "longitude": geo_info["lng"],
                    "location_name": geo_info["name"],
                    "location_type": geo_info["type"],
                    "extra_details": post.get("extra_details", {}),
                }
            )
            current_idd += 1

        facebook_raw = self._fetch_facebook(keyword, user=user)
        for post in facebook_raw:
            text = post.get("text") or ""
            # Use real location from Facebook 'place' field if available, else fall back to heuristic
            fb_location = post.get("location", "")
            fb_lat = geo_info["lat"]
            fb_lng = geo_info["lng"]
            fb_loc_name = fb_location if fb_location else geo_info["name"]
            fb_loc_type = geo_info["type"]
            all_posts.append(
                {
                    "id": current_idd,
                    "post_id": post.get("id"),
                    "post_title": text[:50] + "..." if len(text) > 50 else text,
                    "post_text": text,
                    "post_url": post.get("permalink"),
                    "platform": "facebook",
                    "author": post.get("author"),
                    "published_at": post.get("created_at"),
                    "latitude": fb_lat,
                    "longitude": fb_lng,
                    "location_name": fb_loc_name,
                    "location_type": fb_loc_type,
                    "extra_details": {},
                }
            )
            current_idd += 1
        
        # If hours filter is provided, filter all_posts by published_at
        if hours:
            try:
                hours_int = int(hours)
                time_threshold = timezone.now() - timedelta(hours=hours_int)
                filtered_posts = []
                for post in all_posts:
                    pub_at = post.get("published_at")
                    if pub_at:
                        try:
                            # Handle ISO 8601 strings
                            if isinstance(pub_at, str):
                                dt = datetime.fromisoformat(pub_at.replace("Z", "+00:00"))
                            else:
                                dt = pub_at
                            if dt >= time_threshold:
                                filtered_posts.append(post)
                        except (ValueError, TypeError):
                            filtered_posts.append(post)
                    else:
                        filtered_posts.append(post)
                all_posts = filtered_posts
            except ValueError:
                pass

        add_to_sentiment_quene(all_posts, keyword=keyword)
        
        # Calculate counts by platform
        yt_count = len([p for p in all_posts if p['platform'] == 'youtube'])
        ig_count = len([p for p in all_posts if p['platform'] == 'instagram'])
        tw_count = len([p for p in all_posts if p['platform'] == 'twitter'])
        fb_count = len([p for p in all_posts if p['platform'] == 'facebook'])

        return {
            "youtube": yt_count,
            "instagram": ig_count,
            "twitter": tw_count,
            "facebook": fb_count,
        }

    def get(self, request):
        keyword = request.query_params.get("keyword")
        hours = request.query_params.get("hours")
        if not keyword:
            return Response({"error": "Keyword is required"}, status=400)

        counts = self.perform_search(keyword, hours=hours, user=request.user)
        
        # Save keyword for the current user to ensure it's tracked and shown in history
        User_Keyword.objects.get_or_create(user=request.user, keyword=keyword.strip())

        return Response(
            {
                "success": True,
                "message": f"Data for '{keyword}' successfully fetched and sent for sentiment analysis.",
                "counts": counts,
            }
        )


class UserKeywordSearchTriggerView(SocialMediaSearchView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_keywords = User_Keyword.objects.filter(user=request.user).values_list("keyword", flat=True)
        hours = request.query_params.get("hours")
        
        if not user_keywords:
            return Response({"error": "No keywords found for this user. Please add keywords first."}, status=400)

        total_counts = {
            "youtube": 0,
            "instagram": 0,
            "twitter": 0,
            "facebook": 0,
        }
        processed_keywords = []

        for kw in user_keywords:
            counts = self.perform_search(kw, hours=hours, user=request.user)
            processed_keywords.append(kw)
            for platform in counts:
                total_counts[platform] = total_counts.get(platform, 0) + counts[platform]

        return Response({
            "success": True,
            "message": f"Search triggered for {len(processed_keywords)} keywords.",
            "processed_keywords": processed_keywords,
            "total_counts": total_counts,
        })


class AddKeywordView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Retrieve keywords for the current user."""
        keywords = User_Keyword.objects.filter(user=request.user)
        serializer = UserKeywordSerializer(keywords, many=True)
        return Response(serializer.data)

    def post(self, request):
        """
        Add an array of keywords for the current user.
        Format: {"keywords": ["keyword1", "keyword2"]}
        """
        keywords_list = request.data.get("keywords")
        if not keywords_list or not isinstance(keywords_list, list):
            return Response({"error": "A list of 'keywords' is required."}, status=400)

        created_keywords = []
        for kw in keywords_list:
            if kw.strip():
                # Avoid duplicates for the same user if they exist
                obj, created = User_Keyword.objects.get_or_create(
                    user=request.user, 
                    keyword=kw.strip()
                )
                created_keywords.append(UserKeywordSerializer(obj).data)

        return Response({
            "success": True, 
            "message": f"Successfully processed {len(created_keywords)} keywords.",
            "data": created_keywords
        }, status=201)

    def delete(self, request):
        """Delete a keyword by ID."""
        keyword_id = request.query_params.get("id")
        if not keyword_id:
            return Response({"error": "Keyword ID is required."}, status=400)
        
        try:
            keyword = User_Keyword.objects.get(id=keyword_id, user=request.user)
            keyword.delete()
            return Response({"success": True, "message": "Keyword deleted."})
        except User_Keyword.DoesNotExist:
            return Response({"error": "Keyword not found."}, status=404)


class UserSentimentView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_keywords = list(
            User_Keyword.objects.filter(user=request.user)
            .values_list("keyword", flat=True)
        )

        if not user_keywords:
            return Response({
                "success": True,
                "count": 0,
                "page": 1,
                "page_size": 20,
                "total_pages": 0,
                "results": [],
                "message": "No keywords found for this user. Please add keywords first.",
            })
            
        sentiments = (
            Sentiment.objects
            .select_related("post")
            .order_by("-analyzed_at")
        )

        keyword_filter = request.query_params.get("keyword", "").strip()
        if keyword_filter:
            # Flexible keyword matching: check for exact, or with/without leading '#'
            q_filter = Q(keyword__iexact=keyword_filter)
            if keyword_filter.startswith("#"):
                q_filter |= Q(keyword__iexact=keyword_filter[1:])
            else:
                q_filter |= Q(keyword__iexact=f"#{keyword_filter}")
            
            sentiments = sentiments.filter(q_filter)
        else:
            # If no specific keyword filter, fall back to user's registered keywords
            # For each user keyword, we also want to be flexible
            user_q = Q()
            for kw in user_keywords:
                user_q |= Q(keyword__iexact=kw)
                if kw.startswith("#"):
                    user_q |= Q(keyword__iexact=kw[1:])
                else:
                    user_q |= Q(keyword__iexact=f"#{kw}")
            sentiments = sentiments.filter(user_q)

        sentiment_filter = request.query_params.get("sentiment")
        if sentiment_filter:
            sentiments = sentiments.filter(sentiment_label__iexact=sentiment_filter)

        platform_filter = request.query_params.get("platform")
        if platform_filter:
            sentiments = sentiments.filter(post__platform__iexact=platform_filter)

        # Optional hours filter — only apply if provided by frontend
        hours_filter = request.query_params.get("hours")
        if hours_filter:
            try:
                hours_int = int(hours_filter)
                time_threshold = timezone.now() - timedelta(hours=hours_int)
                sentiments = sentiments.filter(post__published_at__gte=time_threshold)
            except ValueError:
                pass

        # Date range filter: date_from and date_to (YYYY-MM-DD)
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        if date_from:
            try:
                dt_from = datetime.strptime(date_from, "%Y-%m-%d")
                from django.utils.timezone import make_aware
                dt_from = make_aware(dt_from)
                sentiments = sentiments.filter(post__published_at__gte=dt_from)
            except ValueError:
                pass
        if date_to:
            try:
                from datetime import time as dtime
                dt_to = datetime.strptime(date_to, "%Y-%m-%d")
                # Include the full day by going to 23:59:59
                dt_to = datetime.combine(dt_to.date(), dtime(23, 59, 59))
                from django.utils.timezone import make_aware
                dt_to = make_aware(dt_to)
                sentiments = sentiments.filter(post__published_at__lte=dt_to)
            except ValueError:
                pass

        # Optional location filter — Country, State, City
        countries = request.query_params.get("countries")
        states = request.query_params.get("states")
        cities = request.query_params.get("cities")
        
        if countries or states or cities:
            # We filter by location_name or location_type metadata
            loc_q = Q()
            if countries:
                loc_list = [c.strip() for c in countries.split(",")]
                loc_q |= Q(post__location_name__in=loc_list, post__location_type="country")
            if states:
                loc_list = [s.strip() for s in states.split(",")]
                loc_q |= Q(post__location_name__in=loc_list, post__location_type="state")
            if cities:
                loc_list = [c.strip() for c in cities.split(",")]
                loc_q |= Q(post__location_name__in=loc_list, post__location_type="city")
            
            sentiments = sentiments.filter(loc_q)

        # Optional location filter — only include posts with real location (defaults to false now)
        location_only = request.query_params.get("location_only", "false")
        if location_only.lower() == "true":
            sentiments = sentiments.filter(
                Q(post__latitude__isnull=False) | Q(post__location_name__gt="")
            )

        # Skip pagination if 'all=true' is requested
        all_data = request.query_params.get("all", "false")
        if all_data.lower() == "true":
            serializer = UserSentimentSerializer(sentiments, many=True)
            return Response({
                "success": True,
                "count": sentiments.count(),
                "results": serializer.data,
            })

        try:
            page = max(int(request.query_params.get("page", 1)), 1)
        except (ValueError, TypeError):
            page = 1
        try:
            page_size = min(
                max(int(request.query_params.get("page_size", 20)), 1), 100
            )
        except (ValueError, TypeError):
            page_size = 20

        total_count = sentiments.count()
        total_pages = (total_count + page_size - 1) // page_size if total_count else 0
        start = (page - 1) * page_size
        end = start + page_size

        page_results = sentiments[start:end]
        serializer = UserSentimentSerializer(page_results, many=True)

        return Response({
            "success": True,
            "count": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "results": serializer.data,
        })

