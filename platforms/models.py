from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class AddPlatform(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    PLATFORM_CHOICES = [
        ("youtube", "YouTube"),
        ("instagram", "Instagram"),
        ("facebook", "Facebook"),
        ("linkedin", "LinkedIn"),
        ("twitter", "Twitter (X)"),
    ]

    name = models.CharField(max_length=50, choices=PLATFORM_CHOICES)
    channel_url = models.URLField(max_length=255)
    channel_id = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - {self.channel_id}"