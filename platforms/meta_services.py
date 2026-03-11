import requests
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from django.utils import timezone
from django.conf import settings

logger = logging.getLogger(__name__)

class MetaBaseService:
    """Base service for Meta (Facebook/Instagram) API integration"""
    
    def __init__(self, platform=None, access_token=None):
        self.platform = platform
        self.access_token = access_token
        self.api_version = getattr(settings, 'FACEBOOK_API_VERSION', 'v19.0')
        self.base_url = f"https://graph.facebook.com/{self.api_version}"
        
        # If platform exists, try to get token from metadata
        if platform and not access_token:
            self.access_token = platform.metadata.get('page_access_token') or \
                               platform.metadata.get('access_token')
            print(f"DEBUG MetaBaseService - Platform: {platform.channel_id}, has_token: {bool(self.access_token)}, metadata_keys: {list(platform.metadata.keys()) if platform.metadata else 'None'}")
    
    def _make_request(self, endpoint, params=None, method='GET'):
        """Make authenticated request to Meta API"""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        if params is None:
            params = {}
        
        # Add access token to params
        if self.access_token:
            params['access_token'] = self.access_token
        
        try:
            if method.upper() == 'GET':
                response = requests.get(url, params=params, timeout=30)
            elif method.upper() == 'POST':
                response = requests.post(url, data=params, timeout=30)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            # Check for token expiration
            if response.status_code == 401:
                response_data = response.json()
                if 'error' in response_data:
                    error = response_data['error']
                    if error.get('code') == 190 or 'token' in error.get('message', '').lower():
                        logger.warning("Access token expired, attempting refresh")
                        self._refresh_token()
                        # Retry the request with new token
                        params['access_token'] = self.access_token
                        response = requests.get(url, params=params, timeout=30)
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Meta API request failed: {e}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"Response: {e.response.text}")
            raise
    
    def _refresh_token(self):
        """Refresh long-lived token"""
        if not self.platform:
            logger.error("Cannot refresh token: No platform associated")
            return False
        
        try:
            # Get the refresh token from metadata
            refresh_token = self.platform.metadata.get('refresh_token')
            if not refresh_token:
                logger.error("No refresh token available")
                return False
            
            # Exchange refresh token for new access token
            params = {
                'grant_type': 'fb_exchange_token',
                'client_id': settings.FACEBOOK_APP_ID,
                'client_secret': settings.FACEBOOK_APP_SECRET,
                'fb_exchange_token': refresh_token
            }
            
            response = requests.get(
                f"{self.base_url}/oauth/access_token",
                params=params
            )
            response.raise_for_status()
            token_data = response.json()
            
            # Update tokens in platform metadata
            new_token = token_data.get('access_token')
            expires_in = token_data.get('expires_in', 5184000)  # Default 60 days
            
            if new_token:
                self.access_token = new_token
                self.platform.metadata['access_token'] = new_token
                self.platform.metadata['token_expires_at'] = (
                    timezone.now() + timedelta(seconds=expires_in)
                ).isoformat()
                self.platform.save(update_fields=['metadata'])
                logger.info(f"Successfully refreshed token for {self.platform.name}")
                return True
            
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
        
        return False


class FacebookService(MetaBaseService):
    """Facebook Page API integration"""
    
    def __init__(self, platform):
        super().__init__(platform)
        self.page_id = platform.channel_id
    
    def fetch_channel_info(self) -> Optional[Dict]:
        """Fetch Facebook page information"""
        try:
            fields = [
                'id', 'name', 'about', 'description', 'website',
                'picture', 'cover', 'category', 'fan_count',
                'followers_count', 'talking_about_count', 'verification_status',
                'engagement', 'unread_message_count', 'unread_notif_count'
            ]
            
            data = self._make_request(
                self.page_id,
                params={'fields': ','.join(fields)}
            )
            
            # Extract profile picture
            picture_url = ''
            if data.get('picture') and data['picture'].get('data'):
                picture_url = data['picture']['data'].get('url', '')
            
            # Get page insights for reach and engagement
            insights = self._fetch_page_insights()
            
            channel_info = {
                'channel_id': data.get('id'),
                'channel_name': data.get('name', ''),
                'profile_picture': picture_url,
                'about': data.get('about', ''),
                'description': data.get('description', ''),
                'category': data.get('category', ''),
                'followers': data.get('followers_count', data.get('fan_count', 0)),
                'talking_about': data.get('talking_about_count', 0),
                'posts_count': 0,  # Will be updated from posts fetch
                'total_reach': insights.get('page_impressions', 0),
                'total_engagement': insights.get('page_engaged_users', 0),
                'verified': data.get('verification_status', 'not_verified') == 'verified',
                'website': data.get('website', ''),
                'cover_photo': data.get('cover', {}).get('source', '') if data.get('cover') else ''
            }
            
            return channel_info
            
        except Exception as e:
            logger.error(f"Failed to fetch Facebook page info: {e}")
            return None
    
    def _fetch_page_insights(self, period='days_28'):
        """Fetch page insights for engagement metrics"""
        try:
            # Get insights for the last 28 days
            since = (timezone.now() - timedelta(days=28)).strftime('%Y-%m-%d')
            until = timezone.now().strftime('%Y-%m-%d')
            
            metrics = [
                'page_impressions',
                'page_impressions_unique',
                'page_engaged_users',
                'page_post_engagements',
                'page_actions_post_reactions_total'
            ]
            
            data = self._make_request(
                f"{self.page_id}/insights",
                params={
                    'metric': ','.join(metrics),
                    'period': period,
                    'since': since,
                    'until': until
                }
            )
            
            insights = {}
            if data.get('data'):
                for metric in data['data']:
                    name = metric['name']
                    values = metric.get('values', [])
                    if values:
                        # Get the latest value
                        insights[name] = values[-1].get('value', 0)
            
            return insights
            
        except Exception as e:
            logger.warning(f"Failed to fetch page insights: {e}")
            return {}
    
    def fetch_posts(self, limit=50) -> List[Dict]:
        """Fetch Facebook page posts"""
        try:
            fields = [
                'id', 'message', 'story', 'created_time', 'permalink_url',
                'full_picture', 'attachments{media,subattachments}',
                'likes.summary(true).limit(0)',
                'comments.summary(true).limit(0)',
                'shares',
                'reactions.type(LIKE).summary(total_count).limit(0) as reactions_like',
                'reactions.type(LOVE).summary(total_count).limit(0) as reactions_love',
                'reactions.type(HAHA).summary(total_count).limit(0) as reactions_haha',
                'reactions.type(WOW).summary(total_count).limit(0) as reactions_wow',
                'reactions.type(SAD).summary(total_count).limit(0) as reactions_sad',
                'reactions.type(ANGRY).summary(total_count).limit(0) as reactions_angry',
                'insights.metric(post_impressions,post_engaged_users)'
            ]
            
            data = self._make_request(
                f"{self.page_id}/posts",
                params={
                    'fields': ','.join(fields),
                    'limit': min(limit, 100)
                }
            )
            
            posts = []
            for item in data.get('data', []):
                post_data = self._parse_post(item)
                if post_data:
                    posts.append(post_data)
            
            return posts
            
        except Exception as e:
            logger.error(f"Failed to fetch Facebook posts: {e}")
            return []
    
    def _parse_post(self, post):
        """Parse Facebook post data"""
        try:
            # Extract media URLs
            media_urls = []
            media_type = 'text'
            
            if post.get('full_picture'):
                media_urls.append(post['full_picture'])
                media_type = 'image'
            
            if post.get('attachments'):
                attachments = post['attachments']['data']
                for attachment in attachments:
                    if attachment.get('media', {}).get('image', {}).get('src'):
                        media_urls.append(attachment['media']['image']['src'])
                    
                    # Check for video
                    if attachment.get('type') == 'video':
                        media_type = 'video'
                        if attachment.get('media', {}).get('source'):
                            media_urls.append(attachment['media']['source'])
            
            # Extract reactions
            likes = 0
            reactions = {
                'like': 0, 'love': 0, 'haha': 0, 'wow': 0, 'sad': 0, 'angry': 0
            }
            
            if post.get('likes'):
                likes = post['likes']['summary']['total_count']
                reactions['like'] = likes
            
            # Parse reaction breakdowns
            for reaction_type in reactions.keys():
                key = f'reactions_{reaction_type}'
                if key in post:
                    reactions[reaction_type] = post[key]['summary']['total_count']
            
            # Extract insights
            impressions = 0
            engaged_users = 0
            if post.get('insights'):
                insights_data = post['insights']['data']
                for insight in insights_data:
                    if insight['name'] == 'post_impressions':
                        impressions = insight['values'][0]['value'] if insight.get('values') else 0
                    elif insight['name'] == 'post_engaged_users':
                        engaged_users = insight['values'][0]['value'] if insight.get('values') else 0
            
            return {
                'platform_post_id': post['id'],
                'title': (post.get('message', post.get('story', ''))[:100] + '...') if post.get('message') or post.get('story') else 'Facebook Post',
                'content': post.get('message', post.get('story', '')),
                'post_url': post.get('permalink_url', ''),
                'media_urls': media_urls,
                'media_type': media_type,
                'likes': likes,
                'reactions': reactions,
                'comments': post.get('comments', {}).get('summary', {}).get('total_count', 0),
                'shares': post.get('shares', {}).get('count', 0),
                'impressions': impressions,
                'engaged_users': engaged_users,
                'engagement_rate': (engaged_users / impressions * 100) if impressions > 0 else 0,
                'published_at': post.get('created_time'),
                'metadata': {
                    'story': post.get('story', ''),
                    'is_published': True,
                    'reactions_breakdown': reactions
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to parse Facebook post: {e}")
            return None


class InstagramService(MetaBaseService):
    """Instagram Business Account API integration"""
    
    def __init__(self, platform):
        super().__init__(platform)
        self.instagram_account_id = platform.channel_id
    
    def _get_instagram_account_id(self) -> Optional[str]:
        """Get Instagram Business Account ID from Facebook Page"""
        try:
            # First, get the Facebook page ID from platform metadata
            page_id = self.platform.metadata.get('page_id')
            if not page_id:
                logger.error("No Facebook page ID found in platform metadata")
                return None
            
            # Get Instagram Business Account connected to this page
            data = self._make_request(
                page_id,
                params={'fields': 'instagram_business_account'}
            )
            
            if data.get('instagram_business_account'):
                ig_account_id = data['instagram_business_account']['id']
                # Save it back to platform
                self.platform.metadata['instagram_account_id'] = ig_account_id
                self.platform.save(update_fields=['metadata'])
                return ig_account_id
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get Instagram account ID: {e}")
            return None
    
    def fetch_channel_info(self) -> Optional[Dict]:
        """Fetch Instagram business account information"""
        try:
            # Ensure we have the Instagram account ID
            if not self.instagram_account_id:
                self.instagram_account_id = self._get_instagram_account_id()
                if not self.instagram_account_id:
                    logger.error("Could not find Instagram business account")
                    return None
            
            fields = [
                'id', 'username', 'name', 'biography', 'profile_picture_url',
                'followers_count', 'follows_count', 'media_count',
                'ig_id', 'website', 'business_discovery'
            ]
            
            data = self._make_request(
                self.instagram_account_id,
                params={'fields': ','.join(fields)}
            )
            
            # Fetch insights
            insights = self._fetch_account_insights()
            
            channel_info = {
                'channel_id': data.get('id'),
                'channel_name': data.get('username', ''),
                'full_name': data.get('name', ''),
                'profile_picture': data.get('profile_picture_url', ''),
                'biography': data.get('biography', ''),
                'website': data.get('website', ''),
                'followers': data.get('followers_count', 0),
                'following': data.get('follows_count', 0),
                'posts_count': data.get('media_count', 0),
                'total_reach': insights.get('reach', 0),
                'total_impressions': insights.get('impressions', 0),
                'profile_views': insights.get('profile_views', 0),
                'email_contacts': insights.get('email_contacts', 0),
                'phone_calls': insights.get('phone_calls', 0),
                'text_messages': insights.get('text_messages', 0),
                'website_clicks': insights.get('website_clicks', 0)
            }
            
            return channel_info
            
        except Exception as e:
            logger.error(f"Failed to fetch Instagram account info: {e}")
            return None
    
    def _fetch_account_insights(self, period='day', metric_type='total_value'):
        """Fetch Instagram account insights"""
        try:
            since = (timezone.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            until = timezone.now().strftime('%Y-%m-%d')
            
            metrics = [
                'reach', 'impressions', 'profile_views',
                'email_contacts', 'phone_calls', 'text_messages',
                'website_clicks', 'follower_count'
            ]
            
            data = self._make_request(
                f"{self.instagram_account_id}/insights",
                params={
                    'metric': ','.join(metrics),
                    'period': period,
                    'since': since,
                    'until': until
                }
            )
            
            insights = {}
            if data.get('data'):
                for metric in data['data']:
                    name = metric['name']
                    values = metric.get('values', [])
                    if values:
                        # Sum up values for the period
                        if metric_type == 'total_value':
                            insights[name] = sum(v.get('value', 0) for v in values)
                        else:
                            insights[name] = values[-1].get('value', 0)
            
            return insights
            
        except Exception as e:
            logger.warning(f"Failed to fetch Instagram insights: {e}")
            return {}
    
    def fetch_posts(self, limit=50) -> List[Dict]:
        """Fetch Instagram media posts"""
        try:
            if not self.instagram_account_id:
                self.instagram_account_id = self._get_instagram_account_id()
                if not self.instagram_account_id:
                    return []
            
            fields = [
                'id', 'caption', 'media_type', 'media_url', 'permalink',
                'timestamp', 'like_count', 'comments_count',
                'thumbnail_url', 'children{media_url,media_type}',
                'insights.metric(reach,impressions,saved)'
            ]
            
            data = self._make_request(
                f"{self.instagram_account_id}/media",
                params={
                    'fields': ','.join(fields),
                    'limit': min(limit, 100)
                }
            )
            
            posts = []
            for item in data.get('data', []):
                post_data = self._parse_post(item)
                if post_data:
                    posts.append(post_data)
            
            return posts
            
        except Exception as e:
            logger.error(f"Failed to fetch Instagram posts: {e}")
            return []
    
    def _parse_post(self, post):
        """Parse Instagram post data"""
        try:
            media_type = post.get('media_type', '').lower()
            media_url = post.get('media_url') or post.get('thumbnail_url', '')
            
            # Handle carousel posts
            media_urls = [media_url] if media_url else []
            if post.get('children'):
                children = post['children'].get('data', [])
                for child in children:
                    if child.get('media_url'):
                        media_urls.append(child['media_url'])
            
            # Extract insights
            insights = {}
            if post.get('insights'):
                for insight in post['insights'].get('data', []):
                    insights[insight['name']] = insight['values'][0]['value'] if insight.get('values') else 0
            
            return {
                'platform_post_id': post['id'],
                'title': (post.get('caption', '')[:100] + '...') if post.get('caption') else 'Instagram Post',
                'content': post.get('caption', ''),
                'post_url': post.get('permalink', ''),
                'media_urls': media_urls,
                'media_type': media_type,
                'likes': post.get('like_count', 0),
                'comments': post.get('comments_count', 0),
                'reach': insights.get('reach', 0),
                'impressions': insights.get('impressions', 0),
                'saved': insights.get('saved', 0),
                'published_at': post.get('timestamp'),
                'metadata': {
                    'media_type': media_type,
                    'has_children': 'children' in post,
                    'insights': insights
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to parse Instagram post: {e}")
            return None
    
    def fetch_stories(self, limit=25) -> List[Dict]:
        """Fetch Instagram stories (last 24 hours)"""
        try:
            if not self.instagram_account_id:
                self.instagram_account_id = self._get_instagram_account_id()
                if not self.instagram_account_id:
                    return []
            
            fields = [
                'id', 'media_type', 'media_url', 'permalink',
                'timestamp', 'insights.metric(impressions,reach,exits,replies)'
            ]
            
            data = self._make_request(
                f"{self.instagram_account_id}/stories",
                params={
                    'fields': ','.join(fields),
                    'limit': min(limit, 100)
                }
            )
            
            stories = []
            for item in data.get('data', []):
                story_data = self._parse_story(item)
                if story_data:
                    stories.append(story_data)
            
            return stories
            
        except Exception as e:
            logger.warning(f"Failed to fetch Instagram stories: {e}")
            return []
    
    def _parse_story(self, story):
        """Parse Instagram story data"""
        try:
            insights = {}
            if story.get('insights'):
                for insight in story['insights'].get('data', []):
                    insights[insight['name']] = insight['values'][0]['value'] if insight.get('values') else 0
            
            return {
                'platform_post_id': story['id'],
                'title': 'Instagram Story',
                'content': '',
                'post_url': story.get('permalink', ''),
                'media_urls': [story.get('media_url', '')],
                'media_type': story.get('media_type', '').lower(),
                'impressions': insights.get('impressions', 0),
                'reach': insights.get('reach', 0),
                'exits': insights.get('exits', 0),
                'replies': insights.get('replies', 0),
                'published_at': story.get('timestamp'),
                'metadata': {
                    'is_story': True,
                    'insights': insights
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to parse Instagram story: {e}")
            return None