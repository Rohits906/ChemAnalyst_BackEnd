import os
import django
import json
from kafka import KafkaConsumer
from django.utils import timezone
from datetime import datetime, timedelta
import logging

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.conf import settings
from platforms.models import Platform, ChannelStats, ChannelPost, PlatformFetchTask
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize YouTube API
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY) if YOUTUBE_API_KEY else None

from platforms.youtube_service import fetch_youtube_channel_data

def fetch_instagram_data(account_id, platform_obj):
    """Placeholder for Instagram data fetching"""
    logger.info(f"Instagram fetching not yet implemented for {account_id}")
    return False


def fetch_twitter_data(username, platform_obj):
    """Placeholder for Twitter data fetching"""
    logger.info(f"Twitter fetching not yet implemented for {username}")
    return False


def fetch_facebook_data(page_id, platform_obj):
    """Placeholder for Facebook data fetching"""
    logger.info(f"Facebook fetching not yet implemented for {page_id}")
    return False


def fetch_linkedin_data(profile_id, platform_obj):
    """Placeholder for LinkedIn data fetching"""
    logger.info(f"LinkedIn fetching not yet implemented for {profile_id}")
    return False


def process_platform_fetch(message):
    """Process a platform fetch task from Kafka"""
    try:
        platform_id = message.get("platform_id")
        task_type = message.get("task_type", "update")
        
        platform = Platform.objects.get(id=platform_id)
        
        logger.info(f"Processing {task_type} for platform: {platform.channel_id} ({platform.name})")
        
        # Create fetch task record
        fetch_task = PlatformFetchTask.objects.create(
            platform=platform,
            user=platform.user,
            task_type=task_type,
            status="processing",
        )
        
        # Dispatch to appropriate platform handler
        success = False
        if platform.name == "youtube":
            success = fetch_youtube_channel_data(platform)
        elif platform.name == "instagram":
            success = fetch_instagram_data(platform.channel_id, platform)
        elif platform.name == "twitter":
            success = fetch_twitter_data(platform.channel_id, platform)
        elif platform.name == "facebook":
            success = fetch_facebook_data(platform.channel_id, platform)
        elif platform.name == "linkedin":
            success = fetch_linkedin_data(platform.channel_id, platform)
        
        # Update fetch task
        fetch_task.status = "completed" if success else "failed"
        fetch_task.completed_at = timezone.now()
        fetch_task.save()
        
        logger.info(f"Completed fetch for {platform.channel_id}: {fetch_task.status}")
        
    except Platform.DoesNotExist:
        logger.error(f"Platform {platform_id} not found")
    except Exception as e:
        logger.error(f"Error processing platform fetch: {e}", exc_info=True)


# Initialize Kafka consumer
try:
    platform_consumer = KafkaConsumer(
        settings.KAFKA_PLATFORM_FETCH_TOPIC,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        value_deserializer=lambda x: json.loads(x.decode("utf-8")),
        group_id="platform-fetch-group",
        auto_offset_reset="latest",
    )
    logger.info(f"Started platform consumer on topic: {settings.KAFKA_PLATFORM_FETCH_TOPIC}")
except Exception as e:
    logger.error(f"Failed to initialize Kafka consumer: {e}")
    platform_consumer = None

# Main consumer loop
if platform_consumer:
    for msg in platform_consumer:
        data = msg.value
        logger.info(f"Received message: {data}")
        process_platform_fetch(data)
