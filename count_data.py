import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from sentiment.models import Post, Sentiment
from django.db.models import Count

post_counts = Post.objects.values('platform').annotate(count=Count('id'))
sentiment_counts = Sentiment.objects.values('post__platform').annotate(count=Count('id'))

with open("data_counts.txt", "w", encoding="utf-8") as f:
    f.write("--- POST COUNTS ---\n")
    for pc in post_counts:
        f.write(f"{pc['platform']}: {pc['count']}\n")
    
    f.write("\n--- SENTIMENT COUNTS ---\n")
    for sc in sentiment_counts:
        f.write(f"{sc['post__platform']}: {sc['count']}\n")

print("Counts written to data_counts.txt")
