import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from sentiment.models import Post

yt_posts = Post.objects.filter(platform__iexact="youtube")
count = yt_posts.count()

with open("yt_check.txt", "w", encoding="utf-8") as f:
    f.write(f"YouTube posts count: {count}\n")
    if count > 0:
        f.write("Recent YouTube posts:\n")
        for p in yt_posts.order_by('-published_at')[:10]:
            f.write(f"- {p.post_title} | Date: {p.published_at} | ID: {p.platform_post_id}\n")
    else:
        f.write("No YouTube posts found in database.\n")
