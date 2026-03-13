from django.db import models
import uuid
from django.contrib.auth.models import User


class SentimentPlatform(models.Model):
    PLATFORM_CHOICES = [
        ("youtube", "YouTube"),
        ("instagram", "Instagram"),
        ("facebook", "Facebook"),
        ("linkedin", "LinkedIn"),
        ("twitter", "Twitter"),
    ]

    name = models.CharField(max_length=50, choices=PLATFORM_CHOICES)
    channel_id = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - {self.channel_id}"


class SentimentPost(models.Model):
    SENTIMENT_CHOICES = [
        ("positive", "Positive"),
        ("negative", "Negative"),
    ]

    platform = models.ForeignKey(
        SentimentPlatform, on_delete=models.CASCADE, related_name="posts"
    )
    content = models.TextField()
    keyword = models.CharField(max_length=255, default="N/A")
    sentiment = models.CharField(max_length=20, choices=SENTIMENT_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.platform.name} - {self.sentiment}"


class User_Keyword(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    keyword = models.CharField(max_length=255)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="keywords")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.keyword} ({self.user.username})"


class Post(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    platform = models.CharField(max_length=100)
    platform_post_id = models.CharField(max_length=255)
    author_name = models.CharField(max_length=255, default="N/A")
    author_id = models.CharField(max_length=255, default="N/A")
    post_title = models.CharField(max_length=255, default="")
    post_text = models.TextField()
    post_url = models.URLField(max_length=500, default="https://example.com")
    published_at = models.DateTimeField()
    likes = models.IntegerField(default=0)
    comments = models.IntegerField(default=0)
    shares = models.IntegerField(default=0)
    raw_json = models.JSONField(default=dict)

    # Location fields
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    location_name = models.CharField(max_length=255, null=True, blank=True, default="")
    location_type = models.CharField(max_length=50, default="city")  # country, state, or city

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("platform", "platform_post_id")
        indexes = [
            models.Index(fields=["platform"]),
            models.Index(fields=["published_at"]),
        ]

    def __str__(self):
        return f"{self.platform} - {self.platform_post_id}"


class Sentiment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="sentiments")
    keyword = models.CharField(max_length=255, default="N/A")
    sentiment_label = models.CharField(max_length=50)
    confidence_score = models.FloatField()
    model_used = models.CharField(max_length=255)
    analyzed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("post", "keyword")
        indexes = [
            models.Index(fields=["sentiment_label"]),
            models.Index(fields=["analyzed_at"]),
        ]

    def __str__(self):
        return f"{self.sentiment_label} ({self.confidence_score})"