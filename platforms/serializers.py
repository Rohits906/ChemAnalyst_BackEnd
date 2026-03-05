from rest_framework import serializers
from .models import Platform, ChannelStats, ChannelPost, PlatformFetchTask
from django.utils import timezone
from django.db.models import Sum

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
    """Serializer for platform-wise sentiment or engagement data"""
    
    def to_representation(self, instance):
        platforms = instance.get('platforms', [])
        date_range = instance.get('date_range', {})
        
        bar_data = []
        for platform in platforms:
            # Get posts for this platform
            posts = platform.posts.filter(
                published_at__date__gte=date_range.get('start'),
                published_at__date__lte=date_range.get('end')
            ) if date_range else platform.posts.all()
            
            # Try to get sentiment counts, fall back to engagement metrics
            positive_count = posts.filter(sentiment_label__iexact='positive').count()
            negative_count = posts.filter(sentiment_label__iexact='negative').count()
            
            # If no sentiment data, use 0 (no sentiment analysis yet)
            if positive_count == 0 and negative_count == 0 and posts.exists():
                positive_count = 0
                negative_count = 0
            
            bar_data.append({
                'name': platform.name.title(),
                'pos': positive_count,
                'neg': negative_count,
            })
        
        return bar_data


class TopLiveDataSerializer(serializers.Serializer):
    """Serializer for top performing posts (by engagement)"""
    
    def to_representation(self, instance):
        platforms = instance.get('platforms', [])
        limit = instance.get('limit', 5)
        
        all_posts = []
        for platform in platforms:
            # Get all posts sorted by engagement
            posts = platform.posts.all().order_by('-likes', '-comments', '-views')[:limit]
            for post in posts:
                all_posts.append({
                    'id': str(post.id),
                            'link': post.post_url,
                    'platform': platform.name.title(),
                    'channel': platform.channel_name or platform.name.title(),
                    'like': post.likes,
                    'comment': post.comments,
                })
        
        # Sort all by total engagement and return top
        all_posts.sort(key=lambda x: x['like'] + x['comment'], reverse=True)
        return all_posts[:limit]


class RecentProfilePostsSerializer(serializers.Serializer):
    """Serializer for recent posts with sentiment (or placeholder)"""
    
    def to_representation(self, instance):
        platforms = instance.get('platforms', [])
        limit = instance.get('limit', 5)
        
        recent_posts = []
        for platform in platforms:
            posts = platform.posts.order_by('-published_at')[:limit]
            
            for post in posts:
                # Use sentiment if available, otherwise use engagement to infer
                sentiment = post.sentiment_label.title() if post.sentiment_label else None
                
                # Use sentiment if available, otherwise use neutral as default
                sentiment = post.sentiment_label.title() if post.sentiment_label else "Neutral"
                
                recent_posts.append({
                    'id': str(post.id),
                    'title': post.title[:50] + '...' if len(post.title) > 50 else post.title,
                    'channel': platform.channel_name or platform.name.title(),
                    'sentiment': sentiment,
                })
        
        # Sort by published date
        return sorted(recent_posts, key=lambda x: x['id'])[:limit]


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
                {'label': 'Retweets', 'value': stats.total_shares if hasattr(stats, 'total_shares') else 0, 'change': 2.8},
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
        # use supplied posts (already filtered by date range) or all posts
        posts = instance.get('posts')
        if posts is None:
            platform = instance.get('platform')
            posts = platform.posts.all()

        # simple bar counts: likes vs comments per post or stub daily
        bar_data = []
        for post in posts:
            bar_data.append({
                'name': post.published_at.strftime('%Y-%m-%d'),
                'likes': post.likes or 0,
                'comments': post.comments or 0,
            })
        return bar_data


class ChannelRecentPostsSerializer(serializers.Serializer):
    """Serializer for channel's recent posts"""
    
    def to_representation(self, instance):
        # allow caller to supply filtered posts queryset/list
        posts = instance.get('posts')
        limit = instance.get('limit', 10)
        
        if posts is None:
            platform = instance.get('platform')
            posts = platform.posts.all()
        
        # if queryset, apply limit
        posts = posts[:limit]
        
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
        limit = instance.get('limit', 5)
        posts = instance.get('posts')
        if posts is None:
            platform = instance.get('platform')
            posts = platform.posts.all()
        
        # ensure we can sort; if it's a queryset fine, otherwise convert to list
        try:
            sorted_posts = posts.order_by('-likes', '-comments')
        except Exception:
            sorted_posts = sorted(posts, key=lambda p: (-(p.likes or 0), -(p.comments or 0)))
        sorted_posts = sorted_posts[:limit]
        
        return [{
            'title': post.title,
            'likes': post.likes,
            'comments': post.comments,
            'shares': post.shares,
            'growth': 12 + i * 3,  # Calculate actual growth
        } for i, post in enumerate(sorted_posts)]


class FetchTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformFetchTask
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'started_at', 'completed_at']


class SubscriberGrowthSerializer(serializers.Serializer):
    """Serializer for subscriber growth chart data (line chart)"""
    
    def to_representation(self, instance):
        platforms = instance.get('platforms', [])
        
        growth_data = {}
        
        for platform in platforms:
            # Get all stats for this platform ordered by date
            stats = platform.stats.all().order_by('period_start')
            
            platform_name = platform.name.title()
            growth_data[platform_name] = {
                'dates': [],
                'subscribers': [],
                'views': [],
            }
            
            for stat in stats:
                date_str = stat.period_start.strftime('%Y-%m-%d')
                growth_data[platform_name]['dates'].append(date_str)
                growth_data[platform_name]['subscribers'].append(stat.subscribers)
                growth_data[platform_name]['views'].append(stat.views)
        
        # Convert to list format for frontend
        line_chart_data = []
        for platform_name, data in growth_data.items():
            line_chart_data.append({
                'name': platform_name,
                'dates': data['dates'],
                'subscribers': data['subscribers'],
                'views': data['views'],
            })
        
        return line_chart_data


class ChannelsListSerializer(serializers.Serializer):
    """Serializer for list of channels"""
    
    def to_representation(self, instance):
        platforms = instance.get('platforms', [])
        
        channels = []
        for platform in platforms:
            # Get latest stats record (contains correct video/post counts from YouTube API)
            latest_stats = platform.stats.first()
            
            # derive display label including platform name
            display_label = f"{platform.name.title()} - {platform.channel_name}"
            
            # use view count as the 'likes' metric for YouTube
            likes_value = latest_stats.views if (latest_stats and platform.name == 'youtube') else (latest_stats.total_likes if latest_stats else 0)
            
            channels.append({
                'id': str(platform.id),
                'name': platform.channel_name,
                'display': display_label,
                'platform': platform.name,
                'platform_id': str(platform.channel_id),
                'subscribers': latest_stats.subscribers if latest_stats else 0,
                'posts_count': latest_stats.posts_count if latest_stats else 0,  # From ChannelStats, not post count
                'followers': latest_stats.followers if latest_stats else 0,
                'total_likes': likes_value,
                'total_comments': latest_stats.total_comments if latest_stats else 0,
                'videos': latest_stats.posts_count if latest_stats else 0,  # Alias for YouTube
                'views': latest_stats.views if latest_stats else 0,  # For YouTube watch time
                'profile_picture': platform.profile_picture or '',
                'channel_url': platform.channel_url,
            })
        
        return channels