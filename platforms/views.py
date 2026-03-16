import requests
import logging
import json
from django.conf import settings
from django.http import HttpResponseRedirect
from django.db.models import Count, Q, Sum, Avg
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from datetime import datetime, timedelta

from .models import Platform, ChannelStats, ChannelPost, PlatformFetchTask, UserSocialAccount
from .serializers import (
    PlatformSerializer, PlatformCreateSerializer, ChannelStatsSerializer,
    ChannelPostSerializer, DashboardStatsSerializer, BarChartDataSerializer,
    TopLiveDataSerializer, RecentProfilePostsSerializer, FetchTaskSerializer,
    ChannelInfoSerializer, ChannelStatsSummarySerializer, ChannelBarDataSerializer,
    ChannelRecentPostsSerializer, ChannelTopPostsSerializer,
    SubscriberGrowthSerializer, ChannelsListSerializer
)
from .producers import queue_platform_fetch, queue_batch_platform_fetch
from .services import fetch_platform_data

logger = logging.getLogger(__name__)


# Removed fetch_platform_data local definition



class PlatformCreateView(APIView):
    """Add a new platform/channel"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        serializer = PlatformCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        data: dict = serializer.validated_data  # type: ignore
        
        # Check if platform already exists for this user
        existing = Platform.objects.filter(
            user=request.user,
            name=data['name'],
            channel_id=data['channel_id']
        ).first()
        
        if existing:
            if existing.is_active:
                return Response({
                    "message": "Platform already exists",
                    "data": PlatformSerializer(existing).data,
                    "fetch_success": False
                }, status=status.HTTP_200_OK)
            else:
                # Reactivate and queue background fetch
                existing.is_active = True
                existing.save()
                
                try:
                    queue_platform_fetch(existing.id, "reactivate")
                    message = "Platform reactivated; fetch queued in background."
                except Exception as qex:
                    logger.warning(f"Failed to queue background fetch for platform {existing.id}: {qex}")
                    message = "Platform reactivated but failed to queue fetch."
                
                return Response({
                    "message": message,
                    "data": PlatformSerializer(existing).data,
                    "fetch_success": True
                })
        
        # Create new platform
        platform = Platform.objects.create(
            user=request.user,
            name=str(data.get('name', '')),
            channel_id=str(data.get('channel_id', '')),
            channel_url=str(data.get('channel_url', '')),
            channel_name=str(data.get('channel_id', '')),  # Will be updated by fetch
            metadata={}
        )
        
        # Queue background fetch
        try:
            queue_platform_fetch(platform.id, "initial")
            message = "Platform added; fetch queued for background processing."
        except Exception as qex:
            logger.warning(f"Failed to queue background fetch for platform {platform.id}: {qex}")
            message = "Platform added but failed to queue background fetch."
        
        return Response({
            "message": message,
            "data": PlatformSerializer(platform).data,
            "fetch_success": True
        }, status=status.HTTP_201_CREATED)


class PlatformListView(APIView):
    """Get all platforms for current user"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        platforms = Platform.objects.filter(
            user=request.user,
            is_active=True
        ).order_by('-created_at')
        
        serializer = PlatformSerializer(platforms, many=True)
        return Response({
            "success": True,
            "data": serializer.data
        })


class PlatformDetailView(APIView):
    """Get, update, delete a specific platform"""
    permission_classes = [IsAuthenticated]
    
    def get_object(self, pk):
        return get_object_or_404(Platform, id=pk, user=self.request.user)
    
    def get(self, request, pk):
        platform = self.get_object(pk)
        serializer = PlatformSerializer(platform)
        return Response(serializer.data)
    
    def delete(self, request, pk):
        platform = self.get_object(pk)
        platform.delete()
        return Response({"message": "Platform removed successfully"})


class PlatformDashboardView(APIView):
    """Main dashboard data for platforms page"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        platforms = Platform.objects.filter(
            user=request.user,
            is_active=True
        ).prefetch_related('stats', 'posts')
        
        if not platforms.exists():
            return Response({
                "success": True,
                "data": {
                    "barData": [],
                    "stats": [
                        {"label": "Post", "value": "0"},
                        {"label": "Following", "value": "0"},
                        {"label": "Followers", "value": "0"},
                        {"label": "Likes", "value": "0"},
                        {"label": "Comment", "value": "0"},
                    ],
                    "topFive": [],
                    "recentProfilePosts": []
                }
            })
        
        # Get date range from query params - support both parameter names
        from_date = request.query_params.get('from') or request.query_params.get('start_date')
        to_date = request.query_params.get('to') or request.query_params.get('end_date')
        
        date_range = {}
        if from_date and to_date:
            date_range = {
                'start': datetime.strptime(from_date, '%Y-%m-%d').date(),
                'end': datetime.strptime(to_date, '%Y-%m-%d').date()
            }
        
        # Prepare data for dashboard
        dashboard_data = {
            'platforms': platforms,
            'user': request.user,
            'date_range': date_range
        }
        
        # Use to_representation directly for serializers that return lists
        bar_chart_serializer = BarChartDataSerializer()
        dashboard_stats_serializer = DashboardStatsSerializer()
        top_live_serializer = TopLiveDataSerializer()
        recent_posts_serializer = RecentProfilePostsSerializer()
        subscriber_growth_serializer = SubscriberGrowthSerializer()
        
        # build per-channel slide lists for top/live and recent posts
        top_by_channel = []
        recent_by_channel = []
        for plat in platforms:
            label = plat.channel_name or plat.name.title()
            top_items = top_live_serializer.to_representation({
                'platforms': [plat],
                'limit': 5,
            })
            recent_items = recent_posts_serializer.to_representation({
                'platforms': [plat],
                'limit': 5,
            })
            top_by_channel.append({'channel': label, 'list': top_items})
            recent_by_channel.append({'channel': label, 'list': recent_items})

        stats_repr = dashboard_stats_serializer.to_representation(dashboard_data)  # type: ignore
        response_data = {
            'barData': bar_chart_serializer.to_representation(dashboard_data),
            'lineChart': subscriber_growth_serializer.to_representation({
                'platforms': platforms
            }),
            'stats': stats_repr.get('stats', []) if isinstance(stats_repr, dict) else [],
            'topFive': top_by_channel,
            'recentProfilePosts': recent_by_channel,
        }
        
        return Response({
            "success": True,
            "data": response_data
        })

class SystemMetaConnectView(APIView):
    """Connect Meta platforms using pre-configured system credentials (.env)"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request, platform):
        platform_name = platform.lower()
        if platform_name not in ["facebook", "instagram"]:
            return Response({"error": "Only Facebook and Instagram supported for system connect"}, status=status.HTTP_400_BAD_REQUEST)
            
        page_id = settings.FACEBOOK_PAGE_ID
        page_token = settings.FACEBOOK_PAGE_ACCESS_TOKEN
        
        if not page_id or not page_token:
            return Response({
                "error": "System credentials (FACEBOOK_PAGE_ID/TOKEN) not configured in .env",
                "configured": False
            }, status=status.HTTP_400_BAD_REQUEST)
            
        # For Instagram, we use the same Page ID and token (we'll look up IG ID in service)
        # Check if platform already exists
        existing = Platform.objects.filter(
            user=request.user,
            name=platform_name,
            channel_id=page_id
        ).first()
        
        if existing:
            return Response({
                "message": f"{platform_name.capitalize()} already connected via system credentials",
                "data": PlatformSerializer(existing).data
            })
            
        # Create platform
        new_platform = Platform.objects.create(
            user=request.user,
            name=platform_name,
            channel_id=page_id,
            channel_url=f"https://www.facebook.com/{page_id}" if platform_name == "facebook" else "https://www.instagram.com/",
            channel_name=f"System {platform_name.capitalize()}",
            metadata={
                "system_auth": True,
                "page_id": page_id,
                "page_access_token": page_token
            }
        )
        
        try:
            queue_platform_fetch(new_platform.id, "initial")
            message = f"{platform_name.capitalize()} connected successfully using system credentials."
        except Exception as e:
            message = f"{platform_name.capitalize()} connected, but background fetch failed to queue."
            
        return Response({
            "message": message,
            "data": PlatformSerializer(new_platform).data,
            "configured": True
        })

    def get(self, request, platform):
        """Check if system credentials are configured"""
        is_configured = bool(settings.FACEBOOK_PAGE_ID and settings.FACEBOOK_PAGE_ACCESS_TOKEN)
        return Response({
            "platform": platform,
            "configured": is_configured
        })


class OAuthInitiateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, platform):
        platform = platform.lower()
        supported = ["facebook", "instagram"]
        if platform not in supported:
            return Response({"error": "Unsupported platform"}, status=status.HTTP_400_BAD_REQUEST)

        # Build callback URI
        from django.urls import reverse
        redirect_uri = request.build_absolute_uri(
            reverse('platform-oauth-callback', args=[platform])
        )
        
        # Meta prefers localhost over 127.0.0.1
        if "127.0.0.1" in redirect_uri:
            redirect_uri = redirect_uri.replace("127.0.0.1", "localhost")
        
        # Get JWT token for state parameter
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        token_value = None
        if auth_header.startswith('Bearer '):
            token_value = auth_header.split(' ', 1)[1]
        
        # OAuth scopes based on platform
        scopes = {
            'facebook': 'pages_show_list,pages_read_engagement,pages_read_user_content',
            'instagram': 'instagram_basic,instagram_manage_insights,pages_show_list,pages_read_engagement'
        }
        
        # Build auth URL
        auth_url = (
            f"https://www.facebook.com/{settings.FACEBOOK_API_VERSION}/dialog/oauth"
            f"?client_id={settings.FACEBOOK_APP_ID}"
            f"&redirect_uri={redirect_uri}"
            f"&scope={scopes[platform]}"
            f"&response_type=code"
        )
        
        # Add state with token
        if token_value:
            import urllib.parse
            state = urllib.parse.quote(json.dumps({'token': token_value}))
            auth_url += f"&state={state}"
        
        return Response({
            "auth_url": auth_url,
            "redirect_uri": redirect_uri,
            "platform": platform
        })


class OAuthCallbackView(APIView):
    permission_classes = []  # No auth required for OAuth callback

    def get(self, request, platform):
        print(f"DEBUG OAuthCallbackView.get - Entering callback for platform: {platform}")
        print(f"DEBUG OAuthCallbackView.get - Full Path: {request.get_full_path()}")
        platform = platform.lower()
        code = request.GET.get('code')
        error = request.GET.get('error')
        error_reason = request.GET.get('error_reason')
        error_description = request.GET.get('error_description')
        state = request.GET.get('state')
        
        frontend_url = settings.FRONTEND_URL.rstrip('/')
        
        # Handle OAuth error
        if error or not code:
            logger.error(f"OAuth error for {platform}: {error} - {error_description}")
            redirect_url = (
                f"{frontend_url}/platforms"
                f"?oauth_error=true"
                f"&platform={platform}"
                f"&reason={error_reason or 'access_denied'}"
            )
            return HttpResponseRedirect(redirect_url)
        
        # Extract user from state
        user = self._get_user_from_state(state)
        if not user:
            logger.error("Could not authenticate user from OAuth state")
            redirect_url = f"{frontend_url}/platforms?oauth_error=1&reason=authentication_failed"
            return HttpResponseRedirect(redirect_url)
        
        # Exchange code for tokens
        try:
            # Step 1: Exchange code for short-lived token
            token_data = self._exchange_code_for_token(request, platform, code)
            if not token_data or 'access_token' not in token_data:
                raise Exception("Failed to get access token")
            
            short_lived_token = token_data['access_token']
            
            # DEBUG: Inspect the token
            inspect_url = "https://graph.facebook.com/debug_token"
            inspect_params = {
                'input_token': short_lived_token,
                'access_token': f"{settings.FACEBOOK_APP_ID}|{settings.FACEBOOK_APP_SECRET}"
            }
            inspect_res = requests.get(inspect_url, params=inspect_params)
            print(f"DEBUG OAuthCallbackView.get - Token Inspection: {inspect_res.json()}")
            
            # DEBUG: Try accounts with short-lived token
            sl_accounts = requests.get(f"https://graph.facebook.com/{settings.FACEBOOK_API_VERSION}/me/accounts", params={'access_token': short_lived_token})
            print(f"DEBUG OAuthCallbackView.get - Short-lived accounts count: {len(sl_accounts.json().get('data', []))}")
            if sl_accounts.json().get('data'):
                 print(f"DEBUG OAuthCallbackView.get - Short-lived accounts: {[p.get('name') for p in sl_accounts.json().get('data')]}")
            
            # Step 2: Exchange for long-lived token
            long_lived_token = self._get_long_lived_token(short_lived_token)
            
            # DEBUG: Check user identity
            user_res = requests.get(f"https://graph.facebook.com/{settings.FACEBOOK_API_VERSION}/me", params={'fields': 'id,name', 'access_token': long_lived_token})
            print(f"DEBUG OAuthCallbackView.get - FB Connected User: {user_res.json()}")
            
            # DEBUG: Check permissions
            perm_res = requests.get(f"https://graph.facebook.com/{settings.FACEBOOK_API_VERSION}/me/permissions", params={'access_token': long_lived_token})
            print(f"DEBUG OAuthCallbackView.get - Granted Permissions: {perm_res.json().get('data')}")
            
            # Step 3: Get page access tokens
            print(f"DEBUG OAuthCallbackView.get - Fetching pages for user with long-lived token...")
            pages_data = self._get_user_pages(long_lived_token)
            print(f"DEBUG OAuthCallbackView.get - Raw pages data count: {len(pages_data)}")
            for idx, p in enumerate(pages_data):
                print(f"DEBUG OAuthCallbackView.get - Page {idx}: {p.get('name')} (IG Business: {bool(p.get('instagram_business_account'))})")
            
            # Step 4: Create or update platforms
            print(f"DEBUG OAuthCallbackView.get - Calling _create_platforms with type: {platform}")
            platforms_created = self._create_platforms(
                user=user,
                platform_type=platform,
                long_lived_token=long_lived_token,
                pages_data=pages_data,
                token_expiry=token_data.get('expires_in', 5184000)  # Default 60 days
            )
            print(f"DEBUG OAuthCallbackView.get - Platforms created count: {len(platforms_created)}")
            for p in platforms_created:
                print(f"DEBUG OAuthCallbackView.get - Created/Updated: {p.name} - {p.channel_name}")
            
            # Queue fetch for each platform (async)
            for platform_obj in platforms_created:
                try:
                    queue_platform_fetch(platform_obj.id, 'initial')
                except Exception as qex:
                    logger.warning(f"Failed to queue fetch for platform {platform_obj.id}: {qex}")
            
            # Also fetch data synchronously so it shows immediately
            for platform_obj in platforms_created:
                try:
                    from .meta_services import FacebookService, InstagramService
                    from .platform_services import TwitterService
                    
                    if platform_obj.name == 'facebook':
                        print(f"DEBUG OAuthCallbackView - Using FacebookService for {platform_obj.channel_id}")
                        service = FacebookService(platform_obj)
                    elif platform_obj.name == 'instagram':
                        print(f"DEBUG OAuthCallbackView - Using InstagramService for {platform_obj.channel_id}")
                        service = InstagramService(platform_obj)
                    elif platform_obj.name == 'twitter':
                        print(f"DEBUG OAuthCallbackView - Using TwitterService for {platform_obj.channel_id}")
                        service = TwitterService(platform_obj)
                    else:
                        print(f"DEBUG OAuthCallbackView - Unknown platform type: {platform_obj.name}")
                        continue
                    
                    # Fetch channel info
                    print(f"DEBUG OAuthCallbackView - Fetching channel info...")
                    channel_info = service.fetch_channel_info()
                    print(f"DEBUG OAuthCallbackView - Channel info result: {bool(channel_info)}")
                    
                    if channel_info:
                        platform_obj.channel_name = channel_info.get('channel_name', platform_obj.channel_id)
                        platform_obj.profile_picture = channel_info.get('profile_picture', '')
                        platform_obj.save()
                        print(f"DEBUG OAuthCallbackView - Platform updated: {platform_obj.channel_name}")
                        
                        # Create stats
                        from .models import ChannelStats
                        ChannelStats.objects.create(
                            platform=platform_obj,
                            followers=channel_info.get('followers', 0),
                            posts_count=channel_info.get('posts_count', 0),
                            impressions=channel_info.get('total_reach', 0),
                            period_start=timezone.now().replace(hour=0, minute=0, second=0, microsecond=0),
                            period_end=timezone.now() + timedelta(days=1),
                            collected_at=timezone.now(),
                        )
                        print(f"DEBUG OAuthCallbackView - Stats created: followers={channel_info.get('followers', 0)}")
                    
                    # Fetch posts
                    print(f"DEBUG OAuthCallbackView - Fetching posts...")
                    posts = service.fetch_posts(limit=15)
                    print(f"DEBUG OAuthCallbackView - Posts fetched: {len(posts)}")
                    
                    for post_data in posts:
                        from .models import ChannelPost
                        # Parse published_at
                        published_at = post_data.get('published_at')
                        if isinstance(published_at, str):
                            try:
                                from dateutil.parser import parse
                                published_at = parse(published_at)
                            except:
                                published_at = timezone.now()
                        
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
                                'published_at': published_at,
                                'collected_at': timezone.now(),
                            }
                        )
                    logger.info(f"Synchronous fetch completed for {platform_obj.name}: {platform_obj.channel_id}")
                    print(f"DEBUG OAuthCallbackView - Sync fetch completed for {platform_obj.name}")
                except Exception as sex:
                    print(f"DEBUG OAuthCallbackView - ERROR in sync fetch for {platform_obj.id}: {str(sex)}")
                    import traceback
                    traceback.print_exc()
                    logger.warning(f"Failed synchronous fetch for {platform_obj.id}: {sex}", exc_info=True)
            
            redirect_url = (
                f"{frontend_url}/platforms"
                f"?oauth_success=true"
                f"&platform={platform}"
                f"&count={len(platforms_created)}"
            )
            
        except Exception as e:
            logger.error(f"OAuth token exchange failed: {e}", exc_info=True)
            redirect_url = (
                f"{frontend_url}/platforms"
                f"?oauth_error=true"
                f"&platform={platform}"
                f"&reason=token_exchange_failed"
            )
        
        return HttpResponseRedirect(redirect_url)
    
    def _get_user_from_state(self, state):
        """Extract user from OAuth state parameter"""
        if not state:
            return None
        
        try:
            import urllib.parse
            import json
            
            # State might be URL encoded
            decoded_state = urllib.parse.unquote(state)
            state_data = json.loads(decoded_state)
            token = state_data.get('token')
            
            if token:
                from rest_framework_simplejwt.tokens import AccessToken
                access_token = AccessToken(token)
                from django.contrib.auth import get_user_model
                User = get_user_model()
                return User.objects.filter(id=access_token['user_id']).first()
        except Exception as e:
            logger.error(f"Failed to extract user from state: {e}")
        
        return None
    
    def _exchange_code_for_token(self, request, platform, code):
        """Exchange authorization code for access token"""
        # Build redirect URI (must match the one used in authorization)
        from django.urls import reverse
        redirect_uri = request.build_absolute_uri(
            reverse('platform-oauth-callback', args=[platform])
        )
        if "127.0.0.1" in redirect_uri:
            redirect_uri = redirect_uri.replace("127.0.0.1", "localhost")
        
        token_url = f"https://graph.facebook.com/{settings.FACEBOOK_API_VERSION}/oauth/access_token"
        
        params = {
            'client_id': settings.FACEBOOK_APP_ID,
            'client_secret': settings.FACEBOOK_APP_SECRET,
            'redirect_uri': redirect_uri,
            'code': code
        }
        
        response = requests.get(token_url, params=params)
        response.raise_for_status()
        return response.json()
    
    def _get_long_lived_token(self, short_lived_token):
        """Exchange short-lived token for long-lived token (60 days)"""
        url = f"https://graph.facebook.com/{settings.FACEBOOK_API_VERSION}/oauth/access_token"
        
        params = {
            'grant_type': 'fb_exchange_token',
            'client_id': settings.FACEBOOK_APP_ID,
            'client_secret': settings.FACEBOOK_APP_SECRET,
            'fb_exchange_token': short_lived_token
        }
        
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        return data.get('access_token')
    
    def _get_user_pages(self, access_token):
        """Get Facebook pages accessible with this token"""
        url = f"https://graph.facebook.com/{settings.FACEBOOK_API_VERSION}/me/accounts"
        
        params = {
            'access_token': access_token,
            'fields': 'id,name,access_token,instagram_business_account{id,username,name,profile_picture_url},picture,fan_count'
        }
        
        response = requests.get(url, params=params)
        print(f"DEBUG _get_user_pages - Response Status: {response.status_code}")
        print(f"DEBUG _get_user_pages - Response Body: {response.text}")
        response.raise_for_status()
        return response.json().get('data', [])
    
    def _create_platforms(self, user, platform_type, long_lived_token, pages_data, token_expiry):
        """Create platform entries for pages"""
        platforms_created = []
        
        # Calculate expiry datetime
        expiry_dt = timezone.now() + timedelta(seconds=token_expiry)
        
        for page in pages_data:
            print(f"DEBUG _create_platforms - Processing page: {page.get('name')} ({page.get('id')})")
            print(f"DEBUG _create_platforms - Instagram data found: {bool(page.get('instagram_business_account'))}")
            if page.get('instagram_business_account'):
                print(f"DEBUG _create_platforms - Instagram details: {page.get('instagram_business_account')}")
            
            page_id = page['id']
            page_name = page['name']
            page_token = page['access_token']
            fan_count = page.get('fan_count', 0)
            
            # Create Instagram platform if business account exists and user chose instagram
            if platform_type == 'instagram' and page.get('instagram_business_account'):
                ig_info = page['instagram_business_account']
                ig_account_id = ig_info['id']
                ig_username = ig_info.get('username', ig_account_id)
                ig_name = ig_info.get('name', ig_username)
                ig_pic = ig_info.get('profile_picture_url', '')
                
                # Create or update Instagram platform
                platform, created = Platform.objects.update_or_create(
                    user=user,
                    name='instagram',
                    channel_id=ig_account_id,
                    defaults={
                        'channel_url': f"https://instagram.com/{ig_username}",
                        'channel_name': ig_name,
                        'profile_picture': ig_pic,
                        'is_active': True,
                        'metadata': {
                            'access_token': long_lived_token,
                            'page_access_token': page_token,
                            'page_id': page_id,
                            'page_name': page_name,
                            'instagram_account_id': ig_account_id,
                            'instagram_username': ig_username,
                            'token_expires_at': expiry_dt.isoformat(),
                            'scopes': ['instagram_basic', 'instagram_manage_insights', 'pages_read_engagement']
                        }
                    }
                )
                platforms_created.append(platform)

                # Create UserSocialAccount (required by background consumer)
                UserSocialAccount.objects.update_or_create(
                    user=user,
                    platform='instagram',
                    account_id=ig_account_id,
                    defaults={
                        'access_token': page_token,
                        'account_name': ig_name,
                        'token_expiry': expiry_dt,
                        'is_token_valid': True,
                        'scopes': ['instagram_basic', 'instagram_manage_insights', 'pages_read_engagement']
                    }
                )
            
            # Create Facebook platform only if user chose facebook
            if platform_type == 'facebook':
                platform, created = Platform.objects.update_or_create(
                    user=user,
                    name='facebook',
                    channel_id=page_id,
                    defaults={
                        'channel_url': f"https://facebook.com/{page_id}",
                        'channel_name': page_name,
                        'is_active': True,
                        'metadata': {
                            'access_token': long_lived_token,
                            'page_access_token': page_token,
                            'page_id': page_id,
                            'page_name': page_name,
                            'fan_count': fan_count,
                            'token_expires_at': expiry_dt.isoformat(),
                            'scopes': ['pages_show_list', 'pages_read_engagement', 'pages_read_user_content']
                        }
                    }
                )
                platforms_created.append(platform)

                # Create UserSocialAccount (required by background consumer)
                UserSocialAccount.objects.update_or_create(
                    user=user,
                    platform='facebook',
                    account_id=page_id,
                    defaults={
                        'access_token': page_token,
                        'account_name': page_name,
                        'token_expiry': expiry_dt,
                        'is_token_valid': True,
                        'scopes': ['pages_show_list', 'pages_read_engagement', 'pages_read_user_content']
                    }
                )
        
        return platforms_created


class TwitterOAuthInitiateView(APIView):
    """Initiate Twitter (X) OAuth 2.0 flow"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Check if Twitter OAuth is configured
        print(f"DEBUG TwitterOAuthInitiateView - TWITTER_APP_ID: {bool(settings.TWITTER_APP_ID)}, TWITTER_APP_SECRET: {bool(settings.TWITTER_APP_SECRET)}")
        print(f"DEBUG TwitterOAuthInitiateView - APP_ID value: {settings.TWITTER_APP_ID[:20] if settings.TWITTER_APP_ID else 'EMPTY'}")
        
        if not settings.TWITTER_APP_ID or not settings.TWITTER_APP_SECRET:
            print("ERROR: Twitter OAuth credentials missing")
            # Check if Bearer token is available for system connect
            if settings.TWITTER_BEARER_TOKEN:
                return Response({
                    "error": "OAuth not configured. Use system-connect endpoint instead.",
                    "use_system_connect": True,
                    "configured": False
                }, status=status.HTTP_400_BAD_REQUEST)
            return Response({
                "error": "Twitter credentials not configured",
                "configured": False
            }, status=status.HTTP_400_BAD_REQUEST)

        # Build callback URI
        from django.urls import reverse
        redirect_uri = request.build_absolute_uri(
            reverse('platform-oauth-callback', args=['twitter'])
        )
        
        # Replace 127.0.0.1 with localhost
        if "127.0.0.1" in redirect_uri:
            redirect_uri = redirect_uri.replace("127.0.0.1", "localhost")
        
        # Get JWT token for state parameter
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        token_value = None
        if auth_header.startswith('Bearer '):
            token_value = auth_header.split(' ', 1)[1]
        
        # Generate PKCE code verifier and challenge
        import secrets
        import base64
        import hashlib
        
        code_verifier = secrets.token_urlsafe(64)[:128]
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).rstrip(b'=').decode('utf-8')
        
        # Store code verifier in session or return it (for simplicity, we'll include in state)
        # In production, store securely in session/DB
        import urllib.parse
        state_data = {
            'token': token_value,
            'code_verifier': code_verifier
        }
        state = urllib.parse.quote(json.dumps(state_data))
        
        # Build Twitter OAuth 2.0 authorization URL
        # Twitter uses OAuth 2.0 with PKCE
        auth_url = (
            "https://twitter.com/i/oauth2/authorize"
            f"?client_id={settings.TWITTER_APP_ID}"
            f"&redirect_uri={urllib.parse.quote(redirect_uri)}"
            f"&response_type=code"
            f"&scope=tweet.read users.read follows.read follows.write"
            f"&state={state}"
            f"&code_challenge={code_challenge}"
            f"&code_challenge_method=S256"
        )
        
        return Response({
            "auth_url": auth_url,
            "redirect_uri": redirect_uri,
            "platform": "twitter"
        })


class TwitterOAuthCallbackView(APIView):
    """Handle Twitter OAuth callback"""
    permission_classes = []  # No auth required for OAuth callback

    def get(self, request):
        code = request.GET.get('code')
        error = request.GET.get('error')
        error_description = request.GET.get('error_description')
        state = request.GET.get('state')
        
        frontend_url = settings.FRONTEND_URL.rstrip('/')
        
        # Handle OAuth error
        if error or not code:
            logger.error(f"OAuth error for Twitter: {error} - {error_description}")
            redirect_url = (
                f"{frontend_url}/platforms"
                f"?oauth_error=1"
                f"&platform=twitter"
                f"&reason={error or 'access_denied'}"
            )
            return HttpResponseRedirect(redirect_url)
        
        # Extract user and code verifier from state
        user, code_verifier = self._get_user_from_state(state)
        if not user:
            logger.error("Could not authenticate user from OAuth state")
            redirect_url = f"{frontend_url}/platforms?oauth_error=1&reason=authentication_failed"
            return HttpResponseRedirect(redirect_url)
        
        # Exchange code for tokens
        try:
            # Build redirect URI
            from django.urls import reverse
            redirect_uri = request.build_absolute_uri(
                reverse('platform-oauth-callback', args=['twitter'])
            )
            if "127.0.0.1" in redirect_uri:
                redirect_uri = redirect_uri.replace("127.0.0.1", "localhost")
            
            # Exchange code for tokens
            token_data = self._exchange_code_for_token(code, redirect_uri, code_verifier)
            if not token_data:
                raise Exception("Failed to get access token")
            
            access_token = token_data.get('access_token')
            refresh_token = token_data.get('refresh_token')
            expires_in = token_data.get('expires_in', 1800)  # Default 30 minutes
            
            # Get authenticated user's Twitter account info
            user_info = self._get_twitter_user_info(access_token)
            if not user_info:
                raise Exception("Failed to get Twitter user info")
            
            twitter_username = user_info.get('username')
            twitter_user_id = user_info.get('id')
            
            # Create or update platform
            platform = self._create_or_update_platform(
                user=user,
                twitter_user_id=twitter_user_id,
                twitter_username=twitter_username,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_in=expires_in
            )
            
            # Queue background fetch
            try:
                queue_platform_fetch(platform.id, 'initial')
            except Exception as qex:
                logger.warning(f"Failed to queue fetch for platform {platform.id}: {qex}")
            
            # Also fetch data synchronously so it shows immediately
            try:
                from .platform_services import TwitterService
                service = TwitterService(platform)
                
                # Fetch channel info
                channel_info = service.fetch_channel_info()
                if channel_info:
                    platform.channel_name = str(channel_info.get('channel_name') or twitter_username)
                    platform.profile_picture = str(channel_info.get('profile_picture') or '')
                    platform.channel_url = f"https://twitter.com/{twitter_username}"
                    platform.save()
                    
                    # Create stats
                    from .models import ChannelStats
                    ChannelStats.objects.create(
                        platform=platform,
                        followers=channel_info.get('followers', 0),
                        following=channel_info.get('following', 0),
                        posts_count=channel_info.get('posts_count', 0),
                        impressions=channel_info.get('impressions', 0),
                        period_start=timezone.now().replace(hour=0, minute=0, second=0, microsecond=0),
                        period_end=timezone.now() + timedelta(days=1),
                        collected_at=timezone.now(),
                    )
                
                # Fetch tweets
                tweets = service.fetch_posts(limit=15)
                for tweet_data in tweets:
                    from .models import ChannelPost
                    published_at = tweet_data.get('published_at')
                    if isinstance(published_at, str):
                        try:
                            from dateutil.parser import parse
                            published_at = parse(published_at)
                        except:
                            published_at = timezone.now()
                    
                    ChannelPost.objects.update_or_create(
                        platform=platform,
                        platform_post_id=tweet_data.get('platform_post_id'),
                        defaults={
                            'title': tweet_data.get('title', ''),
                            'content': tweet_data.get('content', ''),
                            'post_url': tweet_data.get('post_url', ''),
                            'media_urls': tweet_data.get('media_urls', []),
                            'media_type': tweet_data.get('media_type', ''),
                            'likes': tweet_data.get('likes', 0),
                            'comments': tweet_data.get('comments', 0),
                            'shares': tweet_data.get('shares', 0),
                            'views': tweet_data.get('views', 0),
                            'published_at': published_at,
                            'collected_at': timezone.now(),
                        }
                    )
                logger.info(f"Synchronous fetch completed for Twitter: {twitter_username}")
            except Exception as sex:
                logger.warning(f"Failed synchronous fetch for Twitter: {sex}")
            
            redirect_url = (
                f"{frontend_url}/platforms"
                f"?oauth_success=1"
                f"&platform=twitter"
            )
            
        except Exception as e:
            logger.error(f"Twitter OAuth token exchange failed: {e}", exc_info=True)
            redirect_url = (
                f"{frontend_url}/platforms"
                f"?oauth_error=1"
                f"&platform=twitter"
                f"&reason=token_exchange_failed"
            )
        
        return HttpResponseRedirect(redirect_url)
    
    def _get_user_from_state(self, state):
        """Extract user and code verifier from OAuth state parameter"""
        if not state:
            return None, None
        
        try:
            import urllib.parse
            decoded_state = urllib.parse.unquote(state)
            state_data = json.loads(decoded_state)
            token = state_data.get('token')
            code_verifier = state_data.get('code_verifier')
            
            if token:
                from rest_framework_simplejwt.tokens import AccessToken
                access_token = AccessToken(token)
                from django.contrib.auth import get_user_model
                User = get_user_model()
                user = User.objects.filter(id=access_token['user_id']).first()
                return user, code_verifier
        except Exception as e:
            logger.error(f"Failed to extract user from state: {e}")
        
        return None, None
    
    def _exchange_code_for_token(self, code, redirect_uri, code_verifier):
        """Exchange authorization code for access token"""
        import urllib.request
        import urllib.parse
        
        token_url = "https://api.twitter.com/2/oauth2/token"
        
        # URL encode the credentials
        import base64
        credentials = f"{settings.TWITTER_APP_ID}:{settings.TWITTER_APP_SECRET}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        
        data = urllib.parse.urlencode({
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': redirect_uri,
            'client_id': settings.TWITTER_APP_ID,
            'code_verifier': code_verifier,
        }).encode()
        
        req = urllib.request.Request(
            token_url,
            data=data,
            method='POST'
        )
        req.add_header('Authorization', f'Basic {encoded_credentials}')
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode())
        except Exception as e:
            logger.error(f"Token exchange failed: {e}")
            return None
    
    def _get_twitter_user_info(self, access_token):
        """Get authenticated user's Twitter info"""
        url = "https://api.twitter.com/2/users/me"
        params = {
            'user.fields': 'public_metrics,description,profile_image_url,created_at'
        }
        
        import urllib.request
        import urllib.parse
        
        full_url = f"{url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(full_url)
        req.add_header('Authorization', f'Bearer {access_token}')
        
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())
                if data.get('data'):
                    user = data['data']
                    # Get the username from the 'username' field, not 'name'
                    return {
                        'id': user.get('id'),
                        'username': user.get('username'),
                        'name': user.get('name'),
                        'profile_image_url': user.get('profile_image_url'),
                    }
        except Exception as e:
            logger.error(f"Failed to get Twitter user info: {e}")
        return None
    
    def _create_or_update_platform(self, user, twitter_user_id, twitter_username, access_token, refresh_token, expires_in):
        """Create or update Twitter platform"""
        platform, created = Platform.objects.update_or_create(
            user=user,
            name='twitter',
            channel_id=twitter_user_id,
            defaults={
                'channel_url': f"https://twitter.com/{twitter_username}",
                'channel_name': twitter_username,
                'is_active': True,
                'metadata': {
                    'access_token': access_token,
                    'refresh_token': refresh_token,
                    'username': twitter_username,
                    'token_expires_at': (
                        timezone.now() + timedelta(seconds=expires_in)
                    ).isoformat(),
                    'scopes': ['tweet.read', 'users.read', 'follows.read', 'follows.write'],
                    'oauth_type': 'oauth2',
                }
            }
        )
        return platform


class SystemTwitterConnectView(APIView):
    """Connect Twitter using pre-configured system credentials (.env)"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        bearer_token = settings.TWITTER_BEARER_TOKEN
        
        if not bearer_token:
            return Response({
                "error": "Twitter credentials (TWITTER_BEARER_TOKEN) not configured in .env",
                "configured": False
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get username from request body
        username = request.data.get('username', '').lstrip('@')
        
        if not username:
            return Response({
                "error": "Username is required"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if platform already exists
        existing = Platform.objects.filter(
            user=request.user,
            name='twitter',
            channel_id=username
        ).first()
        
        if existing:
            return Response({
                "message": f"Twitter @{username} already connected via system credentials",
                "data": PlatformSerializer(existing).data
            })
        
        # Create platform
        new_platform = Platform.objects.create(
            user=request.user,
            name='twitter',
            channel_id=username,
            channel_url=f"https://twitter.com/{username}",
            channel_name=username,
            metadata={
                "system_auth": True,
                "bearer_token": bearer_token,
                "oauth_type": "bearer_token",
            }
        )
        
        try:
            queue_platform_fetch(new_platform.id, "initial")
            message = f"Twitter @{username} connected successfully using system credentials."
        except Exception as e:
            message = f"Twitter @{username} connected, but background fetch failed to queue."
            
        return Response({
            "message": message,
            "data": PlatformSerializer(new_platform).data,
            "configured": True
        })

    def get(self, request):
        """Check if system credentials are configured"""
        is_configured = bool(settings.TWITTER_BEARER_TOKEN)
        return Response({
            "platform": "twitter",
            "configured": is_configured
        })


class PlatformRefreshView(APIView):
    """Trigger refresh for all platforms or specific one"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request, platform_id=None):
        if platform_id:
            # Refresh specific platform
            platform = get_object_or_404(
                Platform, 
                id=platform_id, 
                user=request.user,
                is_active=True
            )
            
            queue_platform_fetch(platform.id, "update")
            return Response({
                "message": f"Refresh triggered for {platform.name}"
            })
        else:
            # Refresh all platforms
            platforms = Platform.objects.filter(
                user=request.user,
                is_active=True
            )
            
            platform_ids = list(platforms.values_list('id', flat=True))
            queue_batch_platform_fetch(platform_ids, "update")
            
            return Response({
                "message": f"Refresh triggered for {len(platform_ids)} platforms"
            })


# Channel Page Views

class PlatformChannelDataView(APIView):
    """Get all data for a specific channel"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request, platform_name, channel_id):
        platform = get_object_or_404(
            Platform,
            user=request.user,
            name__iexact=platform_name,
            channel_id=channel_id,
            is_active=True
        )
        
        # Get timeframe from query params
        timeframe = request.query_params.get('timeframe', 'weekly')
        start_date = request.query_params.get('startDate')
        end_date = request.query_params.get('endDate')
        
        # Calculate date range based on timeframe
        now = timezone.now()
        if start_date and end_date:
            period_start = datetime.strptime(start_date, '%Y-%m-%d')
            period_end = datetime.strptime(end_date, '%Y-%m-%d')
        else:
            if timeframe == 'weekly':
                period_start = now - timedelta(days=7)
                period_end = now
            elif timeframe == 'monthly':
                period_start = now - timedelta(days=30)
                period_end = now
            else:  # yearly
                period_start = now - timedelta(days=365)
                period_end = now
        
        # Get posts within period
        posts = platform.posts.filter(  # type: ignore[attr-defined]
            published_at__gte=period_start,
            published_at__lte=period_end
        )
        
        # Prepare response data
        channel_data = {
            'platform': platform,
            'posts': posts,
            'timeframe': timeframe,
            'limit': 10
        }
        
        # Use to_representation directly for these serializers
        stats_serializer = ChannelStatsSummarySerializer()
        bar_serializer = ChannelBarDataSerializer()
        channel_info_serializer = ChannelInfoSerializer()
        recent_posts_serializer = ChannelRecentPostsSerializer()
        top_posts_serializer = ChannelTopPostsSerializer()
        
        # include platform id so front end can trigger sentiment analysis easily
        response_data = {
            'platformId': str(platform.id),
            'stats': stats_serializer.to_representation(channel_data),
            'barData': bar_serializer.to_representation(channel_data),
            'channelInfo': channel_info_serializer.to_representation(platform),
            'recentPosts': recent_posts_serializer.to_representation(channel_data),
            'topPosts': top_posts_serializer.to_representation(channel_data),
        }
        
        return Response(response_data)


class PlatformFetchTasksView(APIView):
    """Get fetch tasks status"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        tasks = PlatformFetchTask.objects.filter(
            user=request.user
        ).order_by('-created_at')[:20]
        
        serializer = FetchTaskSerializer(tasks, many=True)
        return Response(serializer.data)


# Sentiment Analysis Views (reusing from your existing code)

class SentimentSearchTriggerView(APIView):
    """Trigger sentiment analysis for platform posts"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request, platform_id):
        platform = get_object_or_404(
            Platform,
            id=platform_id,
            user=request.user
        )
        
        # Get posts without sentiment (blank string). field is blankable, not nullable.
        posts = platform.posts.filter(sentiment_label="")[:50]  # type: ignore[attr-defined]
        
        if not posts.exists():
            return Response({
                "message": "No posts to analyze"
            })
        
        # Prepare posts for sentiment analysis
        posts_data = []
        for post in posts:
            posts_data.append({
                "id": str(post.id),
                "post_id": post.platform_post_id,
                "post_title": post.title,
                "post_text": post.content,
                "post_url": post.post_url,
                "platform": platform.name,
                "author": platform.channel_name,
                "published_at": post.published_at.isoformat(),
            })
        
        # Queue for sentiment analysis (using your existing Kafka producer)
        from sentiment.producers import add_to_sentiment_quene
        add_to_sentiment_quene(posts_data, keyword=platform.channel_name)
        
        return Response({
            "message": f"Sentiment analysis triggered for {posts.count()} posts"
        })


class ChannelsListView(APIView):
    """Get list of all channels for sidebar"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        platforms = Platform.objects.filter(
            user=request.user,
            is_active=True
        ).prefetch_related('stats', 'posts')
        
        channels_serializer = ChannelsListSerializer()
        channels_data = channels_serializer.to_representation({
            'platforms': platforms
        })
        
        return Response({
            "success": True,
            "channels": channels_data
        })