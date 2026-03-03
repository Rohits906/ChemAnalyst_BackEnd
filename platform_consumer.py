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

def fetch_youtube_channel_data(channel_id, platform_obj):
    """Fetch YouTube channel stats and recent videos"""
    if not youtube:
        logger.error("YouTube API not initialized")
        return False
    
    try:
        # Fetch channel stats
        channel_response = youtube.channels().list(
            part="statistics,snippet",
            forUsername=channel_id,  # Try as username first
        ).execute()
        
        # If no results, try as channel ID
        if not channel_response.get("items"):
            channel_response = youtube.channels().list(
                part="statistics,snippet",
                id=channel_id,  # Try as channel ID
            ).execute()
        
        if not channel_response.get("items"):
            logger.warning(f"No YouTube channel found for {channel_id}")
            return False
        
        channel_data = channel_response["items"][0]
        stats = channel_data.get("statistics", {})
        snippet = channel_data.get("snippet", {})
        actual_channel_id = channel_data["id"]
        
        # Update platform with actual channel ID and name
        platform_obj.channel_name = snippet.get("title", platform_obj.channel_id)
        platform_obj.profile_picture = snippet.get("thumbnails", {}).get("default", {}).get("url", "")
        platform_obj.metadata = {
            "description": snippet.get("description", ""),
            "actual_channel_id": actual_channel_id,
        }
        platform_obj.save()
        
        # Create or update channel stats
        channel_stats, created = ChannelStats.objects.get_or_create(
            platform=platform_obj,
            period_start=timezone.now().replace(hour=0, minute=0, second=0, microsecond=0),
            period_end=timezone.now() + timedelta(days=1),
        )
        
        channel_stats.subscribers = int(stats.get("subscriberCount", 0))
        channel_stats.views = int(stats.get("viewCount", 0))
        channel_stats.posts_count = int(stats.get("videoCount", 0))
        channel_stats.followers = int(stats.get("subscriberCount", 0))
        channel_stats.collected_at = timezone.now()
        channel_stats.save()
        
        logger.info(f"Fetched YouTube stats for {channel_id}: {channel_stats.subscribers} subscribers")
        
        # Fetch recent videos
        search_response = youtube.search().list(
            part="snippet",
            channelId=actual_channel_id,
            order="date",
            maxResults=20,
            type="video",
        ).execute()
        
        video_ids = [item["id"]["videoId"] for item in search_response.get("items", [])]
        
        if video_ids:
            # Fetch video statistics
            videos_response = youtube.videos().list(
                part="statistics,snippet",
                id=",".join(video_ids),
            ).execute()
            
            for video in videos_response.get("items", []):
                video_id = video["id"]
                snippet = video.get("snippet", {})
                stats = video.get("statistics", {})
                
                # Create or update post
                post, created = ChannelPost.objects.get_or_create(
                    platform=platform_obj,
                    platform_post_id=video_id,
                    defaults={
                        "title": snippet.get("title", ""),
                        "content": snippet.get("description", ""),
                        "post_url": f"https://youtube.com/watch?v={video_id}",
                        "media_type": "video",
                        "published_at": datetime.fromisoformat(
                            snippet.get("publishedAt", "").replace("Z", "+00:00")
                        ),
                    }
                )
                
                post.likes = int(stats.get("likeCount", 0))
                post.comments = int(stats.get("commentCount", 0))
                post.views = int(stats.get("viewCount", 0))
                post.shares = 0  # YouTube API doesn't expose shares
                post.collected_at = timezone.now()
                post.save()
            
            logger.info(f"Fetched {len(video_ids)} videos for {channel_id}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error fetching YouTube data for {channel_id}: {e}")
        return False


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
            success = fetch_youtube_channel_data(platform.channel_id, platform)
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
