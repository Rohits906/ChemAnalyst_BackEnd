import os
import logging
from datetime import datetime, timedelta
from django.utils import timezone
from django.conf import settings
from googleapiclient.discovery import build

from .models import Platform, ChannelStats, ChannelPost

logger = logging.getLogger(__name__)

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY") or settings.YOUTUBE_API_KEY


def fetch_youtube_channel_data(platform_obj):
    """
    Fetch YouTube channel stats and recent videos synchronously.
    Called immediately after platform creation.
    """
    
    if not YOUTUBE_API_KEY:
        logger.error("❌ YouTube API key not configured in settings or .env")
        return False
    
    try:
        channel_id = platform_obj.channel_id.strip()
        
        # Remove @ symbol if present (YouTube doesn't accept it in API calls)
        if channel_id.startswith("@"):
            channel_id = channel_id[1:]
            logger.info(f"Stripped @ symbol from channel_id: {channel_id}")
        
        logger.info(f"Building YouTube client...")
        youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
        
        logger.info(f"Attempting YouTube API call for channel_id: {channel_id}")
        
        channel_response = None
        
        # Try different lookup methods
        lookup_methods = [
            ("forHandle", {"part": "statistics,snippet", "forHandle": f"@{channel_id}"}),
            ("forUsername", {"part": "statistics,snippet", "forUsername": channel_id}),
            ("direct ID", {"part": "statistics,snippet", "id": channel_id}),
        ]
        
        for method_name, params in lookup_methods:
            logger.info(f"Trying {method_name} lookup with: {channel_id}")
            try:
                channel_response = youtube.channels().list(**params).execute()
                logger.info(f"Response: {channel_response}")
                if channel_response.get("items"):
                    logger.info(f"✓ Found channel using {method_name} lookup")
                    break
                else:
                    logger.info(f"No results from {method_name} lookup. Items: {channel_response.get('items', [])}")
            except Exception as e:
                logger.debug(f"Error with {method_name}: {e}")
                import traceback
                logger.debug(traceback.format_exc())
        
        if not channel_response or not channel_response.get("items"):
            # Try search as a last resort
            logger.info(f"No direct lookup results. Trying search...")
            try:
                search_response = youtube.search().list(
                    q=channel_id,
                    part="snippet",
                    type="channel",
                    maxResults=1
                ).execute()
                
                if search_response.get("items"):
                    logger.info(f"✓ Found channel via search")
                    channel_data = search_response["items"][0]
                    actual_channel_id = channel_data["id"]["channelId"]
                    logger.info(f"  Channel ID from search: {actual_channel_id}")
                    
                    # Now fetch full channel data using the ID we found
                    channel_response = youtube.channels().list(
                        part="statistics,snippet",
                        id=actual_channel_id
                    ).execute()
                    logger.info(f"✓ Fetched full channel data")
                else:
                    logger.warning(f"❌ No results from search for: {channel_id}")
                    return False
            except Exception as e:
                logger.error(f"❌ Search failed: {e}", exc_info=True)
                return False
        
        if not channel_response or not channel_response.get("items"):
            logger.warning(f"❌ No YouTube channel found for: {channel_id}")
            return False
        
        channel_data = channel_response["items"][0]
        stats = channel_data.get("statistics", {})
        snippet = channel_data.get("snippet", {})
        actual_channel_id = channel_data["id"]
        
        logger.info(f"✓ Found YouTube channel: {actual_channel_id}")
        
        # Update platform with actual data
        platform_obj.channel_name = snippet.get("title", platform_obj.channel_id)
        platform_obj.profile_picture = snippet.get("thumbnails", {}).get("default", {}).get("url", "")
        platform_obj.metadata = {
            "description": snippet.get("description", ""),
            "actual_channel_id": actual_channel_id,
            "custom_url": snippet.get("customUrl", ""),
            "published_at": snippet.get("publishedAt", ""),
        }
        platform_obj.save()
        
        logger.info(f"✓ Updated platform info: {platform_obj.channel_name}")
        
        # Create channel stats
        now = timezone.now()
        try:
            channel_stats = ChannelStats.objects.create(
                platform=platform_obj,
                period_start=now.replace(hour=0, minute=0, second=0, microsecond=0),
                period_end=now + timedelta(days=1),
                subscribers=int(stats.get("subscriberCount", 0)),
                views=int(stats.get("viewCount", 0)),
                posts_count=int(stats.get("videoCount", 0)),
                followers=int(stats.get("subscriberCount", 0)),
                collected_at=now,
            )
            logger.info(f"✓ Created ChannelStats (ID: {channel_stats.id})")
        except Exception as e:
            logger.error(f"❌ Failed to create ChannelStats: {e}", exc_info=True)
            return False
        
        # Fetch recent videos
        logger.info("Fetching recent videos...")
        try:
            search_response = youtube.search().list(
                part="snippet",
                channelId=actual_channel_id,
                order="date",
                maxResults=15,
                type="video",
            ).execute()
            
            video_ids = [item["id"]["videoId"] for item in search_response.get("items", [])]
            logger.info(f"✓ Found {len(video_ids)} videos to process")
            
            if video_ids:
                logger.info("Fetching detailed stats for videos...")
                # Fetch detailed video stats
                videos_response = youtube.videos().list(
                    part="statistics,snippet",
                    id=",".join(video_ids),
                ).execute()
                
                logger.info(f"Got stats for {len(videos_response.get('items', []))} videos")
                
                videos_created = 0
                for video in videos_response.get("items", []):
                    try:
                        video_id = video["id"]
                        snippet = video.get("snippet", {})
                        video_stats = video.get("statistics", {})
                        
                        # Parse published date
                        pub_date_str = snippet.get("publishedAt", "")
                        try:
                            published_at = datetime.fromisoformat(
                                pub_date_str.replace("Z", "+00:00")
                            )
                        except:
                            published_at = timezone.now()
                        
                        # Create post
                        post = ChannelPost.objects.create(
                            platform=platform_obj,
                            platform_post_id=video_id,
                            title=snippet.get("title", ""),
                            content=snippet.get("description", ""),
                            post_url=f"https://youtube.com/watch?v={video_id}",
                            media_type="video",
                            likes=int(video_stats.get("likeCount", 0)),
                            comments=int(video_stats.get("commentCount", 0)),
                            views=int(video_stats.get("viewCount", 0)),
                            shares=0,
                            published_at=published_at,
                            collected_at=timezone.now(),
                        )
                        videos_created += 1
                    except Exception as e:
                        logger.warning(f"Failed to create post for video {video_id}: {e}")
                        continue
                
                logger.info(f"✓ Created {videos_created} posts from {len(video_ids)} videos")
            else:
                logger.warning(f"⚠ No videos found for channel {actual_channel_id}")
        
        except Exception as e:
            logger.error(f"❌ Failed to fetch videos: {e}", exc_info=True)
            # Don't fail the entire operation if video fetch fails
        
        logger.info(f"=== ✓ YouTube fetch completed successfully for {platform_obj.channel_id} ===")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error fetching YouTube data: {str(e)}", exc_info=True)
        return False
