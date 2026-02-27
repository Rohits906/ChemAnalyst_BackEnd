import requests
from django.conf import settings
from django.http import JsonResponse
from django.db.models import Count, Q
import requests
from django.conf import settings
from django.http import JsonResponse
from django.db.models import Count, Q
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from core.kafka_client import kafka_producer
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import DBSaveQueue, SentimentPost, User_Keyword, Sentiment
from .serializers import UserKeywordSerializer, UserSentimentSerializer
from .producers import add_to_sentiment_quene
import json


@require_GET
def sentiment_dashboard(request):
    keyword = request.GET.get("keyword")
    
    posts = DBSaveQueue.objects.all()

    # Apply Filters
    if keyword:
        posts = posts.filter(post_text__icontains=keyword)

    # BAR CHART DATA (Example: grouping by model_used mapping if we had it, but for now we'll just mock)
    # The user hasn't specified exactly how they want the dashboard changed, 
    # but we must ensure it doesn't crash on the new schema.
    bar_data = []

    # DONUT DATA
    positive_count = posts.filter(sentiment_label="positive").count()
    negative_count = posts.filter(sentiment_label="negative").count()

    donut_data = [
        {"name": "Positive", "value": positive_count, "color": "#8c84c4"},
        {"name": "Negative", "value": negative_count, "color": "#1e1b4b"},
    ]

    cards_data = []

    # RECENT POSTS
    recent_posts_queryset = posts.order_by("-saved_at")[:5]

    recent_posts = []
    for post in recent_posts_queryset:
        recent_posts.append({
            "id": post.id,
            "post_id": post.post_id,
            "content": post.post_text,
            "sentiment": post.sentiment_label,
            "author": post.author_name,
            "saved_at": post.saved_at.strftime("%Y-%m-%d %H:%M:%S"),
        })

    # FINAL RESPONSE
    return JsonResponse({
        "bar": bar_data,
        "donut": donut_data,
        "cards": cards_data,
        "recentPosts": recent_posts,
    })


@require_POST
@csrf_exempt
def publish_test_sentiment(request):
    """
    Test endpoint to publish a mock payload to the new Kafka topic.
    """
    try:
        body = json.loads(request.body)
        
        # Dispatch this exact payload to Kafka (Sentiment Queue)
        payload = {
            "post_id": body.get("post_id", "12345"),
            "post_url": body.get("post_url", "https://example.com/p/12345"),
            "comments": body.get("comments", ""),
            "author_name": body.get("author_name", "John Doe"),
            "author_id": body.get("author_id", "user_1"),
            "post_caption": body.get("post_caption", "This new architecture is great!"),
            "raw_json": body.get("raw_json", {"source": "api_test"})
        }

        # Produce to Sentiment Queue topic
        kafka_producer.produce_message(topic="sentiment_queue", message=payload)
        kafka_producer.flush()

        return JsonResponse({"success": True, "message": "Message sent to Kafka topic 'sentiment_queue'", "payload": payload}, status=200)

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)


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

    def _fetch_youtube(self, keyword):
        if not settings.YOUTUBE_API_KEY:
            return []
        url = "https://www.googleapis.com/youtube/v3/search"
        params = {
            "part": "snippet",
            "q": keyword,
            "type": "video",
            "key": settings.YOUTUBE_API_KEY,
            "maxResults": 5,
        }
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

    def _fetch_twitter(self, keyword):
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
            "max_results": 15,
        }
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

    def perform_search(self, keyword):
        all_posts = []
        current_idd = 1
        twitter_raw = self._fetch_twitter(keyword)
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
                    "extra_details": {
                        "media_type": post.get("media_type"),
                        "media_url": post.get("media_url"),
                    },
                }
            )
            current_idd += 1

        youtube_raw = self._fetch_youtube(keyword)
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
                    "extra_details": post.get("extra_details", {}),
                }
            )
            current_idd += 1
        
        add_to_sentiment_quene(all_posts, keyword=keyword)
        
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

>>>>>>> 0be2a903ce9742cebe62a198499cc6d9a9b8704d
