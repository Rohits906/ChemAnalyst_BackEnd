import json
import uuid
from datetime import datetime
from django.core.management.base import BaseCommand
from django.conf import settings
from confluent_kafka import Consumer, KafkaException, KafkaError
from sentiment.models import DBSaveQueue

class Command(BaseCommand):
    help = 'Runs a Kafka Consumer to listen for new sentiment posts'

    def handle(self, *args, **kwargs):
        conf = {
            'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS,
            'group.id': 'sentiment_consumer_group',
            'auto.offset.reset': 'earliest',
            'enable.auto.commit': False  # Disable auto-commit to manually acknowledge
        }

        consumer = Consumer(conf)
        topic = 'sentiment_queue'
        
        consumer.subscribe([topic])
        self.stdout.write(self.style.SUCCESS(f"Started Kafka Consumer on topic: '{topic}'..."))
        
        try:
            while True:
                msg = consumer.poll(timeout=1.0)
                if msg is None:
                    continue
                    
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    else:
                        raise KafkaException(msg.error())
                        
                # Process valid message
                try:
                    raw_data = msg.value().decode('utf-8')
                    data = json.loads(raw_data)
                    
                    # Process and save to DB
                    success = self.process_message(data)
                    
                    if success:
                        # Message successfully saved in DB, commit the offset (removes/acknowledges from queue)
                        consumer.commit(asynchronous=False)
                        self.stdout.write(self.style.SUCCESS("Message successfully processed and removed from queue."))
                    
                except json.JSONDecodeError:
                    self.stdout.write(self.style.ERROR(f"Invalid JSON received: {msg.value()}"))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"Error processing message: {str(e)}"))
                    
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Stopping Consumer..."))
        finally:
            consumer.close()
            
    def process_message(self, data):
        """
        Parses the JSON message from 'Sentiment Queue' and saves it to 'DBSaveQueue'.
        Expected JSON format:
        {
            "post_id": "string",
            "post_url": "string",
            "comments": "string (optional)",
            "author_name": "string",
            "author_id": "string",
            "post_caption": "string",
            "raw_json": "json object"
        }
        """
        post_id = data.get("post_id")
        post_url = data.get("post_url")
        post_caption = data.get("post_caption")
        
        if not post_id or not post_caption:
            self.stdout.write(self.style.ERROR(f"Missing required fields (post_id, post_caption) in msg: {data}"))
            return False

        try:
            # Map and save exactly as requested by the user
            post, created = DBSaveQueue.objects.update_or_create(
                post_id=post_id,
                defaults={
                    "post_url": post_url,
                    "post_text": post_caption,
                    "author_name": data.get("author_name"),
                    "author_id": data.get("author_id"),
                    "raw_json": data.get("raw_json"),
                    
                    # These remain explicitly null until analyzed later
                    "sentiment_label": None,
                    "confidence_score": None,
                    "model_used": None,
                    "analyzed_at": None,
                }
            )

            action = "Created" if created else "Updated"
            self.stdout.write(self.style.SUCCESS(f"{action} DB Save Queue record for post {post_id}"))
            return True
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Database error while saving post {post_id}: {str(e)}"))
            return False
