import os
import django
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.append(os.getcwd())
django.setup()

from sentiment.models import Post, Sentiment, User_Keyword

print(f"Before deletion:")
print(f"  Sentiments: {Sentiment.objects.count()}")
print(f"  Posts: {Post.objects.count()}")
print(f"  Keywords: {User_Keyword.objects.count()}")

# Delete in correct order (FK constraints)
s_deleted = Sentiment.objects.all().delete()
p_deleted = Post.objects.all().delete()
k_deleted = User_Keyword.objects.all().delete()

print(f"\nAfter deletion:")
print(f"  Sentiments: {Sentiment.objects.count()}")
print(f"  Posts: {Post.objects.count()}")
print(f"  Keywords: {User_Keyword.objects.count()}")
print("\nAll old data cleared successfully! ✅")
