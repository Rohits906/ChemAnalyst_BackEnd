import os, django, sys
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.append(os.getcwd())
django.setup()

from sentiment.models import Post
from django.utils import timezone

print(f"Current server time: {timezone.now()}")
print(f"\nAll posts with published_at:")
for p in Post.objects.all().order_by('-published_at')[:10]:
    print(f"  [{p.platform}] published_at={p.published_at}  title={p.post_title[:40]}")
