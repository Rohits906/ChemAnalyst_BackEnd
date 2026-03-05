import os
import django
import json
import uuid
import time
from django.utils import timezone
from dateutil import parser

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.conf import settings
from textblob import TextBlob
from sentiment.models import Post, Sentiment
from platforms.models import ChannelPost

MODEL_NAME = "TextBlob"

def analyze_sentiment(text):
    if not text:
        return {
            "sentiment": "Neutral",
            "confidence_score": 0.0,
        }
    
    analysis = TextBlob(text)
    polarity = analysis.sentiment.polarity
    
    if polarity > 0:
        sentiment = "Positive"
    elif polarity < 0:
        sentiment = "Negative"
    else:
        sentiment = "Neutral"

    return {
        "sentiment": sentiment,
        "confidence_score": abs(polarity),
    }

def process_data(data):
    print(f"Processing post: {data.get('post_id')}")
    try:
        platform_post_id = data.get("post_id") or f"unknown_{uuid.uuid4()}"
        platform = data.get("platform") or "unknown"
        post_text = data.get("post_text") or ""
        post_title = data.get("post_title") or (post_text[:100] if post_text else "")
        author_name = data.get("author") or ""
        post_url = data.get("post_url") or "https://example.com"
        published_at_str = data.get("published_at")
        latitude = data.get("latitude")
        longitude = data.get("longitude")
        location_name = data.get("location_name") or ""
        
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
                "post_title": post_title,
                "post_text": post_text,
                "post_url": post_url,
                "published_at": published_at,
                "raw_json": data.get("extra_details") or {},
                "latitude": latitude,
                "longitude": longitude,
                "location_name": location_name,
            }
        )

        if not created and (not post_obj.post_title or post_obj.post_title == "N/A"):
            post_obj.post_title = post_title
            post_obj.save()

        analysis = analyze_sentiment(post_text)

        Sentiment.objects.create(
            post=post_obj,
            keyword=data.get("keyword") or "N/A",
            sentiment_label=analysis["sentiment"],
            confidence_score=analysis["confidence_score"],
            model_used=MODEL_NAME
        )

        # Update ChannelPost sentiment if it exists
        try:
            channel_post = ChannelPost.objects.filter(
                platform__name=platform,
                platform_post_id=platform_post_id
            ).first()
            if channel_post:
                channel_post.sentiment_label = analysis["sentiment"]
                channel_post.sentiment_score = analysis["confidence_score"]
                channel_post.save()
        except Exception as e:
            print(f"Warning: Could not update ChannelPost sentiment: {e}")

        print(f"Successfully saved sentiment for post {platform_post_id}: {analysis['sentiment']}")
        return True
    except Exception as e:
        print(f"Error processing message: {e}")
        return False

def run_kafka_consumer():
    from kafka import KafkaConsumer
    try:
        sentiment_consumer = KafkaConsumer(
            settings.KAFKA_SENTIMENT_TOPIC,
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            value_deserializer=lambda x: json.loads(x.decode("utf-8")),
            group_id="sentiment-group",
            auto_offset_reset="earliest",
        )
        print(f"Started the Kafka consumer on topic: {settings.KAFKA_SENTIMENT_TOPIC}")
        for msg in sentiment_consumer:
            process_data(msg.value)
    except Exception as e:
        print(f"Kafka connection failed: {e}")
        return False
    return True


if __name__ == "__main__":
    if not run_kafka_consumer():
        print("Failed to start Kafka consumer. Ensure Kafka is running.")
