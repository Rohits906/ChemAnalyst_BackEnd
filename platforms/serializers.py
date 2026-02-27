from rest_framework import serializers
from .models import Platform, ChannelStats, ChannelPost, PlatformFetchTask
from django.utils import timezone

class PlatformSerializer(serializers.ModelSerializer):
    class Meta:
        model = Platform
        fields = [
            'id', 'name', 'channel_id', 'channel_name', 
            'channel_url', 'profile_picture', 'created_at',
            'updated_at', 'is_active', 'metadata'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class PlatformCreateSerializer(serializers.Serializer):
    name = serializers.ChoiceField(choices=[
        "youtube", "instagram", "facebook", "linkedin", "twitter"
    ])
    channel_url = serializers.URLField()
    channel_id = serializers.CharField(max_length=255)


class ChannelStatsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChannelStats
        fields = '__all__'
        read_only_fields = ['id', 'collected_at']


class ChannelPostSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChannelPost
        fields = '__all__'
        read_only_fields = ['id', 'collected_at']


class DashboardStatsSerializer(serializers.Serializer):
    """Serializer for main platforms dashboard"""
    
    def to_representation(self, instance):
        # Aggregate stats for dashboard
        platforms = instance.get('platforms', [])
        user = instance.get('user')
        
        # Calculate total stats
        total_posts = 0
        total_likes = 0
        total_comments = 0
        total_followers = 0
        
        for platform in platforms:
            latest_stats = platform.stats.first()
            if latest_stats:
                total_posts += latest_stats.posts_count
                total_likes += latest_stats.total_likes
                total_comments += latest_stats.total_comments
                total_followers += latest_stats.followers
        
        return {
            'stats': [
                {'label': 'Post', 'value': str(total_posts)},
                {'label': 'Following', 'value': '0'},  # Can be calculated if needed
                {'label': 'Followers', 'value': str(total_followers)},
                {'label': 'Likes', 'value': str(total_likes)},
                {'label': 'Comment', 'value': str(total_comments)},
            ]
        }


class BarChartDataSerializer(serializers.Serializer):
    """Serializer for platform-wise sentiment data"""
    
    def to_representation(self, instance):
        platforms = instance.get('platforms', [])
        date_range = instance.get('date_range', {})
        
        bar_data = []
        for platform in platforms:
            # Get posts with sentiment for this platform
            posts = platform.posts.filter(
                published_at__date__gte=date_range.get('start'),
                published_at__date__lte=date_range.get('end')
            ) if date_range else platform.posts.all()
            
            positive_count = posts.filter(sentiment_label='positive').count()
            negative_count = posts.filter(sentiment_label='negative').count()
            
            bar_data.append({
                'name': platform.name.title(),
                'pos': positive_count,
                'neg': negative_count,
            })
        
        return bar_data


class TopLiveDataSerializer(serializers.Serializer):
    """Serializer for top performing posts"""
    
    def to_representation(self, instance):
        platforms = instance.get('platforms', [])
        limit = instance.get('limit', 5)
        
        all_posts = []
        for platform in platforms:
            posts = platform.posts.all()[:limit]
            for post in posts:
                all_posts.append({
                    'id': str(post.id),
                    'link': post.post_url,
                    'platform': platform.name.title(),
                    'like': post.likes,
                    'comment': post.comments,
                })
        
        # Sort by engagement and return top
        all_posts.sort(key=lambda x: x['like'] + x['comment'], reverse=True)
        return all_posts[:limit]


class RecentProfilePostsSerializer(serializers.Serializer):
    """Serializer for recent posts with sentiment"""
    
    def to_representation(self, instance):
        platforms = instance.get('platforms', [])
        limit = instance.get('limit', 5)
        
        recent_posts = []
        for platform in platforms:
            posts = platform.posts.filter(
                sentiment_label__isnull=False
            ).order_by('-published_at')[:limit]
            
            for post in posts:
                recent_posts.append({
                    'id': str(post.id),
                    'title': post.title[:50] + '...' if len(post.title) > 50 else post.title,
                    'sentiment': post.sentiment_label.title() if post.sentiment_label else 'Unknown',
                })
        
        # Sort by published date
        return recent_posts[:limit]


# Channel Page Serializers

class ChannelInfoSerializer(serializers.Serializer):
    """Serializer for channel information"""
    
    def to_representation(self, instance):
        platform = instance
        return {
            'channelId': platform.channel_id,
            'channelName': platform.channel_name,
            'joined': platform.created_at.strftime('%Y-%m-%d'),
            'followers': platform.stats.first().followers if platform.stats.exists() else 0,
            'posts': platform.stats.first().posts_count if platform.stats.exists() else 0,
            'engagement': platform.stats.first().engagement_rate if platform.stats.exists() else 0,
        }


class ChannelStatsSummarySerializer(serializers.Serializer):
    """Serializer for channel stats summary cards"""
    
    def to_representation(self, instance):
        platform = instance.get('platform')
        stats = platform.stats.first()
        
        if not stats:
            return []
        
        # Map metrics based on platform type
        metrics_map = {
            'youtube': [
                {'label': 'Subscribers', 'value': stats.subscribers, 'change': 5.2},
                {'label': 'Views', 'value': stats.views, 'change': 3.1},
                {'label': 'Videos', 'value': stats.posts_count, 'change': 1.5},
                {'label': 'Watch Time', 'value': stats.views, 'change': 2.3},
            ],
            'instagram': [
                {'label': 'Followers', 'value': stats.followers, 'change': 4.8},
                {'label': 'Posts', 'value': stats.posts_count, 'change': 2.1},
                {'label': 'Reach', 'value': stats.impressions, 'change': 6.3},
                {'label': 'Stories', 'value': stats.posts_count, 'change': 1.7},
            ],
            'twitter': [
                {'label': 'Followers', 'value': stats.followers, 'change': 3.5},
                {'label': 'Tweets', 'value': stats.posts_count, 'change': 1.2},
                {'label': 'Impressions', 'value': stats.impressions, 'change': 5.6},
                {'label': 'Retweets', 'value': stats.shares, 'change': 2.8},
            ],
            'linkedin': [
                {'label': 'Connections', 'value': stats.followers, 'change': 2.9},
                {'label': 'Posts', 'value': stats.posts_count, 'change': 1.8},
                {'label': 'Impressions', 'value': stats.impressions, 'change': 4.2},
                {'label': 'Reactions', 'value': stats.total_likes, 'change': 3.3},
            ],
            'facebook': [
                {'label': 'Followers', 'value': stats.followers, 'change': 3.7},
                {'label': 'Posts', 'value': stats.posts_count, 'change': 2.4},
                {'label': 'Reach', 'value': stats.impressions, 'change': 5.1},
                {'label': 'Engagement', 'value': stats.engagement_rate, 'change': 1.9},
            ],
        }
        
        return metrics_map.get(platform.name, [])


class ChannelBarDataSerializer(serializers.Serializer):
    """Serializer for channel engagement bar chart"""
    
    def to_representation(self, instance):
        platform = instance.get('platform')
        posts = instance.get('posts', [])
        
        # Group by date and calculate positive/negative
        # This is a simplified version - you might want more sophisticated aggregation
        bar_data = []
        
        # For demo, create weekly data points
        for i in range(7):
            bar_data.append({
                'name': f'Day {i+1}',
                'pos': 5 + i,
                'neg': 3 + i//2,
            })
        
        return bar_data


class ChannelRecentPostsSerializer(serializers.Serializer):
    """Serializer for channel's recent posts"""
    
    def to_representation(self, instance):
        platform = instance.get('platform')
        limit = instance.get('limit', 10)
        
        posts = platform.posts.all()[:limit]
        
        return [{
            'id': str(post.id),
            'title': post.title,
            'date': post.published_at.strftime('%Y-%m-%d'),
            'likes': post.likes,
            'comments': post.comments,
            'sentiment': post.sentiment_label.title() if post.sentiment_label else 'Neutral',
        } for post in posts]


class ChannelTopPostsSerializer(serializers.Serializer):
    """Serializer for channel's top performing posts"""
    
    def to_representation(self, instance):
        platform = instance.get('platform')
        limit = instance.get('limit', 5)
        
        # Get posts sorted by engagement
        posts = platform.posts.all().order_by('-likes', '-comments')[:limit]
        
        return [{
            'title': post.title,
            'likes': post.likes,
            'comments': post.comments,
            'shares': post.shares,
            'growth': 12 + i * 3,  # Calculate actual growth
        } for i, post in enumerate(posts)]


class FetchTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformFetchTask
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'started_at', 'completed_at']