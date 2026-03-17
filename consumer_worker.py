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
from platforms.models import ChannelPost

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

def safe_json_deserializer(x):
    if not x:
        return {}
    try:
        return json.loads(x.decode("utf-8"))
    except json.JSONDecodeError:
        return {}

sentiment_consumer = KafkaConsumer(
    settings.KAFKA_SENTIMENT_TOPIC,
    bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
    value_deserializer=safe_json_deserializer,
    group_id="sentiment-group",
    auto_offset_reset="latest",
)

print(f"Started the consumer on topic: {settings.KAFKA_SENTIMENT_TOPIC}")

for msg in sentiment_consumer:
    data = msg.value
    keyword = data.get('keyword', 'N/A')
    print(f"Processing post: {data.get('post_id')} for keyword: {keyword}")

    try:
        platform_post_id = data.get("post_id") or f"unknown_{uuid.uuid4()}"
        platform = data.get("platform") or "unknown"
        post_text = data.get("post_text") or ""
        post_title = data.get("post_title") or (post_text[:100] if post_text else "")
        author_name = data.get("author") or ""
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
                "post_title": post_title,
                "post_text": post_text,
                "post_url": post_url,
                "published_at": published_at,
                "latitude": data.get("latitude"),
                "longitude": data.get("longitude"),
                "location_name": data.get("location_name") or "",
                "location_type": data.get("location_type") or "",
                "raw_json": data.get("extra_details") or {}
            }
        )

        if not created:
            updated = False
            if not post_obj.post_title or post_obj.post_title == "N/A":
                post_obj.post_title = post_title
                updated = True
            # Only update location if real data is available from API
            if post_obj.latitude is None and data.get("latitude") is not None:
                post_obj.latitude = data.get("latitude")
                updated = True
            if post_obj.longitude is None and data.get("longitude") is not None:
                post_obj.longitude = data.get("longitude")
                updated = True
            real_loc = data.get("location_name")
            if (not post_obj.location_name or post_obj.location_name in ("", "Global")) and real_loc:
                post_obj.location_name = real_loc
                updated = True
            if updated:
                post_obj.save()

        analysis = analyze_sentiment(post_text)

        Sentiment.objects.update_or_create(
            post=post_obj,
            keyword=(data.get("keyword") or "N/A").strip(),
            defaults={
                "sentiment_label": analysis["sentiment"],
                "confidence_score": analysis["confidence_score"],
                "model_used": MODEL_NAME
            }
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

    except Exception as e:
        print(f"Error processing message: {e}")
