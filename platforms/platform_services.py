import requests
from django.conf import settings
from datetime import datetime, timedelta
import time
from typing import Dict, List, Optional

class BasePlatformService:
    """Base class for platform API integrations"""
    
    def __init__(self, platform):
        self.platform = platform
        self.access_token = None
        
    def fetch_channel_info(self) -> Dict:
        """Fetch basic channel information"""
        raise NotImplementedError
        
    def fetch_posts(self, limit=50) -> List[Dict]:
        """Fetch recent posts"""
        raise NotImplementedError
        
    def fetch_stats(self, period_start=None, period_end=None) -> Dict:
        """Fetch channel statistics"""
        raise NotImplementedError


class YouTubeService(BasePlatformService):
    def __init__(self, platform):
        super().__init__(platform)
        self.api_key = settings.YOUTUBE_API_KEY
        self.base_url = "https://www.googleapis.com/youtube/v3"
        
    def _get_channel_id_from_url(self, url):
        """Extract channel ID from various YouTube URL formats"""
        if "youtube.com/channel/" in url:
            return url.split("youtube.com/channel/")[-1].split("/")[0]
        elif "youtube.com/c/" in url or "youtube.com/user/" in url:
            # Need to resolve custom URLs
            username = url.split("/")[-1]
            search_url = f"{self.base_url}/search"
            params = {
                "part": "snippet",
                "type": "channel",
                "q": username,
                "key": self.api_key,
            }
            response = requests.get(search_url, params=params)
            data = response.json()
            if data.get("items"):
                return data["items"][0]["snippet"]["channelId"]
        return None
        
    def fetch_channel_info(self):
        channel_id = self.platform.channel_id
        url = f"{self.base_url}/channels"
        params = {
            "part": "snippet,statistics",
            "id": channel_id,
            "key": self.api_key,
        }
        
        response = requests.get(url, params=params)
        data = response.json()
        
        if not data.get("items"):
            return None
            
        item = data["items"][0]
        return {
            "channel_name": item["snippet"]["title"],
            "profile_picture": item["snippet"]["thumbnails"]["default"]["url"],
            "subscribers": int(item["statistics"].get("subscriberCount", 0)),
            "views": int(item["statistics"].get("viewCount", 0)),
            "videos": int(item["statistics"].get("videoCount", 0)),
        }
        
    def fetch_posts(self, limit=50):
        channel_id = self.platform.channel_id
        url = f"{self.base_url}/search"
        params = {
            "part": "snippet",
            "channelId": channel_id,
            "type": "video",
            "order": "date",
            "maxResults": limit,
            "key": self.api_key,
        }
        
        response = requests.get(url, params=params)
        data = response.json()
        
        posts = []
        for item in data.get("items", []):
            video_id = item["id"]["videoId"]
            # Fetch video statistics
            stats_url = f"{self.base_url}/videos"
            stats_params = {
                "part": "statistics",
                "id": video_id,
                "key": self.api_key,
            }
            stats_response = requests.get(stats_url, params=stats_params)
            stats_data = stats_response.json()
            
            statistics = stats_data["items"][0]["statistics"] if stats_data.get("items") else {}
            
            posts.append({
                "platform_post_id": video_id,
                "title": item["snippet"]["title"],
                "content": item["snippet"]["description"],
                "post_url": f"https://www.youtube.com/watch?v={video_id}",
                "media_urls": [item["snippet"]["thumbnails"]["high"]["url"]],
                "media_type": "video",
                "likes": int(statistics.get("likeCount", 0)),
                "comments": int(statistics.get("commentCount", 0)),
                "views": int(statistics.get("viewCount", 0)),
                "published_at": item["snippet"]["publishedAt"],
            })
            
        return posts


class TwitterService(BasePlatformService):
    def __init__(self, platform):
        super().__init__(platform)
        self.bearer_token = settings.TWITTER_BEARER_TOKEN
        self.base_url = "https://api.twitter.com/2"
        
    def _get_headers(self):
        return {"Authorization": f"Bearer {self.bearer_token}"}
        
    def fetch_channel_info(self):
        # Twitter API v2 for user lookup
        url = f"{self.base_url}/users/by/username/{self.platform.channel_id}"
        params = {
            "user.fields": "public_metrics,description,profile_image_url,created_at"
        }
        
        response = requests.get(url, headers=self._get_headers(), params=params)
        data = response.json()
        
        if not data.get("data"):
            return None
            
        user = data["data"]
        metrics = user.get("public_metrics", {})
        
        return {
            "channel_name": user["name"],
            "profile_picture": user.get("profile_image_url", ""),
            "followers": metrics.get("followers_count", 0),
            "following": metrics.get("following_count", 0),
            "posts_count": metrics.get("tweet_count", 0),
            "created_at": user.get("created_at"),
        }
        
    def fetch_posts(self, limit=50):
        # First get user ID
        user_url = f"{self.base_url}/users/by/username/{self.platform.channel_id}"
        user_response = requests.get(user_url, headers=self._get_headers())
        user_data = user_response.json()
        
        if not user_data.get("data"):
            return []
            
        user_id = user_data["data"]["id"]
        
        # Fetch tweets
        tweets_url = f"{self.base_url}/users/{user_id}/tweets"
        params = {
            "max_results": min(limit, 100),
            "tweet.fields": "created_at,public_metrics,attachments",
            "media.fields": "url",
            "expansions": "attachments.media_keys",
        }
        
        response = requests.get(tweets_url, headers=self._get_headers(), params=params)
        data = response.json()
        
        posts = []
        media_map = {}
        
        if data.get("includes") and data["includes"].get("media"):
            for media in data["includes"]["media"]:
                media_map[media["media_key"]] = media.get("url", "")
        
        for tweet in data.get("data", []):
            metrics = tweet.get("public_metrics", {})
            media_urls = []
            
            if tweet.get("attachments") and tweet["attachments"].get("media_keys"):
                for key in tweet["attachments"]["media_keys"]:
                    if key in media_map:
                        media_urls.append(media_map[key])
            
            posts.append({
                "platform_post_id": tweet["id"],
                "title": tweet["text"][:100] + ("..." if len(tweet["text"]) > 100 else ""),
                "content": tweet["text"],
                "post_url": f"https://twitter.com/{self.platform.channel_id}/status/{tweet['id']}",
                "media_urls": media_urls,
                "media_type": "image" if media_urls else "text",
                "likes": metrics.get("like_count", 0),
                "comments": metrics.get("reply_count", 0),
                "shares": metrics.get("retweet_count", 0),
                "published_at": tweet["created_at"],
            })
            
        return posts


class InstagramService(BasePlatformService):
    def __init__(self, platform):
        super().__init__(platform)
        self.access_token = settings.INSTAGRAM_ACCESS_TOKEN
        self.base_url = "https://graph.facebook.com/v22.0"
        
    def fetch_channel_info(self):
        # First get business account ID
        accounts_url = f"{self.base_url}/me/accounts"
        params = {"access_token": self.access_token}
        
        response = requests.get(accounts_url, params=params)
        data = response.json()
        
        # Find Instagram Business Account
        instagram_url = f"{self.base_url}/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}"
        ig_params = {
            "fields": "username,profile_picture_url,followers_count,media_count",
            "access_token": self.access_token,
        }
        
        ig_response = requests.get(instagram_url, params=ig_params)
        ig_data = ig_response.json()
        
        return {
            "channel_name": ig_data.get("username", ""),
            "profile_picture": ig_data.get("profile_picture_url", ""),
            "followers": ig_data.get("followers_count", 0),
            "posts_count": ig_data.get("media_count", 0),
        }
        
    def fetch_posts(self, limit=50):
        media_url = f"{self.base_url}/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media"
        params = {
            "fields": "id,caption,media_type,media_url,permalink,timestamp,like_count,comments_count",
            "limit": limit,
            "access_token": self.access_token,
        }
        
        response = requests.get(media_url, params=params)
        data = response.json()
        
        posts = []
        for item in data.get("data", []):
            posts.append({
                "platform_post_id": item["id"],
                "title": (item.get("caption", "")[:100] + "...") if item.get("caption") else "Instagram Post",
                "content": item.get("caption", ""),
                "post_url": item.get("permalink", ""),
                "media_urls": [item.get("media_url", "")] if item.get("media_url") else [],
                "media_type": item.get("media_type", "").lower(),
                "likes": item.get("like_count", 0),
                "comments": item.get("comments_count", 0),
                "published_at": item.get("timestamp"),
            })
            
        return posts


class PlatformServiceFactory:
    """Factory to create appropriate platform service"""
    
    @staticmethod
    def get_service(platform):
        services = {
            "youtube": YouTubeService,
            "twitter": TwitterService,
            "instagram": InstagramService,
            # Add other platforms as needed
        }
        
        service_class = services.get(platform.name)
        if service_class:
            return service_class(platform)
        return None