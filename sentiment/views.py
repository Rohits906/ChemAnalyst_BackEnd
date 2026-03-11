import requests
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

    def _fetch_instagram(self, keyword, hours=None):
        """Fetch Instagram posts from user's connected accounts or .env credentials"""
        posts = []
        all_accounts = []
        
        # Step 1: Try to get user's connected Instagram accounts from database
        if hasattr(self, 'request') and self.request.user.is_authenticated:
            user_accounts = UserSocialAccount.objects.filter(
                user=self.request.user,
                platform__in=['instagram', 'instagram_business'],
                is_token_valid=True
            ).exclude(access_token__isnull=True)
            
            if user_accounts.exists():
                print(f"🔐 [INSTAGRAM] Found {user_accounts.count()} connected account(s) for user: {self.request.user.username}")
                all_accounts = list(user_accounts)
            else:
                print(f"ℹ️ [INSTAGRAM] No connected accounts for {self.request.user.username}, checking .env credentials...")
        
        # Step 2: If no user accounts, fall back to .env credentials (backward compatibility)
        if not all_accounts:
            if not settings.INSTAGRAM_ACCESS_TOKEN or not settings.INSTAGRAM_BUSINESS_ACCOUNT_ID:
                print(f"❌ [INSTAGRAM] No credentials available - User accounts: None, .env ACCESS_TOKEN: {bool(settings.INSTAGRAM_ACCESS_TOKEN)}, ACCOUNT_ID: {bool(settings.INSTAGRAM_BUSINESS_ACCOUNT_ID)}")
                return []
            
            # Create a fake account object for .env credentials
            class EnvAccount:
                def __init__(self):
                    self.access_token = settings.INSTAGRAM_ACCESS_TOKEN
                    self.account_id = settings.INSTAGRAM_BUSINESS_ACCOUNT_ID
                    self.account_name = "System Instagram Business Account"
            
            all_accounts = [EnvAccount()]
            print(f"🔄 [INSTAGRAM] Using system credentials from .env for account: {settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}")
        
        # Step 3: Fetch posts from all connected accounts
        try:
            api_version = getattr(settings, 'FACEBOOK_API_VERSION', 'v19.0')
            seen_ids = set()
            clean_keyword = keyword.strip().lstrip('#').rstrip('#')
            
            for account in all_accounts:
                try:
                    print(f"📝 [INSTAGRAM] Fetching posts from: {account.account_name if hasattr(account, 'account_name') else account.account_id}")
                    
                    # Try multiple hashtag variations
                    hashtag_variations = [
                        clean_keyword.replace(" ", "").lower(),
                        clean_keyword.lower(),
                        clean_keyword.replace(" ", "_").lower(),
                    ]
                    
                    account_posts_found = False
                    
                    for hashtag in hashtag_variations:
                        search_url = f"https://graph.facebook.com/{api_version}/ig_hashtag_search"
                        params = {
                            "user_id": account.account_id,
                            "q": hashtag,
                            "access_token": account.access_token,
                        }
                        
                        try:
                            response = requests.get(search_url, params=params, timeout=10)
                            data = response.json()
                            
                            if "error" in data:
                                continue
                            
                            if "data" not in data or not data["data"]:
                                continue
                            
                            hashtag_id = data["data"][0]["id"]
                            
                            # Fetch media from hashtag
                            for endpoint in ["recent_media", "top_media"]:
                                media_url = f"https://graph.facebook.com/{api_version}/{hashtag_id}/{endpoint}"
                                media_params = {
                                    "user_id": account.account_id,
                                    "fields": "id,caption,media_type,media_url,permalink,timestamp,username,like_count,comments_count",
                                    "limit": 50,
                                    "access_token": account.access_token,
                                }
                                
                                media_response = requests.get(media_url, params=media_params, timeout=10)
                                media_data = media_response.json()
                                
                                if "error" in media_data:
                                    continue
                                
                                fetched_count = 0
                                for item in media_data.get("data", []):
                                    if item.get("id") in seen_ids:
                                        continue
                                    
                                    caption = item.get("caption", "")
                                    if keyword.lower() in caption.lower() or keyword.lower() in (item.get("username", "")).lower():
                                        posts.append({
                                            "id": item.get("id"),
                                            "caption": caption,
                                            "media_type": item.get("media_type"),
                                            "media_url": item.get("media_url"),
                                            "permalink": item.get("permalink"),
                                            "timestamp": item.get("timestamp"),
                                            "username": item.get("username"),
                                            "like_count": item.get("like_count", 0),
                                            "comments_count": item.get("comments_count", 0),
                                        })
                                        seen_ids.add(item.get("id"))
                                        fetched_count += 1
                                
                                if fetched_count > 0:
                                    print(f"✅ [INSTAGRAM] Found {fetched_count} posts from {endpoint}")
                                    account_posts_found = True
                            
                            if account_posts_found:
                                break
                        
                        except Exception as e:
                            print(f"⚠️ [INSTAGRAM] Error searching hashtag #{hashtag}: {str(e)}")
                            continue
                    
                    if not account_posts_found:
                        print(f"ℹ️ [INSTAGRAM] No posts found for keyword '{keyword}' in this account")
                
                except Exception as e:
                    print(f"⚠️ [INSTAGRAM] Error fetching from account {account.account_id}: {str(e)}")
                    continue
            
            print(f"📊 [INSTAGRAM] Total posts found: {len(posts)}")
            return posts
            
        except Exception as e:
            print(f"❌ [INSTAGRAM] Fetch error: {str(e)}")
            import traceback
            traceback.print_exc()
            return []

    def _fetch_facebook(self, keyword, hours=None):
        """Fetch Facebook posts by keyword from user's connected accounts or .env credentials"""
        posts = []
        all_accounts = []
        
        # Step 1: Try to get user's connected Facebook accounts from database
        if hasattr(self, 'request') and self.request.user.is_authenticated:
            user_accounts = UserSocialAccount.objects.filter(
                user=self.request.user,
                platform__in=['facebook', 'facebook_page'],
                is_token_valid=True
            ).exclude(access_token__isnull=True)
            
            if user_accounts.exists():
                print(f"🔐 [FACEBOOK] Found {user_accounts.count()} connected account(s) for user: {self.request.user.username}")
                all_accounts = list(user_accounts)
            else:
                print(f"ℹ️ [FACEBOOK] No connected accounts for {self.request.user.username}, checking .env credentials...")
        
        # Step 2: If no user accounts, fall back to .env credentials (backward compatibility)
        if not all_accounts:
            if not settings.FACEBOOK_PAGE_ACCESS_TOKEN or not settings.FACEBOOK_PAGE_ID:
                print(f"❌ [FACEBOOK] No credentials available - User accounts: None, .env PAGE_TOKEN: {bool(settings.FACEBOOK_PAGE_ACCESS_TOKEN)}, PAGE_ID: {bool(settings.FACEBOOK_PAGE_ID)}")
                return []
            
            # Create a fake account object for .env credentials
            class EnvAccount:
                def __init__(self):
                    self.access_token = settings.FACEBOOK_PAGE_ACCESS_TOKEN
                    self.account_id = settings.FACEBOOK_PAGE_ID
                    self.account_name = "System Facebook Page"
            
            all_accounts = [EnvAccount()]
            print(f"🔄 [FACEBOOK] Using system credentials from .env for page: {settings.FACEBOOK_PAGE_ID}")
        
        # Step 3: Fetch posts from all connected accounts
        try:
            api_version = getattr(settings, 'FACEBOOK_API_VERSION', 'v19.0')
            seen_ids = set()
            
            for account in all_accounts:
                try:
                    print(f"📝 [FACEBOOK] Fetching posts from: {account.account_name if hasattr(account, 'account_name') else account.account_id}")
                    
                    search_url = f"https://graph.facebook.com/{api_version}/{account.account_id}/posts"
                    params = {
                        "fields": "id,message,created_time,type,permalink_url,likes.summary(true).limit(0),comments.summary(true).limit(0),shares",
                        "limit": 100,
                        "access_token": account.access_token,
                    }
                    
                    if hours:
                        try:
                            hours_int = int(hours)
                            time_threshold = timezone.now() - timedelta(hours=hours_int)
                            params["since"] = int(time_threshold.timestamp())
                        except ValueError:
                            pass
                    
                    response = requests.get(search_url, params=params, timeout=10)
                    data = response.json()
                    
                    if "error" in data:
                        error_msg = data.get('error', {}).get('message', 'Unknown error')
                        print(f"❌ [FACEBOOK] API Error: {error_msg}")
                        continue
                    
                    fetched_count = 0
                    for item in data.get("data", []):
                        if item.get("id") in seen_ids:
                            continue
                        
                        message = item.get("message", "") or item.get("story", "")
                        search_text = message.lower()
                        
                        if keyword.lower() in search_text:
                            posts.append({
                                "id": item.get("id"),
                                "message": message,
                                "created_time": item.get("created_time"),
                                "type": item.get("type"),
                                "permalink_url": item.get("permalink_url"),
                                "likes": item.get("likes", {}).get("summary", {}).get("total_count", 0),
                                "comments": item.get("comments", {}).get("summary", {}).get("total_count", 0),
                                "shares": item.get("shares", {}).get("summary", {}).get("total_count", 0),
                            })
                            seen_ids.add(item.get("id"))
                            fetched_count += 1
                    
                    print(f"✅ [FACEBOOK] Found {fetched_count} posts matching '{keyword}' from this account")
                    
                except Exception as e:
                    print(f"⚠️ [FACEBOOK] Error fetching from account {account.account_id}: {str(e)}")
                    continue
            
            print(f"📊 [FACEBOOK] Total posts found: {len(posts)}")
            return posts
            
        except Exception as e:
            print(f"❌ [FACEBOOK] Fetch error: {str(e)}")
            import traceback
            traceback.print_exc()
            return []

    def _fetch_youtube(self, keyword, hours=None):
        if not settings.YOUTUBE_API_KEY:
            return []
        url = "https://www.googleapis.com/youtube/v3/search"
        params = {
            "part": "snippet",
            "q": keyword,
            "type": "video",
            "key": settings.YOUTUBE_API_KEY,
            "maxResults": 15, # Increased max results
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

    def perform_search(self, keyword, hours=None):
        all_posts = []
        current_id = 1

        # Fetch from Twitter
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
                    "extra_details": post.get("extra_details", {}),
                }
            )
            current_id += 1

        # Filter by hours if provided
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

        counts = self.perform_search(keyword, hours=hours)
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
            counts = self.perform_search(kw, hours=hours)
            processed_keywords.append(kw)
            for platform in total_counts:
                total_counts[platform] += counts.get(platform, 0)

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
            .filter(keyword__in=user_keywords)
            .select_related("post")
            .order_by("-analyzed_at")
        )

        keyword_filter = request.query_params.get("keyword")
        if keyword_filter:
            sentiments = sentiments.filter(keyword__iexact=keyword_filter)

        sentiment_filter = request.query_params.get("sentiment")
        if sentiment_filter:
            sentiments = sentiments.filter(sentiment_label__iexact=sentiment_filter)

        platform_filter = request.query_params.get("platform")
        if platform_filter:
            sentiments = sentiments.filter(post__platform__iexact=platform_filter)

        hours_filter = request.query_params.get("hours")
        if hours_filter:
            try:
                hours_int = int(hours_filter)
                time_threshold = timezone.now() - timedelta(hours=hours_int)
                sentiments = sentiments.filter(post__published_at__gte=time_threshold)
            except ValueError:
                pass

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

