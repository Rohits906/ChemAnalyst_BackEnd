import json
import uuid
import random
from datetime import datetime
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone
from kafka import KafkaConsumer, TopicPartition
from sentiment.models import Post, Sentiment, SentimentPlatform

class Command(BaseCommand):
    help = 'Runs a Kafka Consumer to listen for new sentiment posts and analyze them'

    def handle(self, *args, **kwargs):
        # Use the topic name from settings
        topic = settings.KAFKA_SENTIMENT_TOPIC
        
        try:
            consumer = KafkaConsumer(
                topic,
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                group_id='sentiment_consumer_group',
                auto_offset_reset='earliest',
                enable_auto_commit=False,
                value_deserializer=lambda x: json.loads(x.decode('utf-8')),
                api_version=(0, 10, 2)
            )
            
            self.stdout.write(self.style.SUCCESS(f"Started Kafka Consumer on topic: '{topic}'..."))
            
            for msg in consumer:
                try:
                    data = msg.value
                    self.stdout.write(self.style.SUCCESS(f"Processing message from partition {msg.partition}, offset {msg.offset}"))
                    
                    success = self.process_message(data)
                    
                    if success:
                        # Manual commit
                        consumer.commit()
                        self.stdout.write(self.style.SUCCESS(f"Successfully processed post: {data.get('post_id')}"))
                    
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"Error processing message: {str(e)}"))
                    
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Stopping Consumer..."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Kafka connection error: {e}"))
            
    def analyze_sentiment(self, text):
        """Simple keyword-based sentiment analysis for demonstration."""
        text_lower = text.lower()
        positive_words = ['good', 'great', 'awesome', 'excellent', 'happy', 'love', 'amazing', 'best']
        negative_words = ['bad', 'horrible', 'terrible', 'sad', 'hate', 'worst', 'disappointed', 'poor']
        
        pos_count = sum(1 for word in positive_words if word in text_lower)
        neg_count = sum(1 for word in negative_words if word in text_lower)
        
        if pos_count > neg_count:
            return "positive", 0.85
        elif neg_count > pos_count:
            return "negative", 0.85
        else:
            return "neutral", 0.5

    def process_message(self, data):
        """
        Processes the message, saves Post and Sentiment records.
        """
        post_id = data.get("post_id")
        platform_name = data.get("platform", "unknown").lower()
        post_text = data.get("post_text") or data.get("post_caption") or ""
        keyword = data.get("keyword", "N/A")
        
        if not post_id:
            return False

        try:
            # 1. Get or Create Platform
            # Ensure it is a valid platform choices from the model
            # models.SentimentPlatform.PLATFORM_CHOICES
            platform, _ = SentimentPlatform.objects.get_or_create(
                name=platform_name if platform_name in ['youtube', 'instagram', 'facebook', 'linkedin', 'twitter'] else 'twitter',
                defaults={'channel_id': data.get("author_id", "unknown")}
            )

            # 2. Save/Update Post
            published_at_str = data.get("published_at") or data.get("timestamp")
            if published_at_str:
                try:
                    # Remove Z and convert to datetime
                    ts = published_at_str.replace('Z', '+00:00')
                    published_at = datetime.fromisoformat(ts)
                except:
                    published_at = timezone.now()
            else:
                published_at = timezone.now()

            post, created = Post.objects.update_or_create(
                platform=platform_name,
                platform_post_id=post_id,
                defaults={
                    "author_name": data.get("author", data.get("author_name", "N/A")),
                    "author_id": data.get("author_id", "N/A"),
                    "post_title": data.get("post_title", post_text[:50]),
                    "post_text": post_text,
                    "post_url": data.get("post_url", ""),
                    "published_at": published_at,
                    "location_name": data.get("location_name", ""),
                    "location_type": data.get("location_type", "city").lower(),
                    "latitude": data.get("latitude"),
                    "longitude": data.get("longitude"),
                    "likes": data.get("extra_details", {}).get("likes", 0),
                    "comments": data.get("extra_details", {}).get("comments", 0),
                    "shares": data.get("extra_details", {}).get("shares", 0),
                    "raw_json": data.get("extra_details", {}),
                }
            )

            # 3. Analyze and Save Sentiment
            label, confidence = self.analyze_sentiment(post_text)
            
            Sentiment.objects.update_or_create(
                post=post,
                keyword=keyword,
                defaults={
                    "sentiment_label": label,
                    "confidence_score": confidence,
                    "model_used": "VaderSimplified",
                }
            )

            return True
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error in process_message: {str(e)}"))
            return False
