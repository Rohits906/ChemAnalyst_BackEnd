from django.http import JsonResponse
from django.db.models import Count, Q
from django.views.decorators.http import require_GET
from .models import SentimentPost


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
        bar_data.append({
            "name": item["platform__name"].title(),
            "positive": item["positive"],
            "negative": item["negative"],
        })

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
        cards_data.append({
            "name": item["name"],
            "count": item["positive"] + item["negative"],
            "icon": item["name"],
        })

    # RECENT POSTS
    recent_posts_queryset = posts.order_by("-created_at")[:5]

    recent_posts = []
    for post in recent_posts_queryset:
        recent_posts.append({
            "id": post.id,
            "platform": post.platform.name.title(),
            "content": post.content,
            "sentiment": post.sentiment,
            "keyword": post.keyword,
            "created_at": post.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        })

    # FINAL RESPONSE
    return JsonResponse({
        "bar": bar_data,
        "donut": donut_data,
        "cards": cards_data,
        "recentPosts": recent_posts,
    })