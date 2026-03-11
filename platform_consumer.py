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
from platforms.models import Platform, ChannelStats, ChannelPost, PlatformFetchTask, UserSocialAccount
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
    """Fetch Instagram data using meta_services and user's connected account token"""
    try:
        from platforms.meta_services import InstagramService
        
        # Step 1: Get the user's connected Instagram account (from OAuth)
        user_ig_account = UserSocialAccount.objects.filter(
            user=platform_obj.user,
            platform__in=['instagram', 'instagram_business'],
            is_token_valid=True
        ).first()
        
        if not user_ig_account:
            logger.error(f"No valid Instagram account token found for user {platform_obj.user}")
            return False
        
        # Step 2: Use the OAuth token for API calls
        access_token = user_ig_account.access_token
        
        logger.info(f"🔐 Using OAuth token for {platform_obj.user.username}")
        
        # Update Platform metadata with token for future use
        platform_obj.metadata['access_token'] = access_token
        platform_obj.metadata['token_source'] = 'oauth'
        platform_obj.save()
        
        # Step 3: Create service with the token
        service = InstagramService(platform_obj)
        # Override the service's token with our OAuth token
        service.access_token = access_token
        
        logger.info(f"📝 Fetching Instagram channel info for {account_id}")
        # Fetch channel info
        channel_info = service.fetch_channel_info()
        if channel_info:
            platform_obj.channel_name = channel_info.get('channel_name', platform_obj.channel_id)
            platform_obj.profile_picture = channel_info.get('profile_picture', '')
            platform_obj.save()
            
            logger.info(f"✅ Channel info fetched: {platform_obj.channel_name}")
            
            # Create stats
            stats = ChannelStats.objects.create(
                platform=platform_obj,
                followers=channel_info.get('followers', 0),
                posts_count=channel_info.get('posts_count', 0),
                period_start=timezone.now().replace(hour=0, minute=0, second=0, microsecond=0),
                period_end=timezone.now() + timedelta(days=1),
                collected_at=timezone.now(),
            )
            logger.info(f"✅ Stats created: {stats.followers} followers, {stats.posts_count} posts")
        
        # Fetch posts
        logger.info(f"📝 Fetching Instagram posts for {account_id}")
        posts = service.fetch_posts(limit=15)
        posts_created = 0
        for post_data in posts:
            ChannelPost.objects.update_or_create(
                platform=platform_obj,
                platform_post_id=post_data.get('platform_post_id'),
                defaults={
                    'title': post_data.get('title', ''),
                    'content': post_data.get('content', ''),
                    'post_url': post_data.get('post_url', ''),
                    'media_urls': post_data.get('media_urls', []),
                    'media_type': post_data.get('media_type', ''),
                    'likes': post_data.get('likes', 0),
                    'comments': post_data.get('comments', 0),
                    'shares': post_data.get('shares', 0),
                    'views': post_data.get('views', 0),
                    'published_at': post_data.get('published_at'),
                    'collected_at': timezone.now(),
                }
            )
            posts_created += 1
        
        logger.info(f"✅ Instagram data fetched successfully for {account_id} - {posts_created} posts")
        return True
    except Exception as e:
        logger.error(f"❌ Error fetching Instagram data: {e}", exc_info=True)
        return False


def fetch_facebook_data(page_id, platform_obj):
    """Fetch Facebook data using meta_services and user's connected account token"""
    try:
        from platforms.meta_services import FacebookService
        
        # Step 1: Get the user's connected Facebook account (from OAuth)
        user_fb_account = UserSocialAccount.objects.filter(
            user=platform_obj.user,
            platform__in=['facebook', 'facebook_page'],
            is_token_valid=True
        ).first()
        
        if not user_fb_account:
            logger.error(f"No valid Facebook account token found for user {platform_obj.user}")
            return False
        
        # Step 2: Use the OAuth token for API calls
        access_token = user_fb_account.access_token
        
        logger.info(f"🔐 Using OAuth token for {platform_obj.user.username}")
        print(f"🔐 Using OAuth token for {platform_obj.user.username} - Token first 50 chars: {access_token[:50]}...")
        
        # Update Platform metadata with token for future use
        platform_obj.metadata['page_access_token'] = access_token
        platform_obj.metadata['token_source'] = 'oauth'
        platform_obj.save()
        
        # Step 3: Create service with the token
        service = FacebookService(platform_obj)
        # Override the service's token with our OAuth token
        service.access_token = access_token
        
        logger.info(f"📝 Fetching Facebook channel info for {page_id}")
        # Fetch channel info
        channel_info = service.fetch_channel_info()
        if channel_info:
            platform_obj.channel_name = channel_info.get('channel_name', platform_obj.channel_id)
            platform_obj.profile_picture = channel_info.get('profile_picture', '')
            platform_obj.save()
            
            logger.info(f"✅ Channel info fetched: {platform_obj.channel_name}")
            
            # Create stats
            stats = ChannelStats.objects.create(
                platform=platform_obj,
                followers=channel_info.get('followers', 0),
                posts_count=channel_info.get('posts_count', 0),
                impressions=channel_info.get('total_reach', 0),
                period_start=timezone.now().replace(hour=0, minute=0, second=0, microsecond=0),
                period_end=timezone.now() + timedelta(days=1),
                collected_at=timezone.now(),
            )
            logger.info(f"✅ Stats created: {stats.followers} followers, {stats.posts_count} posts")
        
        # Fetch posts
        logger.info(f"📝 Fetching Facebook posts for {page_id}")
        posts = service.fetch_posts(limit=15)
        posts_created = 0
        for post_data in posts:
            ChannelPost.objects.update_or_create(
                platform=platform_obj,
                platform_post_id=post_data.get('platform_post_id'),
                defaults={
                    'title': post_data.get('title', ''),
                    'content': post_data.get('content', ''),
                    'post_url': post_data.get('post_url', ''),
                    'media_urls': post_data.get('media_urls', []),
                    'media_type': post_data.get('media_type', ''),
                    'likes': post_data.get('likes', 0),
                    'comments': post_data.get('comments', 0),
                    'shares': post_data.get('shares', 0),
                    'views': post_data.get('views', 0),
                    'published_at': post_data.get('published_at'),
                    'collected_at': timezone.now(),
                }
            )
            posts_created += 1
        
        logger.info(f"✅ Facebook data fetched successfully for {page_id} - {posts_created} posts")
        return True
    except Exception as e:
        logger.error(f"❌ Error fetching Facebook data: {e}", exc_info=True)
        return False


def fetch_linkedin_data(profile_id, platform_obj):
    """Placeholder for LinkedIn data fetching"""
    logger.info(f"LinkedIn fetching not yet implemented for {profile_id}")
    return False


def fetch_twitter_data(username, platform_obj):
    """Placeholder for Twitter data fetching"""
    logger.info(f"Twitter fetching not yet implemented for {username}")
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
