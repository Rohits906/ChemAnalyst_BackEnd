import requests
from django.conf import settings
from django.http import JsonResponse
from django.db.models import Count, Q
from django.views.decorators.http import require_GET
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import SentimentPost, User_Keyword, Sentiment
from .serializers import UserKeywordSerializer, UserSentimentSerializer
from .producers import add_to_sentiment_quene


@require_GET
def sentiment_dashboard(request):
    keyword = request.GET.get("keyword")
    platform = request.GET.get("platform")

    posts = SentimentPost.objects.select_related("platform").all()

    # Apply Filters
    if keyword:
        posts = posts.filter(content__icontains=keyword)

    if platform:
        posts = posts.filter(platform__name__iexact=platform)

    # BAR CHART DATA
    bar_queryset = (
        posts.values("platform__name")
        .annotate(
            positive=Count("id", filter=Q(sentiment="positive")),
            negative=Count("id", filter=Q(sentiment="negative")),
        )
        .order_by("platform__name")
    )

    bar_data = []
    for item in bar_queryset:
        bar_data.append(
            {
                "name": item["platform__name"].title(),
                "positive": item["positive"],
                "negative": item["negative"],
            }
        )

    # DONUT DATA
    positive_count = posts.filter(sentiment="positive").count()
    negative_count = posts.filter(sentiment="negative").count()

    donut_data = [
        {
            "name": "Positive",
            "value": positive_count,
            "color": "#8c84c4",
        },
        {
            "name": "Negative",
            "value": negative_count,
            "color": "#1e1b4b",
        },
    ]

    # CARDS DATA
    cards_data = []
    for item in bar_data:
        cards_data.append(
            {
                "name": item["name"],
                "count": item["positive"] + item["negative"],
                "icon": item["name"],
            }
        )

    # RECENT POSTS
    recent_posts_queryset = posts.order_by("-created_at")[:5]

    recent_posts = []
    for post in recent_posts_queryset:
        recent_posts.append(
            {
                "id": post.id,
                "platform": post.platform.name.title(),
                "content": post.content,
                "sentiment": post.sentiment,
                "keyword": post.keyword,
                "created_at": post.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )

    # FINAL RESPONSE
    return JsonResponse(
        {
            "bar": bar_data,
            "donut": donut_data,
            "cards": cards_data,
            "recentPosts": recent_posts,
        }
    )


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
        params = {
            "query": keyword,
            "tweet.fields": "created_at,text",
            "max_results": 15,
        }
        try:
            response = requests.get(url, headers=headers, params=params)
            data = response.json()
            print(data)
            results = []
            if "data" in data:
                for item in data["data"]:
                    results.append(
                        {
                            "id": item["id"],
                            "text": item["text"],
                            "created_at": item.get("created_at"),
                            "permalink": f"https://twitter.com/anyuser/status/{item['id']}",
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
            all_posts.append(
                {
                    "id": current_idd,
                    "post_id": post.get("id"),
                    "post_title": "N/A",
                    "post_text": post.get("text"),
                    "post_url": post.get("permalink"),
                    "platform": "twitter",
                    "author": "N/A",
                    "published_at": post.get("created_at"),
                    "extra_details": {},
                }
            )
            current_idd += 1

        instagram_raw = self._fetch_instagram(keyword)
        for post in instagram_raw:
            all_posts.append(
                {
                    "id": current_idd,
                    "post_id": post.get("id"),
                    "post_title": post.get("caption", "")[:50].replace("\n", " "),
                    "post_text": post.get("caption", ""),
                    "post_url": post.get("permalink"),
                    "platform": "instagram",
                    "author": "N/A",
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


class UserSentimentView(APIView):
    """
    Returns sentiment analysis results that belong to the
    authenticated user's keywords.

    Query params (all optional):
        - keyword   : filter by a specific keyword
        - sentiment : filter by sentiment_label (e.g. positive, negative)
        - platform  : filter by post platform (e.g. youtube, twitter)
        - page      : page number (default 1)
        - page_size : results per page (default 20, max 100)
    """
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

        # 2. Query sentiments whose keyword is in the user's keyword list
        sentiments = (
            Sentiment.objects
            .filter(keyword__in=user_keywords)
            .select_related("post")
            .order_by("-analyzed_at")
        )

        # 3. Optional filters
        keyword_filter = request.query_params.get("keyword")
        if keyword_filter:
            sentiments = sentiments.filter(keyword__iexact=keyword_filter)

        sentiment_filter = request.query_params.get("sentiment")
        if sentiment_filter:
            sentiments = sentiments.filter(sentiment_label__iexact=sentiment_filter)

        platform_filter = request.query_params.get("platform")
        if platform_filter:
            sentiments = sentiments.filter(post__platform__iexact=platform_filter)

        # 4. Pagination
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

