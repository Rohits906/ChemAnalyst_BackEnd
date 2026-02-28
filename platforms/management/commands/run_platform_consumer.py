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

# Initialize YouTube API
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY") or settings.YOUTUBE_API_KEY


def fetch_youtube_channel_data(channel_id, platform_obj):
    """Fetch YouTube channel stats and recent videos"""
    if not YOUTUBE_API_KEY:
        logger.error("YouTube API key not configured")
        return False
    
    try:
        youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
        
        # Fetch channel stats - try by username first, then by channel ID
        channel_response = youtube.channels().list(
            part="statistics,snippet",
            forUsername=channel_id,
        ).execute()
        
        # If no results, try as channel ID
        if not channel_response.get("items"):
            channel_response = youtube.channels().list(
                part="statistics,snippet",
                id=channel_id,
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
        
        logger.info(f"✓ Fetched YouTube stats for {channel_id}: {channel_stats.subscribers} subscribers")
        
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
                
                # Parse published date
                pub_date_str = snippet.get("publishedAt", "")
                try:
                    published_at = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
                except:
                    published_at = timezone.now()
                
                # Create or update post
                post, created = ChannelPost.objects.get_or_create(
                    platform=platform_obj,
                    platform_post_id=video_id,
                    defaults={
                        "title": snippet.get("title", ""),
                        "content": snippet.get("description", ""),
                        "post_url": f"https://youtube.com/watch?v={video_id}",
                        "media_type": "video",
                        "published_at": published_at,
                    }
                )
                
                post.likes = int(stats.get("likeCount", 0))
                post.comments = int(stats.get("commentCount", 0))
                post.views = int(stats.get("viewCount", 0))
                post.shares = 0  # YouTube API doesn't expose shares
                post.collected_at = timezone.now()
                post.save()
            
            logger.info(f"✓ Fetched {len(video_ids)} videos for {channel_id}")
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Error fetching YouTube data for {channel_id}: {e}", exc_info=True)
        return False


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
        
        # Dispatch to appropriate platform handler
        success = False
        if platform.name == "youtube":
            success = fetch_youtube_channel_data(platform.channel_id, platform)
        elif platform.name == "instagram":
            logger.info(f"⏳ Instagram fetching not yet implemented for {platform.channel_id}")
        elif platform.name == "twitter":
            logger.info(f"⏳ Twitter fetching not yet implemented for {platform.channel_id}")
        elif platform.name == "facebook":
            logger.info(f"⏳ Facebook fetching not yet implemented for {platform.channel_id}")
        elif platform.name == "linkedin":
            logger.info(f"⏳ LinkedIn fetching not yet implemented for {platform.channel_id}")
        
        # Update fetch task
        fetch_task.status = "completed" if success else "failed"
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
