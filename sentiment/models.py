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


class SentimentPost(models.Model):
    SENTIMENT_CHOICES = [
        ("positive", "Positive"),
        ("negative", "Negative"),
    ]

    platform = models.ForeignKey(
        SentimentPlatform,
        on_delete=models.CASCADE,
        related_name="posts"
    )
    content = models.TextField()
    keyword = models.CharField(max_length=255, blank=True, null=True)
    sentiment = models.CharField(max_length=20, choices=SENTIMENT_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.platform.name} - {self.sentiment}"