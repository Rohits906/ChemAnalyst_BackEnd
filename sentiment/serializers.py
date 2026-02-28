from rest_framework import serializers
from .models import User_Keyword, Sentiment


class UserKeywordSerializer(serializers.ModelSerializer):
    class Meta:
        model = User_Keyword
        fields = ['id', 'keyword', 'user', 'created_at']
        read_only_fields = ['id', 'user', 'created_at']


class UserSentimentSerializer(serializers.ModelSerializer):
    # Flatten Post fields into the response
    post_title = serializers.CharField(source="post.post_title", read_only=True)
    post_url = serializers.URLField(source="post.post_url", read_only=True)
    author = serializers.CharField(source="post.author_name", read_only=True)
    author_id = serializers.CharField(source='post.author_id', default='N/A')
    platform = serializers.CharField(source='post.platform', default='')
    post_text = serializers.CharField(source='post.post_text', default='')
    likes = serializers.IntegerField(source='post.likes', default=0)
    comments = serializers.IntegerField(source='post.comments', default=0)
    shares = serializers.IntegerField(source='post.shares', default=0)
    published_at = serializers.DateTimeField(source='post.published_at', default=None)
    platform_post_id = serializers.CharField(source='post.platform_post_id', default='')
    latitude = serializers.FloatField(source='post.latitude', default=None, allow_null=True)
    longitude = serializers.FloatField(source='post.longitude', default=None, allow_null=True)
    location_name = serializers.CharField(source='post.location_name', default='', allow_null=True)
    location_type = serializers.CharField(source='post.location_type', default='city')

    class Meta:
        model = Sentiment
        fields = [
            'id',
            'keyword',
            'sentiment_label',
            'confidence_score',
            'model_used',
            'analyzed_at',
            'post_title',
            'post_url',
            'post_text',
            'author',
            'author_id',
            'platform',
            'platform_post_id',
            'likes',
            'comments',
            'shares',
            'published_at',
            'latitude',
            'longitude',
            'location_name',
            'location_type',
        ]
