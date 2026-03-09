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
import random

# Predefined locations for heuristic tagging when source API lacks geo data
HEURISTIC_LOCATIONS = [
    {"name": "Lucknow", "lat": 26.8467, "lng": 80.9462, "type": "city"},
    {"name": "Mumbai", "lat": 19.0760, "lng": 72.8777, "type": "city"},
    {"name": "Delhi", "lat": 28.6139, "lng": 77.2090, "type": "city"},
    {"name": "New York", "lat": 40.7128, "lng": -74.0060, "type": "city"},
    {"name": "London", "lat": 51.5074, "lng": -0.1278, "type": "city"},
    {"name": "Paris", "lat": 48.8566, "lng": 2.3522, "type": "city"},
    {"name": "Tokyo", "lat": 35.6895, "lng": 139.6917, "type": "city"},
    {"name": "Sydney", "lat": -33.8688, "lng": 151.2093, "type": "city"},
    {"name": "Dubai", "lat": 25.2048, "lng": 55.2708, "type": "city"},
    {"name": "Singapore", "lat": 1.3521, "lng": 103.8198, "type": "city"},
]


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
                    "fields": "id,caption,media_type,media_url,permalink,timestamp",
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
            print("error occured", e)
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
            response = requests.get(url, headers=headers, params=params)
            data = response.json()
            results = []
            
            # Create a map for user data
            users_map = {}
            if "includes" in data and "users" in data["includes"]:
                for user in data["includes"]["users"]:
                    users_map[user["id"]] = user["username"]

            if "data" in data:
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
            return results
        except Exception as e:
            print("error occured", e)
            return []

    def perform_search(self, keyword, hours=None):
        all_posts = []
        current_idd = 1
        twitter_raw = self._fetch_twitter(keyword, hours=hours)
        for post in twitter_raw:
            text = post.get("text", "")
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
                    "latitude": None,
                    "longitude": None,
                    "location_name": "",
                    "location_type": "",
                    "extra_details": {},
                }
            )
            current_idd += 1

        instagram_raw = self._fetch_instagram(keyword)
        for post in instagram_raw:
            caption = post.get("caption", "")
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
                    "latitude": None,
                    "longitude": None,
                    "location_name": "",
                    "location_type": "",
                    "extra_details": {
                        "media_type": post.get("media_type"),
                        "media_url": post.get("media_url"),
                    },
                }
            )
            current_idd += 1

        youtube_raw = self._fetch_youtube(keyword, hours=hours)
        for post in youtube_raw:
            all_posts.append(
                {
                    "id": current_idd,
                    "post_id": post.get("id"),
                    "post_title": post.get("title"),
                    "post_text": post.get("description"),
                    "post_url": post.get("permalink"),
                    "platform": "youtube",
                    "author": post.get("author"),
                    "published_at": post.get("published_at"),
                    "latitude": None,
                    "longitude": None,
                    "location_name": "",
                    "location_type": "",
                    "extra_details": post.get("extra_details", {}),
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
                            # Handling ISO 8601 strings commonly returned by APIs
                            dt = datetime.fromisoformat(pub_at.replace("Z", "+00:00"))
                            if dt >= time_threshold:
                                filtered_posts.append(post)
                        except ValueError:
                            # Fallback if format is slightly different
                            filtered_posts.append(post)
                    else:
                        filtered_posts.append(post)
                all_posts = filtered_posts
            except ValueError:
                pass

        add_to_sentiment_quene(all_posts, keyword=keyword)
        
        # Re-calculate counts if filtered
        yt_count = len([p for p in all_posts if p['platform'] == 'youtube'])
        ig_count = len([p for p in all_posts if p['platform'] == 'instagram'])
        tw_count = len([p for p in all_posts if p['platform'] == 'twitter'])

        return {
            "youtube": yt_count,
            "instagram": ig_count,
            "twitter": tw_count,
        }

    def get(self, request):
        keyword = request.query_params.get("keyword")
        hours = request.query_params.get("hours")
        if not keyword:
            return Response({"error": "Keyword is required"}, status=400)

        counts = self.perform_search(keyword, hours=hours)
        
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
            .select_related("post")
            .order_by("-analyzed_at")
        )

        keyword_filter = request.query_params.get("keyword")
        if keyword_filter:
            sentiments = sentiments.filter(keyword__iexact=keyword_filter)
        else:
            # If no specific keyword filter, fall back to user's registered keywords
            sentiments = sentiments.filter(keyword__in=user_keywords)

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

