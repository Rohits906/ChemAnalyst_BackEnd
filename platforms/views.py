import requests
import logging
from django.conf import settings
from django.db.models import Count, Q, Sum, Avg
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from datetime import datetime, timedelta

from .models import Platform, ChannelStats, ChannelPost, PlatformFetchTask
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
        
        data = serializer.validated_data
        
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
            name=data['name'],
            channel_id=data['channel_id'],
            channel_url=data['channel_url'],
            channel_name=data['channel_id'],  # Will be updated by fetch
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
        platform.is_active = False
        platform.save()
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

        response_data = {
            'barData': bar_chart_serializer.to_representation(dashboard_data),
            'lineChart': subscriber_growth_serializer.to_representation({
                'platforms': platforms
            }),
            'stats': dashboard_stats_serializer.to_representation(dashboard_data).get('stats', []),
            'topFive': top_by_channel,
            'recentProfilePosts': recent_by_channel,
        }
        
        return Response({
            "success": True,
            "data": response_data
        })

class OAuthInitiateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, platform):
        platform = platform.lower()
        supported = ["facebook", "instagram", "twitter", "linkedin"]
        if platform not in supported:
            return Response({"error": "Unsupported platform"}, status=status.HTTP_400_BAD_REQUEST)

        # build a callback URI using Django reverse
        from django.urls import reverse
        redirect_uri = request.build_absolute_uri(reverse('platform-oauth-callback', args=[platform]))

        # grab the raw JWT access token so that we can round-trip it via state
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        token_value = None
        if auth_header.startswith('Bearer '):
            token_value = auth_header.split(' ', 1)[1]

        auth_url = None
        state_param = ''
        if token_value:
            from urllib.parse import urlencode
            state_param = urlencode({'token': token_value})

        if platform == "facebook":
            client_id = settings.FACEBOOK_APP_ID
            auth_url = (
                f"https://www.facebook.com/v13.0/dialog/oauth?client_id={client_id}"
                f"&redirect_uri={redirect_uri}&scope=pages_show_list,instagram_basic"
            )
        elif platform == "instagram":
            client_id = settings.INSTAGRAM_CLIENT_ID
            auth_url = (
                f"https://api.instagram.com/oauth/authorize?client_id={client_id}"
                f"&redirect_uri={redirect_uri}&scope=user_profile,user_media&response_type=code"
            )
        elif platform == "twitter":
            auth_url = "https://api.twitter.com/oauth/authenticate?oauth_token=REQUEST_TOKEN"
        elif platform == "linkedin":
            client_id = settings.LINKEDIN_CLIENT_ID
            auth_url = (
                f"https://www.linkedin.com/oauth/v2/authorization?response_type=code"
                f"&client_id={client_id}&redirect_uri={redirect_uri}"
                f"&scope=r_liteprofile%20r_emailaddress%20w_member_social"
            )

        if auth_url and state_param:
            # append state to preserve token
            sep = '&' if '?' in auth_url else '?'
            auth_url = f"{auth_url}{sep}state={state_param}"

        return Response({"auth_url": auth_url})


class OAuthCallbackView(APIView):
    permission_classes = []  # handled manually below

    def get(self, request, platform):
        platform = platform.lower()
        code = request.GET.get('code') or request.GET.get('oauth_token')
        error = request.GET.get('error')
        frontend = settings.FRONTEND_URL.rstrip('/')

        # attempt to recover user from state token
        user = None
        state = request.GET.get('state')
        if state:
            from urllib.parse import parse_qs
            qs = parse_qs(state)
            token_list = qs.get('token')
            if token_list:
                raw_token = token_list[0]
                try:
                    from rest_framework_simplejwt.tokens import AccessToken
                    access = AccessToken(raw_token)
                    from django.contrib.auth import get_user_model
                    User = get_user_model()
                    user = User.objects.filter(id=access['user_id']).first()
                except Exception:
                    user = None

        if error or not code or not user:
            # redirect back to frontend with error indicator
            from django.http import HttpResponseRedirect
            redirect_url = f"{frontend}/dashboard/platforms?oauth_error=1&platform={platform}"
            return HttpResponseRedirect(redirect_url)

        # stub: create a dummy channel id using platform name + user id
        channel_id = f"{platform}_{user.id}"
        obj, created = Platform.objects.get_or_create(
            user=user,
            name=platform,
            channel_id=channel_id,
            defaults={
                'channel_url': '',
                'channel_name': channel_id,
                'metadata': {'oauth_code': code}
            }
        )
        if not created:
            obj.metadata['oauth_code'] = code
            obj.is_active = True
            obj.save()

        # kick off a fetch for the new platform via Kafka
        try:
            queue_platform_fetch(obj.id, 'initial')
        except Exception as qex:
            logger.warning(f"OAuth: Failed to queue background fetch: {qex}")

        from django.http import HttpResponseRedirect
        # send user to the platforms dashboard (adjust path depending on frontend routing)
        redirect_url = f"{frontend}/(dashboard)/platforms?oauth_success=1&platform={platform}"
        return HttpResponseRedirect(redirect_url)

class OAuthInitiateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, platform):
        platform = platform.lower()
        supported = ["facebook", "instagram", "twitter", "linkedin"]
        if platform not in supported:
            return Response({"error": "Unsupported platform"}, status=status.HTTP_400_BAD_REQUEST)

        # build a callback URI using Django reverse
        from django.urls import reverse
        redirect_uri = request.build_absolute_uri(reverse('platform-oauth-callback', args=[platform]))

        # grab the raw JWT access token so that we can round-trip it via state
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        token_value = None
        if auth_header.startswith('Bearer '):
            token_value = auth_header.split(' ', 1)[1]

        auth_url = None
        state_param = ''
        if token_value:
            from urllib.parse import urlencode
            state_param = urlencode({'token': token_value})

        if platform == "facebook":
            client_id = settings.FACEBOOK_APP_ID
            auth_url = (
                f"https://www.facebook.com/v13.0/dialog/oauth?client_id={client_id}"
                f"&redirect_uri={redirect_uri}&scope=pages_show_list,instagram_basic"
            )
        elif platform == "instagram":
            client_id = settings.INSTAGRAM_CLIENT_ID
            auth_url = (
                f"https://api.instagram.com/oauth/authorize?client_id={client_id}"
                f"&redirect_uri={redirect_uri}&scope=user_profile,user_media&response_type=code"
            )
        elif platform == "twitter":
            auth_url = "https://api.twitter.com/oauth/authenticate?oauth_token=REQUEST_TOKEN"
        elif platform == "linkedin":
            client_id = settings.LINKEDIN_CLIENT_ID
            auth_url = (
                f"https://www.linkedin.com/oauth/v2/authorization?response_type=code"
                f"&client_id={client_id}&redirect_uri={redirect_uri}"
                f"&scope=r_liteprofile%20r_emailaddress%20w_member_social"
            )

        if auth_url and state_param:
            # append state to preserve token
            sep = '&' if '?' in auth_url else '?'
            auth_url = f"{auth_url}{sep}state={state_param}"

        return Response({"auth_url": auth_url})


class OAuthCallbackView(APIView):
    permission_classes = []  # handled manually below

    def get(self, request, platform):
        platform = platform.lower()
        code = request.GET.get('code') or request.GET.get('oauth_token')
        error = request.GET.get('error')
        frontend = settings.FRONTEND_URL.rstrip('/')

        # attempt to recover user from state token
        user = None
        state = request.GET.get('state')
        if state:
            from urllib.parse import parse_qs
            qs = parse_qs(state)
            token_list = qs.get('token')
            if token_list:
                raw_token = token_list[0]
                try:
                    from rest_framework_simplejwt.tokens import AccessToken
                    access = AccessToken(raw_token)
                    from django.contrib.auth import get_user_model
                    User = get_user_model()
                    user = User.objects.filter(id=access['user_id']).first()
                except Exception:
                    user = None

        if error or not code or not user:
            # redirect back to frontend with error indicator
            from django.http import HttpResponseRedirect
            redirect_url = f"{frontend}/dashboard/platforms?oauth_error=1&platform={platform}"
            return HttpResponseRedirect(redirect_url)

        # stub: create a dummy channel id using platform name + user id
        channel_id = f"{platform}_{user.id}"
        obj, created = Platform.objects.get_or_create(
            user=user,
            name=platform,
            channel_id=channel_id,
            defaults={
                'channel_url': '',
                'channel_name': channel_id,
                'metadata': {'oauth_code': code}
            }
        )
        if not created:
            obj.metadata['oauth_code'] = code
            obj.is_active = True
            obj.save()

        # kick off a fetch for the new platform via Kafka
        try:
            queue_platform_fetch(obj.id, 'initial')
        except Exception as qex:
            logger.warning(f"OAuth: Failed to queue background fetch: {qex}")

        from django.http import HttpResponseRedirect
        # send user to the platforms dashboard (adjust path depending on frontend routing)
        redirect_url = f"{frontend}/(dashboard)/platforms?oauth_success=1&platform={platform}"
        return HttpResponseRedirect(redirect_url)


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
        posts = platform.posts.filter(
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
        posts = platform.posts.filter(sentiment_label="")[:50]
        
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
        from .producers import add_to_sentiment_quene
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