from django.db import models


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


class DBSaveQueue(models.Model):
    post_id = models.CharField(max_length=255, unique=True, help_text="Unique Identifier for the Post")
    post_url = models.URLField(max_length=500, null=True, blank=True, help_text="URL of the post")
    post_text = models.TextField(help_text="Mapped from post_caption or description")
    sentiment_label = models.CharField(max_length=50, null=True, blank=True)
    author_name = models.CharField(max_length=255, null=True, blank=True)
    author_id = models.CharField(max_length=255, null=True, blank=True)
    confidence_score = models.FloatField(null=True, blank=True)
    model_used = models.CharField(max_length=100, null=True, blank=True)
    analyzed_at = models.DateTimeField(null=True, blank=True)
    raw_json = models.JSONField(null=True, blank=True, help_text="The raw incoming JSON document")
    
    # Optional metadata for tracking when it was saved to DB
    saved_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Post: {self.post_id} by {self.author_name}"