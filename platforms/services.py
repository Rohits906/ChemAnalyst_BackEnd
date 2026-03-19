import logging
import requests
from django.utils import timezone
from .models import ChannelStats, ChannelPost
from .platform_services import PlatformServiceFactory
from .youtube_service import fetch_youtube_channel_data
from .meta_services import FacebookService, InstagramService

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
        
        # For Facebook and Instagram, use the comprehensive meta_services
        if platform.name in ["facebook", "instagram"]:
            from .models import UserSocialAccount
            
            # Get the user's connected account for the freshest token available
            social_account = UserSocialAccount.objects.filter(
                user=platform.user,
                platform=platform.name,
                is_token_valid=True
            ).order_by('-last_synced').first() # Get most recently used/synced one

            if social_account:
                # Update platform metadata with token for consistency
                if not platform.metadata:
                    platform.metadata = {}
                
                token_key = 'page_access_token' if platform.name == 'facebook' else 'access_token'
                platform.metadata[token_key] = social_account.access_token
                platform.save(update_fields=['metadata'])
            
            if platform.name == "facebook":
                service = FacebookService(platform)
                return _fetch_meta_data(platform, service, "Facebook")
            else:
                service = InstagramService(platform)
                return _fetch_meta_data(platform, service, "Instagram")
        
        # Use PlatformServiceFactory for other platforms (Twitter, LinkedIn)
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


def _is_token_error(exc):
    """Check if a requests exception is a Meta OAuth token error (code 190)."""
    try:
        err = exc.response.json().get("error", {})
        return err.get("code") == 190
    except Exception:
        return False


def _fetch_meta_data(platform, service, platform_type):
    """
    Fetch data from Meta services (Facebook/Instagram) using the comprehensive meta_services.
    Returns: (success: bool, message: str)
    """
    try:
        # Fetch channel info using the comprehensive Meta service
        channel_info = service.fetch_channel_info()
        if not channel_info:
            return False, f"Failed to fetch {platform_type} channel information"
        
        # Update platform with channel information
        platform.channel_name = channel_info.get("channel_name", platform.channel_id)
        platform.profile_picture = channel_info.get("profile_picture", "")
        
        # Merge metadata
        existing_metadata = platform.metadata or {}
        existing_metadata.update({
            "description": channel_info.get("description", ""),
            "about": channel_info.get("about", ""),
            "category": channel_info.get("category", ""),
            "total_reach": channel_info.get("total_reach", 0),
            "total_engagement": channel_info.get("total_engagement", 0),
            "verified": channel_info.get("verified", False),
            "cover_photo": channel_info.get("cover_photo", ""),
        })
        platform.metadata = existing_metadata
        platform.save()
        
        # Create or update ChannelStats
        stats, created = ChannelStats.objects.update_or_create(
            platform=platform,
            defaults={
                "followers": channel_info.get("followers", 0),
                "posts_count": channel_info.get("posts_count", 0),
                "total_likes": channel_info.get("total_likes", 0),
                "total_comments": channel_info.get("total_comments", 0),
                "impressions": channel_info.get("total_reach", 0),
                "engagement_rate": channel_info.get("engagement_rate", 0.0),
                "period_start": timezone.now().replace(hour=0, minute=0, second=0, microsecond=0),
                "period_end": timezone.now() + timezone.timedelta(days=1),
                "collected_at": timezone.now(),
                "raw_data": channel_info
            }
        )
        
        # Fetch posts
        posts_data = service.fetch_posts(limit=25)
        sentiment_posts = []
        
        if posts_data:
            for post_data in posts_data:
                # Parse published_at datetime
                published_at = post_data.get("published_at")
                if isinstance(published_at, str):
                    try:
                        from datetime import datetime
                        published_at = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                    except:
                        published_at = timezone.now()
                
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
                        "views": post_data.get("views", post_data.get("impressions", 0)),
                        "published_at": published_at,
                        "raw_data": post_data.get("metadata", {})
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
        
        logger.info(f"Successfully fetched {platform_type} data: {len(posts_data)} posts, {channel_info.get('followers', 0)} followers")
        return True, f"{platform_type} data fetched successfully"
        
    except requests.exceptions.RequestException as e:
        if _is_token_error(e):
            # The OAuth token is no longer valid – mark the social account as invalid
            # so the user is prompted to reconnect in the UI.
            try:
                from .models import UserSocialAccount
                UserSocialAccount.objects.filter(
                    user=platform.user,
                    platform=platform.name,
                    is_token_valid=True
                ).update(is_token_valid=False)
                logger.warning(
                    f"{platform_type} token invalidated for platform {platform.channel_id}. "
                    "Marked social account as invalid."
                )
            except Exception as mark_err:
                logger.error(f"Failed to mark social account as invalid: {mark_err}")
            return False, f"{platform_type} access token has expired or been revoked. Please reconnect your {platform_type} account."
        logger.error(f"Error fetching {platform_type} data for {platform.channel_id}: {str(e)}", exc_info=True)
        return False, f"Data fetch failed: {str(e)}"
    except Exception as e:
        logger.error(f"Error fetching {platform_type} data for {platform.channel_id}: {str(e)}", exc_info=True)
        return False, f"Data fetch failed: {str(e)}"
