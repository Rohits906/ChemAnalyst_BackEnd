import requests
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
    ChannelRecentPostsSerializer, ChannelTopPostsSerializer
)
from .producers import queue_platform_fetch, queue_batch_platform_fetch
from .platform_services import PlatformServiceFactory


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
                    "data": PlatformSerializer(existing).data
                }, status=status.HTTP_200_OK)
            else:
                # Reactivate
                existing.is_active = True
                existing.save()
                queue_platform_fetch(existing.id, "initial")
                return Response({
                    "message": "Platform reactivated successfully",
                    "data": PlatformSerializer(existing).data
                })
        
        # Create new platform
        platform = Platform.objects.create(
            user=request.user,
            name=data['name'],
            channel_id=data['channel_id'],
            channel_url=data['channel_url'],
            channel_name=data['channel_id'],  # Will be updated by fetch task
            metadata={}
        )
        
        # Queue initial fetch
        queue_platform_fetch(platform.id, "initial")
        
        return Response({
            "message": "Platform added successfully. Fetching data...",
            "data": PlatformSerializer(platform).data
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
        
        response_data = {
            'barData': BarChartDataSerializer(dashboard_data).data,
            'stats': DashboardStatsSerializer(dashboard_data).data['stats'],
            'topFive': TopLiveDataSerializer({
                'platforms': platforms,
                'limit': 5
            }).data,
            'recentProfilePosts': RecentProfilePostsSerializer({
                'platforms': platforms,
                'limit': 5
            }).data
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
        
        response_data = {
            'stats': ChannelStatsSummarySerializer(channel_data).data,
            'barData': ChannelBarDataSerializer(channel_data).data,
            'channelInfo': ChannelInfoSerializer(platform).data,
            'recentPosts': ChannelRecentPostsSerializer(channel_data).data,
            'topPosts': ChannelTopPostsSerializer(channel_data).data,
            'comparisons': [
                {'label': 'Engagement', 'value': '+12.5%', 'trend': 'up'},
                {'label': 'Reach', 'value': '+8.3%', 'trend': 'up'},
                {'label': 'New Followers', 'value': '-2.1%', 'trend': 'down'},
            ]
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