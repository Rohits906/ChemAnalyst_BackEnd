import logging
from django.utils import timezone
from .models import ChannelStats, ChannelPost
from .platform_services import PlatformServiceFactory
from .youtube_service import fetch_youtube_channel_data

logger = logging.getLogger(__name__)

def fetch_platform_data(platform):
    """
    Fetch platform data using appropriate service based on platform type.
    Creates ChannelStats and ChannelPost records.
    Returns: (success: bool, message: str)
    """
    try:
        # For YouTube, continue using existing fetch function for backward compatibility
        if platform.name == "youtube":
            result = fetch_youtube_channel_data(platform)
            return bool(result), "YouTube data fetched successfully"
        
        # Use PlatformServiceFactory for other platforms
        service = PlatformServiceFactory.get_service(platform)
        if not service:
            return False, f"No service implementation for platform: {platform.name}"
        
        # Fetch channel info
        channel_info = service.fetch_channel_info()
        if not channel_info:
            return False, "Failed to fetch channel information"
        
        # Update platform with channel information
        platform.channel_name = channel_info.get("channel_name", platform.channel_id)
        platform.profile_picture = channel_info.get("profile_picture", "")
        platform.metadata = channel_info
        platform.save()
        
        # Create or update ChannelStats
        stats, created = ChannelStats.objects.update_or_create(
            platform=platform,
            defaults={
                "subscribers": channel_info.get("followers", 0),
                "views": channel_info.get("total_views", 0),
                "posts_count": channel_info.get("posts_count", 0),
                "engagement_rate": 0.0,
                "last_updated": timezone.now(),
                "metadata": channel_info
            }
        )
        
        # Fetch and create posts
        posts_data = service.fetch_posts(limit=15)
        sentiment_posts = []
        if posts_data:
            for post_data in posts_data:
                post_obj, created = ChannelPost.objects.update_or_create(
                    platform=platform,
                    platform_post_id=post_data.get("platform_post_id"),
                    defaults={
                        "title": post_data.get("title", ""),
                        "content": post_data.get("content", ""),
                        "post_url": post_data.get("post_url", ""),
                        "media_urls": post_data.get("media_urls", []),
                        "media_type": post_data.get("media_type", ""),
                        "likes": post_data.get("likes", 0),
                        "comments": post_data.get("comments", 0),
                        "shares": post_data.get("shares", 0),
                        "views": post_data.get("views", 0),
                        "published_at": post_data.get("published_at"),
                        "metadata": {
                            "engagement": post_data.get("likes", 0) + post_data.get("comments", 0),
                            "reach": post_data.get("views", 0)
                        }
                    }
                )
                # Prepare for sentiment analysis if newly created or no sentiment
                if created or not post_obj.sentiment_label:
                    sentiment_posts.append({
                        "id": str(post_obj.id),
                        "post_id": post_obj.platform_post_id,
                        "post_title": post_obj.title,
                        "post_text": post_obj.content,
                        "post_url": post_obj.post_url,
                        "platform": platform.name,
                        "author": platform.channel_name,
                        "published_at": post_obj.published_at.isoformat() if hasattr(post_obj.published_at, 'isoformat') else str(post_obj.published_at),
                    })
        
        # Queue for sentiment analysis
        if sentiment_posts:
            try:
                from sentiment.producers import add_to_sentiment_quene
                add_to_sentiment_quene(sentiment_posts, keyword=platform.channel_name)
            except Exception as qex:
                logger.warning(f"Failed to queue sentiment analysis: {qex}")
        
        return True, f"Platform data fetched successfully from {platform.name}"
        
    except Exception as e:
        logger.error(f"Error fetching data for {platform.name} - {platform.channel_id}: {str(e)}", exc_info=True)
        return False, f"Data fetch failed: {str(e)}"
