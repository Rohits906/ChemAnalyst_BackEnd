import requests
import random
import uuid
from django.utils import timezone
from django.conf import settings
from django.http import JsonResponse
from django.db.models import Count, Q
from django.views.decorators.http import require_GET
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from .models import SentimentPost, User_Keyword, Sentiment
from .serializers import UserKeywordSerializer, UserSentimentSerializer
from .producers import add_to_sentiment_queue


class SentimentDashboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        keyword = request.query_params.get("keyword")
        platform = request.query_params.get("platform")

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
        recent_sentiments = sentiments.order_by("-analyzed_at")[:1000]
        recent_posts = []
        for s in recent_sentiments:
            recent_posts.append({
                "id": s.id,
                "platform": s.post.platform.title(),
                "content": s.post.post_text,
                "sentiment": s.sentiment_label,
                "keyword": s.keyword,
                "created_at": s.analyzed_at.strftime("%Y-%m-%d %H:%M:%S"),
                "published_at": s.post.published_at.strftime("%Y-%m-%d %H:%M:%S") if s.post.published_at else None,
                "location_name": s.post.location_name or "",
                "latitude": s.post.latitude,
                "longitude": s.post.longitude,
                "post_url": s.post.post_url,
                "post_title": s.post.post_title,
                "author": s.post.author_name,
            })

        # TOP ENGAGED POSTS (for TopLiveData component)
        top_engaged_posts = sentiments.order_by("-post__likes", "-post__comments")[:5]
        top_live_data = []
        for s in top_engaged_posts:
            top_live_data.append({
                "id": str(s.id),
                "link": s.post.post_url,
                "platform": s.post.platform.title(),
                "like": s.post.likes,
                "comment": s.post.comments,
                "shares": s.post.shares,
            })

        # PLATFORM STATS (Aggregate metrics)
        from django.db.models import Sum
        stats_aggregate = sentiments.aggregate(
            total_posts=Count("id"),
            total_likes=Sum("post__likes"),
            total_comments=Sum("post__comments"),
            total_shares=Sum("post__shares"),
        )

        def format_number(num):
            if num is None: return "0"
            if num >= 1000000: return f"{num/1000000:.1f}M"
            if num >= 1000: return f"{num/1000:.1f}K"
            return str(num)

        platform_stats = [
            {"label": "Post", "value": format_number(stats_aggregate["total_posts"])},
            {"label": "Likes", "value": format_number(stats_aggregate["total_likes"])},
            {"label": "Comment", "value": format_number(stats_aggregate["total_comments"])},
            {"label": "Shares", "value": format_number(stats_aggregate["total_shares"])},
        ]

        return Response({
            "bar": bar_data,
            "donut": donut_data,
            "cards": cards_data,
            "recentPosts": recent_posts,
            "topEngagedPosts": top_live_data,
            "platformStats": platform_stats,
        })


class SocialMediaSearchView(APIView):
    permission_classes = [IsAuthenticated]

    def _fetch_instagram(self, keyword):
        if (
            not settings.INSTAGRAM_ACCESS_TOKEN
            or not settings.INSTAGRAM_BUSINESS_ACCOUNT_ID
        ):
            return []

        hashtag = keyword.replace(" ", "").lower()
        search_url = "https://graph.facebook.com/v22.0/ig_hashtag_search"
        params = {
            "user_id": settings.INSTAGRAM_BUSINESS_ACCOUNT_ID,
            "q": hashtag,
            "access_token": settings.INSTAGRAM_ACCESS_TOKEN,
        }

        try:
            print(f"Instagram search for hashtag: {hashtag}")
            response = requests.get(search_url, params=params, timeout=10)
            print(f"Instagram search status: {response.status_code}")
            data = response.json()
            if "error" in data:
                print(f"Instagram API Error: {data['error'].get('message')}")
            if "data" not in data or not data["data"]:
                print("No hashtag ID found for keyword.")
                return []
            hashtag_id = data["data"][0]["id"]
            print(f"Found hashtag ID: {hashtag_id}")

            posts = []
            seen_ids = set()
            for endpoint in ["recent_media", "top_media"]:
                media_url = f"https://graph.facebook.com/v22.0/{hashtag_id}/{endpoint}"
                media_params = {
                    "user_id": settings.INSTAGRAM_BUSINESS_ACCOUNT_ID,
                    "fields": "id,caption,media_type,media_url,permalink,timestamp,location",
                    "access_token": settings.INSTAGRAM_ACCESS_TOKEN,
                }
                media_response = requests.get(media_url, params=media_params, timeout=10)
                print(f"Instagram {endpoint} status: {media_response.status_code}")
                media_data = media_response.json()
                if "error" in media_data:
                    print(f"Instagram {endpoint} API Error: {media_data['error'].get('message')}")
                if "data" in media_data:
                    for item in media_data["data"]:
                        if item["id"] not in seen_ids:
                            posts.append(item)
                            seen_ids.add(item["id"])
            print(f"Total Instagram posts found: {len(posts)}")
            return posts
        except Exception as e:
            print("error occured", e)
            return []

    def _fetch_youtube(self, keyword):
        if not settings.YOUTUBE_API_KEY:
            return []
        url = "https://www.googleapis.com/youtube/v3/search"
        params = {
            "part": "snippet",
            "q": keyword,
            "type": "video",
            "key": settings.YOUTUBE_API_KEY,
            "maxResults": 50,
        }
        try:
            print(f"YouTube search for keyword: {keyword}")
            response = requests.get(url, params=params, timeout=10)
            print(f"YouTube status: {response.status_code}")
            data = response.json()
            if "error" in data:
                print(f"YouTube API Error: {data['error'].get('message')}")
            results = []
            if "items" in data:
                video_ids = [item["id"]["videoId"] for item in data["items"] if item.get("id", {}).get("kind") == "youtube#video"]
                
                if video_ids:
                    # Fetch detailed video info including recordingDetails (location)
                    details_url = "https://www.googleapis.com/youtube/v3/videos"
                    details_params = {
                        "part": "snippet,recordingDetails",
                        "id": ",".join(video_ids),
                        "key": settings.YOUTUBE_API_KEY
                    }
                    details_response = requests.get(details_url, params=details_params, timeout=10)
                    details_data = details_response.json()
                    
                    if "items" in details_data:
                        for item in details_data["items"]:
                            snippet = item["snippet"]
                            rec_details = item.get("recordingDetails", {})
                            location = rec_details.get("location", {})
                            
                            results.append(
                                {
                                    "id": item["id"],
                                    "title": snippet["title"],
                                    "description": snippet["description"],
                                    "author": snippet["channelTitle"],
                                    "published_at": snippet["publishedAt"],
                                    "permalink": f"https://www.youtube.com/watch?v={item['id']}",
                                    "location": {
                                        "latitude": location.get("latitude"),
                                        "longitude": location.get("longitude"),
                                        "name": rec_details.get("locationDescription")
                                    },
                                    "extra_details": {
                                        "thumbnails": snippet.get("thumbnails"),
                                        "channelId": snippet.get("channelId"),
                                    },
                                }
                            )
            print(f"Total YouTube videos found: {len(results)}")
            return results
        except Exception as e:
            print("error occured", e)
            return []

    def _fetch_twitter(self, keyword):
        if not settings.TWITTER_BEARER_TOKEN:
            return []
        url = "https://api.twitter.com/2/tweets/search/recent"
        headers = {"Authorization": f"Bearer {settings.TWITTER_BEARER_TOKEN}"}
        # Added expansions and user.fields to get username
        params = {
            "query": keyword,
            "tweet.fields": "created_at,text,author_id,geo",
            "expansions": "author_id,geo.place_id",
            "user.fields": "username,name",
            "place.fields": "full_name,geo",
            "max_results": 100,
        }
        try:
            print(f"Twitter search for keyword: {keyword}")
            response = requests.get(url, headers=headers, params=params, timeout=10)
            print(f"Twitter status: {response.status_code}")
            
            if response.status_code == 402:
                print("Twitter API: Payment Required (likely plan limit hit). Returning empty results.")
                return []
                
            data = response.json()
            if "errors" in data:
                print(f"Twitter API Errors: {data['errors']}")
            results = []
            
            # Create a map for user data and place data
            users_map = {}
            places_map = {}
            if "includes" in data:
                if "users" in data["includes"]:
                    for user in data["includes"]["users"]:
                        users_map[user["id"]] = user["username"]
                if "places" in data["includes"]:
                    for place in data["includes"]["places"]:
                        places_map[place["id"]] = place

            if "data" in data:
                for item in data["data"]:
                    author_id = item.get("author_id")
                    username = users_map.get(author_id, "unknown")
                    
                    # Extract Geo if present
                    geo_data = {}
                    if "geo" in item and "place_id" in item["geo"]:
                        place = places_map.get(item["geo"]["place_id"])
                        if place:
                            geo_data = {
                                "full_name": place.get("full_name"),
                                "coordinates": place.get("geo", {}).get("bbox", []) or place.get("geo", {}).get("coordinates", {}).get("coordinates", [])
                            }

                    results.append(
                        {
                            "id": item["id"],
                            "text": item["text"],
                            "created_at": item.get("created_at"),
                            "author": username,
                            "permalink": f"https://twitter.com/{username}/status/{item['id']}",
                            "geo": geo_data
                        }
                    )
            print(f"Total Twitter tweets found: {len(results)}")
            return results
        except Exception as e:
            print("error occured", e)
            return []

    def _extract_location(self, text, keyword, post_metadata=None):
        """
        Extract location prioritizing real API metadata, then falling back to text analysis.
        """
        # 1. Clean inputs
        text_lower = text.lower() if text else ""
        # Remove hashtags and trim for keyword matching
        keyword_clean = keyword.lower().replace("#", "").strip() if keyword else ""

        # 2. Check for real metadata (coordinates or location name)
        if post_metadata:
            # Twitter Geo
            geo = post_metadata.get("geo")
            if geo and geo.get("coordinates"):
                coords = geo["coordinates"]
                if isinstance(coords, list) and len(coords) >= 2:
                    lng = (coords[0] + coords[2]) / 2 if len(coords) == 4 else coords[0]
                    lat = (coords[1] + coords[3]) / 2 if len(coords) == 4 else coords[1]
                    name = geo.get("full_name") or keyword_clean.title()
                    return name, lat, lng
            
            # Instagram/Facebook Location name
            if post_metadata.get("location"):
                loc = post_metadata["location"]
                if isinstance(loc, dict):
                    # YouTube case (has direct coordinates)
                    if loc.get("latitude") is not None:
                        name = loc.get("name") or keyword_clean.title()
                        return name, loc["latitude"], loc["longitude"]
                    
                    # Instagram case (has name only)
                    if loc.get("name"):
                        loc_name = loc["name"]
                        loc_name_lower = loc_name.lower()
                        for city, coords in self._get_cities().items():
                            if city in loc_name_lower:
                                return city.title(), coords[0], coords[1]
                        return loc["name"], None, None

        # 3. Fallback to city-based heuristic
        cities = self._get_cities()
        
        # Check if keyword contains or is a city
        for city, coords in cities.items():
            if city in keyword_clean:
                return city.title(), coords[0], coords[1]
            
        # Check if city is mentioned in text
        for city, coords in cities.items():
            if city in text_lower:
                return city.title(), coords[0], coords[1]
        
        # 4. Final fallback: Return empty if no real location identified
        return "", None, None

    def _get_cities(self):
        return {
            # India
            "delhi": (28.6139, 77.2090),
            "दिल्ल्ली": (28.6139, 77.2090),
            "नई दिल्ली": (28.6139, 77.2090),
            "mumbai": (19.0760, 72.8777),
            "मुंबई": (19.0760, 72.8777),
            "bangalore": (12.9716, 77.5946),
            "bengaluru": (12.9716, 77.5946),
            "chennai": (13.0827, 80.2707),
            "kolkata": (22.5726, 88.3639),
            "hyderabad": (17.3850, 78.4867),
            "pune": (18.5204, 73.8567),
            "ahmedabad": (23.0225, 72.5714),
            "jaipur": (26.9124, 75.7873),
            "lucknow": (26.8467, 80.9462),
            "noida": (28.5355, 77.3910),
            "gurgaon": (28.4595, 77.0266),
            "india": (20.5937, 78.9629),
            "भारत": (20.5937, 78.9629),

            # World Countries
            "israel": (31.0461, 34.8516),
            "usa": (37.0902, -95.7129),
            "united states": (37.0902, -95.7129),
            "america": (37.0902, -95.7129),
            "russia": (61.5240, 105.3188),
            "ukraine": (48.3794, 31.1656),
            "china": (35.8617, 104.1954),
            "uk": (55.3781, -3.4360),
            "united kingdom": (55.3781, -3.4360),
            "germany": (51.1657, 10.4515),
            "france": (46.2276, 2.2137),
            "canada": (56.1304, -106.3468),
            "australia": (-25.2744, 133.7751),
            "japan": (36.2048, 138.2529),
            "brazil": (-14.2350, -51.9253),
            "pakistan": (30.3753, 69.3451),
            "bangladesh": (23.6850, 90.3563),
            "uae": (23.4241, 53.8478),
            "dubai": (25.2048, 55.2708),
            "saudi arabia": (23.8859, 45.0792),

            # Global Cities / Trending Locations
            "tel aviv": (32.0853, 34.7818),
            "jerusalem": (31.7683, 35.2137),
            "gaza": (31.5017, 34.4668),
            "kyiv": (50.4501, 30.5234),
            "moscow": (55.7558, 37.6173),
            "new york": (40.7128, -74.0060),
            "london": (51.5074, -0.1278),
            "paris": (48.8566, 2.3522),
            "tokyo": (35.6762, 139.6503),
            "washington": (38.9072, -77.0369),
            "beijing": (39.9042, 116.4074),
        }

    def perform_search(self, keyword):
        all_posts = []
        current_idd = 1
        twitter_raw = self._fetch_twitter(keyword)
        for post in twitter_raw:
            text = post.get("text", "")
            loc_name, lat, lng = self._extract_location(text, keyword, post_metadata=post)
            all_posts.append(
                {
                    "id": current_idd,
                    "post_id": post.get("id"),
                    "post_title": text[:50] + "..." if len(text) > 50 else text,
                    "post_text": text,
                    "post_url": post.get("permalink"),
                    "platform": "twitter",
                    "author": post.get("author", ""),
                    "published_at": post.get("created_at"),
                    "extra_details": post.get("geo") or {},
                    "location_name": loc_name,
                    "latitude": lat,
                    "longitude": lng,
                }
            )
            current_idd += 1

        instagram_raw = self._fetch_instagram(keyword)
        for post in instagram_raw:
            caption = post.get("caption", "")
            loc_name, lat, lng = self._extract_location(caption, keyword, post_metadata=post)
            all_posts.append(
                {
                    "id": current_idd,
                    "post_id": post.get("id"),
                    "post_title": caption[:50].replace("\n", " ") if caption else "Instagram Post",
                    "post_text": caption,
                    "post_url": post.get("permalink"),
                    "platform": "instagram",
                    "author": post.get("username", ""), 
                    "published_at": post.get("timestamp"),
                    "extra_details": {
                        "media_type": post.get("media_type"),
                        "media_url": post.get("media_url"),
                        "location": post.get("location"),
                    },
                    "location_name": loc_name,
                    "latitude": lat,
                    "longitude": lng,
                }
            )
            current_idd += 1

        youtube_raw = self._fetch_youtube(keyword)
        for post in youtube_raw:
            text = post.get("description", "")
            loc_name, lat, lng = self._extract_location(text, keyword, post_metadata=post)
            all_posts.append(
                {
                    "id": current_idd,
                    "post_id": post.get("id"),
                    "post_title": post.get("title"),
                    "post_text": text,
                    "post_url": post.get("permalink"),
                    "platform": "youtube",
                    "author": post.get("author"),
                    "published_at": post.get("published_at"),
                    "extra_details": {
                        **(post.get("extra_details", {})),
                        "location": post.get("location")
                    },
                    "location_name": loc_name,
                    "latitude": lat,
                    "longitude": lng,
                }
            )
            current_idd += 1
        
        add_to_sentiment_queue(all_posts, keyword=keyword)
        
        return {
            "youtube": len(youtube_raw),
            "instagram": len(instagram_raw),
            "twitter": len(twitter_raw),
        }


    def get(self, request):
        keyword = request.query_params.get("keyword")
        if not keyword:
            return Response({"error": "Keyword is required"}, status=400)

        counts = self.perform_search(keyword)
        return Response(
            {
                "success": True,
                "message": f"Data for '{keyword}' successfully fetched and sent for sentiment analysis.",
                "counts": counts,
            }
        )


class ScraperStatusView(SocialMediaSearchView):
    """View to check if API keys are working correctly"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        keyword = "news"
        status = {}
        
        # Test YouTube
        yt_results = self._fetch_youtube(keyword)
        status['youtube'] = {
            'configured': bool(settings.YOUTUBE_API_KEY),
            'working': len(yt_results) > 0,
            'count': len(yt_results)
        }

        # Test Twitter
        tw_results = self._fetch_twitter(keyword)
        status['twitter'] = {
            'configured': bool(settings.TWITTER_BEARER_TOKEN),
            'working': len(tw_results) > 0,
            'count': len(tw_results)
        }

        # Test Instagram
        ig_results = self._fetch_instagram(keyword)
        status['instagram'] = {
            'configured': bool(settings.INSTAGRAM_ACCESS_TOKEN and settings.INSTAGRAM_BUSINESS_ACCOUNT_ID),
            'working': len(ig_results) > 0,
            'count': len(ig_results)
        }

        return Response({
            "success": True,
            "platforms": status
        })


class UserKeywordSearchTriggerView(SocialMediaSearchView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_keywords = User_Keyword.objects.filter(user=request.user).values_list("keyword", flat=True)
        
        if not user_keywords:
            return Response({"error": "No keywords found for this user. Please add keywords first."}, status=400)

        total_counts = {
            "youtube": 0,
            "instagram": 0,
            "twitter": 0,
        }
        processed_keywords = []

        for kw in user_keywords:
            counts = self.perform_search(kw)
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
    permission_classes = [AllowAny]

    def get(self, request):
        keyword_filter = request.query_params.get("keyword")
        
        # If user is authenticated, we can filter by their keywords if no specific keyword is asked
        if request.user.is_authenticated:
            user_keywords = list(
                User_Keyword.objects.filter(user=request.user)
                .values_list("keyword", flat=True)
            )
        else:
            user_keywords = []

        sentiments = Sentiment.objects.select_related("post").order_by("-analyzed_at")

        if keyword_filter:
            # If a specific keyword is requested via query param
            sentiments = sentiments.filter(keyword__iexact=keyword_filter)
            
            if request.user.is_authenticated:
                # Add this keyword to the user's keywords so it shows up in their dashboard
                User_Keyword.objects.get_or_create(user=request.user, keyword=keyword_filter.strip())

            # Auto-trigger a search if we have NO data for this keyword
            if not sentiments.exists():
                try:
                    search_view = SocialMediaSearchView()
                    search_view.perform_search(keyword_filter)
                except Exception as e:
                    print(f"Error auto-triggering search: {e}")
                    
        elif user_keywords:
            # Otherwise, if logged in, show their own keyword results
            sentiments = sentiments.filter(keyword__in=user_keywords)
        # If neither, 'sentiments' remains the full list (or we could limit to most recent)

        sentiment_filter = request.query_params.get("sentiment")
        if sentiment_filter:
            sentiments = sentiments.filter(sentiment_label__iexact=sentiment_filter)

        platform_filter = request.query_params.get("platform")
        if platform_filter:
            sentiments = sentiments.filter(post__platform__iexact=platform_filter)

        # Geo filters: countries, states, cities are location names
        countries_param = request.query_params.get("countries", "")
        states_param = request.query_params.get("states", "")
        cities_param = request.query_params.get("cities", "")

        location_filters = []
        if countries_param:
            location_filters.extend([c.strip() for c in countries_param.split(",") if c.strip()])
        if states_param:
            location_filters.extend([s.strip() for s in states_param.split(",") if s.strip()])
        if cities_param:
            location_filters.extend([c.strip() for c in cities_param.split(",") if c.strip()])

        if location_filters:
            from django.db.models import Q as LocationQ
            location_query = LocationQ()
            for loc in location_filters:
                location_query |= LocationQ(post__location_name__icontains=loc)
            sentiments = sentiments.filter(location_query)

        # Date filter
        date_param = request.query_params.get("date", "")
        if date_param:
            try:
                from datetime import date as date_cls
                from django.db.models.functions import TruncDate
                parsed_date = date_cls.fromisoformat(date_param)
                sentiments = sentiments.filter(post__published_at__date=parsed_date)
            except (ValueError, TypeError):
                pass  # Ignore bad date formats

        # Support fetching all records without pagination
        all_data = request.query_params.get("all", "false").lower() == "true"
        if all_data:
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
                max(int(request.query_params.get("page_size", 20)), 1), 1000
            )
        except (ValueError, TypeError):
            page_size = 20

        total_count = sentiments.count()
        total_pages = (total_count + page_size - 1) // page_size if total_count else 0
        start = (page - 1) * page_size
        end = start + page_size

        page_results = sentiments[start:end]
        serializer = UserSentimentSerializer(page_results, many=True)



class LiveSearchView(SocialMediaSearchView):
    """
    Live search: fetches directly from YouTube API and returns results
    instantly WITHOUT saving to DB.
    """
    permission_classes = [AllowAny]

    def _collect_all_page_tokens(self, keyword):
        """Step 1: Collect all pageTokens by paginating search (fast - no detail fetch)."""
        search_url = "https://www.googleapis.com/youtube/v3/search"
        pages = []  # list of (video_ids, next_page_token)
        next_token = None

        while True:
            params = {
                "part": "id",  # Only IDs — fastest, cheapest
                "q": keyword,
                "type": "video",
                "key": settings.YOUTUBE_API_KEY,
                "maxResults": 50,
            }
            if next_token:
                params["pageToken"] = next_token
            try:
                resp = requests.get(search_url, params=params, timeout=15)
                data = resp.json()
            except Exception as e:
                print(f"Token collect error: {e}")
                break

            if "error" in data:
                print(f"YouTube error: {data['error'].get('message')}")
                break

            video_ids = [
                item["id"]["videoId"]
                for item in data.get("items", [])
                if item.get("id", {}).get("kind") == "youtube#video"
            ]
            if video_ids:
                pages.append(video_ids)

            next_token = data.get("nextPageToken")
            if not next_token:
                break

        return pages  # list of batches of video IDs

    def _fetch_details_batch(self, video_ids):
        """Fetch snippet+recordingDetails for a batch of up to 50 video IDs."""
        details_url = "https://www.googleapis.com/youtube/v3/videos"
        try:
            resp = requests.get(details_url, params={
                "part": "snippet,recordingDetails",
                "id": ",".join(video_ids),
                "key": settings.YOUTUBE_API_KEY,
            }, timeout=15)
            return resp.json().get("items", [])
        except Exception as e:
            print(f"Details batch error: {e}")
            return []

    def get(self, request):
        keyword = request.query_params.get("keyword", "").strip()
        if not keyword:
            return Response({"error": "Keyword is required."}, status=400)

        if not settings.YOUTUBE_API_KEY:
            return Response({"error": "YouTube API key not configured."}, status=500)

        # Step 1: Collect all video ID batches across all pages (sequential but fast - only IDs)
        id_batches = self._collect_all_page_tokens(keyword)
        print(f"[LiveSearch] Collected {len(id_batches)} pages of video IDs for '{keyword}'")

        if not id_batches:
            return Response({"success": True, "count": 0, "results": []})

        # Step 2: Fetch details for ALL batches IN PARALLEL using threads
        from concurrent.futures import ThreadPoolExecutor, as_completed
        all_items = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(self._fetch_details_batch, batch): batch for batch in id_batches}
            for future in as_completed(futures):
                all_items.extend(future.result())

        print(f"[LiveSearch] Total videos fetched: {len(all_items)}")

        # Step 3: Format + sentiment analysis
        from textblob import TextBlob
        formatted = []
        for item in all_items:
            snippet = item.get("snippet", {})
            rec = item.get("recordingDetails", {})
            location = rec.get("location", {})

            title = snippet.get("title", "")
            description = snippet.get("description", "")
            combined_text = f"{title} {description}".strip()

            post_metadata = {
                "location": {
                    "latitude": location.get("latitude"),
                    "longitude": location.get("longitude"),
                    "name": rec.get("locationDescription"),
                }
            }
            loc_name, lat, lng = self._extract_location(combined_text, keyword, post_metadata=post_metadata)

            raw_sentiment = "Neutral"
            try:
                polarity = TextBlob(combined_text).sentiment.polarity
                if polarity > 0.05:
                    raw_sentiment = "Positive"
                elif polarity < -0.05:
                    raw_sentiment = "Negative"
            except Exception:
                pass

            formatted.append({
                "id": f"live_{item.get('id', '')}",
                "post_title": title,
                "post_text": description,
                "post_url": f"https://www.youtube.com/watch?v={item.get('id', '')}",
                "platform": "youtube",
                "author": snippet.get("channelTitle", ""),
                "published_at": snippet.get("publishedAt", ""),
                "analyzed_at": None,
                "keyword": keyword,
                "sentiment_label": raw_sentiment,
                "location_name": loc_name,
                "latitude": lat,
                "longitude": lng,
                "is_live": True,
            })

        # Sort newest first
        formatted.sort(key=lambda x: x.get("published_at") or "", reverse=True)

        return Response({
            "success": True,
            "count": len(formatted),
            "results": formatted,
        })

        """Fetch ONE page from YouTube API. Returns (results, next_page_token)."""
        if not settings.YOUTUBE_API_KEY:
            return [], None


