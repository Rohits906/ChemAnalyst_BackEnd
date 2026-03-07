import os
import json
import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime, timedelta
from kafka import KafkaConsumer
from django.conf import settings

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from platforms.models import Platform, ChannelStats, ChannelPost, PlatformFetchTask
from googleapiclient.discovery import build

from platforms.services import fetch_platform_data

# Initialize YouTube API
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY") or settings.YOUTUBE_API_KEY


# Removed redundant fetch_youtube_channel_data


def process_platform_fetch(message):
    """Process a platform fetch task from Kafka"""
    try:
        platform_id = message.get("platform_id")
        task_type = message.get("task_type", "update")
        
        platform = Platform.objects.get(id=platform_id)
        
        logger.info(f"📥 Processing {task_type} for: {platform.channel_id} ({platform.name})")
        
        # Create fetch task record
        fetch_task = PlatformFetchTask.objects.create(
            platform=platform,
            user=platform.user,
            task_type=task_type,
            status="processing",
        )
        
        # Use shared fetch_platform_data service
        success, message_text = fetch_platform_data(platform)
        
        # Update fetch task
        fetch_task.status = "completed" if success else "failed"
        if not success:
            fetch_task.error_message = message_text
        fetch_task.completed_at = timezone.now()
        fetch_task.save()
        
        logger.info(f"✓ Completed fetch for {platform.channel_id}: {fetch_task.status}")
        
    except Platform.DoesNotExist:
        logger.error(f"✗ Platform {platform_id} not found")
    except Exception as e:
        logger.error(f"✗ Error processing platform fetch: {e}", exc_info=True)


class Command(BaseCommand):
    help = "Run the Kafka consumer for platform data fetching"

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("🚀 Starting Platform Fetch Consumer..."))
        
        try:
            consumer = KafkaConsumer(
                settings.KAFKA_PLATFORM_FETCH_TOPIC,
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                value_deserializer=lambda x: json.loads(x.decode("utf-8")),
                group_id="platform-fetch-group",
                auto_offset_reset="latest",
            )
            
            self.stdout.write(
                self.style.SUCCESS(
                    f"✓ Connected to Kafka on {settings.KAFKA_BOOTSTRAP_SERVERS}"
                )
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"✓ Listening to topic: {settings.KAFKA_PLATFORM_FETCH_TOPIC}"
                )
            )
            self.stdout.write(self.style.SUCCESS("Waiting for messages...\n"))
            
            for msg in consumer:
                data = msg.value
                logger.info(f"Message received: {data}")
                process_platform_fetch(data)
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"✗ Failed to start consumer: {e}")
            )
