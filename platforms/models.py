from django.db import models
import uuid
from django.contrib.auth.models import User
from django.utils import timezone
import json
from datetime import timedelta


class UserSocialAccount(models.Model):
    """Stores each user's connected social media accounts with OAuth tokens"""
    PLATFORM_CHOICES = [
        ("facebook", "Facebook"),
        ("instagram", "Instagram"),
        ("twitter", "Twitter"),
        ("youtube", "YouTube"),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="social_accounts")
    platform = models.CharField(max_length=50, choices=PLATFORM_CHOICES)
    
    # OAuth tokens (stored in metadata for security)
    access_token = models.TextField()  # Encrypted in metadata
    refresh_token = models.TextField(blank=True, null=True)  # Optional
    token_expiry = models.DateTimeField()
    is_token_valid = models.BooleanField(default=True)
    
    # Account details
    account_id = models.CharField(max_length=255)
    account_name = models.CharField(max_length=255)
    account_email = models.CharField(max_length=255, blank=True)
    profile_picture_url = models.URLField(blank=True)
    
    # Permission tracking
    scopes = models.JSONField(default=list)  # Granted scopes/permissions
    
    # Usage tracking (free tier limits)
    api_calls_made = models.IntegerField(default=0)
    api_calls_limit = models.IntegerField(default=1000)  # Free tier: 1000/month
    last_reset_date = models.DateTimeField(auto_now_add=True)
    
    # Timestamps
    connected_at = models.DateTimeField(auto_now_add=True)
    last_synced = models.DateTimeField(null=True, blank=True)
    last_token_refreshed = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        unique_together = ('user', 'platform', 'account_id')
        indexes = [
            models.Index(fields=['user', 'platform']),
            models.Index(fields=['token_expiry']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.platform} ({self.account_name})"
    
    def is_token_expired(self):
        """Check if token is expired"""
        return timezone.now() >= self.token_expiry
    
    def days_until_expiry(self):
        """Return days remaining before token expires"""
        if self.is_token_expired():
            return 0
        delta = self.token_expiry - timezone.now()
        return delta.days
    
    def api_quota_exceeded(self):
        """Check if API quota exceeded"""
        return self.api_calls_made >= self.api_calls_limit
    
    def get_usage_percentage(self):
        """Get API usage as percentage"""
        return (self.api_calls_made / self.api_calls_limit) * 100 if self.api_calls_limit > 0 else 0

class Platform(models.Model):
    PLATFORM_CHOICES = [
        ("youtube", "YouTube"),
        ("instagram", "Instagram"),
        ("facebook", "Facebook"),
        ("linkedin", "LinkedIn"),
        ("twitter", "Twitter"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=50, choices=PLATFORM_CHOICES)
    channel_id = models.CharField(max_length=255)
    channel_name = models.CharField(max_length=255)
    channel_url = models.URLField(max_length=500)
    profile_picture = models.URLField(max_length=500, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="platforms")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    
    # Platform-specific metadata
    metadata = models.JSONField(default=dict)

    class Meta:
        unique_together = ("user", "name", "channel_id")
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["name"]),
        ]

    def __str__(self):
        return f"{self.name} - {self.channel_name or self.channel_id}"


class ChannelStats(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    platform = models.ForeignKey(Platform, on_delete=models.CASCADE, related_name="stats")
    
    # Core metrics
    followers = models.BigIntegerField(default=0)
    following = models.BigIntegerField(default=0)
    posts_count = models.IntegerField(default=0)
    total_likes = models.BigIntegerField(default=0)
    total_comments = models.BigIntegerField(default=0)
    total_shares = models.BigIntegerField(default=0)
    engagement_rate = models.FloatField(default=0.0)
    
    # Platform-specific metrics
    views = models.BigIntegerField(default=0)  # YouTube
    subscribers = models.BigIntegerField(default=0)  # YouTube
    impressions = models.BigIntegerField(default=0)  # Twitter/LinkedIn
    
    # Time period
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    
    # Metadata
    collected_at = models.DateTimeField(auto_now_add=True)
    raw_data = models.JSONField(default=dict)

    class Meta:
        indexes = [
            models.Index(fields=["platform", "period_start"]),
            models.Index(fields=["platform", "period_end"]),
        ]
        ordering = ["-period_end"]

    def __str__(self):
        return f"{self.platform.channel_name} - {self.period_start.date()}"


class ChannelPost(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    platform = models.ForeignKey(Platform, on_delete=models.CASCADE, related_name="posts")
    
    # Post data
    platform_post_id = models.CharField(max_length=255)
    title = models.CharField(max_length=500, blank=True)
    content = models.TextField(blank=True)
    post_url = models.URLField(max_length=500)
    
    # Media
    media_urls = models.JSONField(default=list)  # Array of media URLs
    media_type = models.CharField(max_length=50, blank=True)  # image, video, carousel
    
    # Engagement
    likes = models.IntegerField(default=0)
    comments = models.IntegerField(default=0)
    shares = models.IntegerField(default=0)
    views = models.IntegerField(default=0)
    
    # Metadata
    published_at = models.DateTimeField()
    collected_at = models.DateTimeField(auto_now_add=True)
    
    # Sentiment (if analyzed)
    sentiment_label = models.CharField(max_length=20, blank=True)
    sentiment_score = models.FloatField(null=True, blank=True)
    
    # Raw data
    raw_data = models.JSONField(default=dict)

    class Meta:
        unique_together = ("platform", "platform_post_id")
        indexes = [
            models.Index(fields=["platform", "published_at"]),
            models.Index(fields=["sentiment_label"]),
        ]
        ordering = ["-published_at"]

    def __str__(self):
        return f"{self.title[:50]}..."


class PlatformFetchTask(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    platform = models.ForeignKey(Platform, on_delete=models.CASCADE, related_name="fetch_tasks")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    
    # Task details
    task_type = models.CharField(max_length=50)  # "initial", "update", "historical"
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    
    # Progress tracking
    total_items = models.IntegerField(default=0)
    processed_items = models.IntegerField(default=0)
    
    # Results
    stats_collected = models.JSONField(default=dict)
    posts_collected = models.IntegerField(default=0)
    error_message = models.TextField(blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.platform.name} - {self.task_type} - {self.status}"