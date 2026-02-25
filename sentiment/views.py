from django.http import JsonResponse
from django.db.models import Count, Q
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from core.kafka_client import kafka_producer
from .models import DBSaveQueue
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