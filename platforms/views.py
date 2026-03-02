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
from .youtube_service import fetch_youtube_channel_data
from .platform_services import PlatformServiceFactory

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
        if posts_data:
            for post_data in posts_data:
                ChannelPost.objects.update_or_create(
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
        
        return True, f"Platform data fetched successfully from {platform.name}"
        
    except Exception as e:
        logger.error(f"Error fetching data for {platform.name} - {platform.channel_id}: {str(e)}", exc_info=True)
        return False, f"Data fetch failed: {str(e)}"



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
                # Reactivate and fetch data
                existing.is_active = True
                existing.save()
                
                # Fetch data using the generalized method
                fetch_success, message = fetch_platform_data(existing)
                
                if not fetch_success:
                    # queue retry when reactivating as well
                    try:
                        queue_platform_fetch(existing.id, "reactivate")
                        message += "; fetch queued in background."
                    except Exception as qex:
                        logger.warning(f"Failed to queue background fetch for platform {existing.id}: {qex}")
                
                return Response({
                    "message": message if fetch_success else f"Platform reactivated but: {message}",
                    "data": PlatformSerializer(existing).data,
                    "fetch_success": fetch_success
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
        
        # Fetch data using the generalized method
        fetch_success, message = fetch_platform_data(platform)
        
        if not fetch_success:
            # Try to queue background fetch for retry
            try:
                queue_platform_fetch(platform.id, "initial")
                message += "; fetch queued for background processing."
            except Exception as qex:
                logger.warning(f"Failed to queue background fetch for platform {platform.id}: {qex}")
        
        return Response({
            "message": ("Platform added successfully and data fetched!" if fetch_success 
                       else f"Platform added. {message}"),
            "data": PlatformSerializer(platform).data,
            "fetch_success": fetch_success
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
        
        response_data = {
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
        
        # Get posts without sentiment
        posts = platform.posts.filter(
            sentiment_label__isnull=True
        )[:50]
        
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