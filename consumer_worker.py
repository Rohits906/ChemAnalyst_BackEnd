import os
import django
import json
import uuid
from kafka import KafkaConsumer
from django.utils import timezone
from dateutil import parser
import uuid
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.conf import settings
from transformers import pipeline
from sentiment.models import Post, Sentiment

MODEL_NAME = "cardiffnlp/twitter-roberta-base-sentiment"
sentiment_pipeline = pipeline(
    "sentiment-analysis", model=MODEL_NAME
)

label_map = {"LABEL_0": "Negative", "LABEL_1": "Neutral", "LABEL_2": "Positive"}

def analyze_sentiment(text):
    if not text:
        return {
            "sentiment": "Neutral",
            "confidence_score": 0.0,
        }
    
    result = sentiment_pipeline(text[:512])[0]
    sentiment = label_map[result["label"]]
    confidence = float(result["score"])

    return {
        "sentiment": sentiment,
        "confidence_score": confidence,
    }

sentiment_consumer = KafkaConsumer(
    settings.KAFKA_SENTIMENT_TOPIC,
    bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
    value_deserializer=lambda x: json.loads(x.decode("utf-8")),
    group_id="sentiment-group",
    auto_offset_reset="latest",
)

print(f"Started the consumer on topic: {settings.KAFKA_SENTIMENT_TOPIC}")

for msg in sentiment_consumer:
    data = msg.value
    print(f"Processing post: {data.get('post_id')}")

    try:
        platform_post_id = data.get("post_id") or f"unknown_{uuid.uuid4()}"
        platform = data.get("platform") or "unknown"
        post_text = data.get("post_text") or "N/A"
        author_name = data.get("author") or "N/A"
        post_url = data.get("post_url") or "https://example.com"
        published_at_str = data.get("published_at")
        if published_at_str:
            try:
                published_at = parser.isoparse(published_at_str)
            except Exception:
                published_at = timezone.now()
        else:
            published_at = timezone.now()

        post_obj, created = Post.objects.get_or_create(
            platform=platform,
            platform_post_id=platform_post_id,
            defaults={
                "author_name": author_name,
                "post_text": post_text,
                "post_url": post_url,
                "published_at": published_at,
                "raw_json": data.get("extra_details") or {}
            }
        )

        analysis = analyze_sentiment(post_text)

        Sentiment.objects.create(
            post=post_obj,
            keyword=data.get("keyword") or "N/A",
            sentiment_label=analysis["sentiment"],
            confidence_score=analysis["confidence_score"],
            model_used=MODEL_NAME
        )

        print(f"Successfully saved sentiment for post {platform_post_id}: {analysis['sentiment']}")

    except Exception as e:
        print(f"Error processing message: {e}")
