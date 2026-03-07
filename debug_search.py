import os
import django
import json
import sys

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.append(os.getcwd())
django.setup()

from sentiment.models import Sentiment, Post, User_Keyword
from sentiment.views import SocialMediaSearchView

def debug_search(keyword):
    print(f"\n--- Debugging Search for: '{keyword}' ---")
    
    # Check if keyword exists for any user
    kws = User_Keyword.objects.filter(keyword__iexact=keyword)
    print(f"User_Keyword entries found: {kws.count()}")
    for kw_obj in kws:
        print(f"  User: {kw_obj.user.username}, Created: {kw_obj.created_at}")

    # Check for sentiments
    sentiments = Sentiment.objects.filter(keyword__iexact=keyword)
    print(f"Sentiments in DB: {sentiments.count()}")
    
    # Check for posts with similar keywords (case-insensitive)
    all_kws = Sentiment.objects.values_list('keyword', flat=True).distinct()
    print(f"Available keywords in Sentiment table: {list(all_kws)}")

    search_view = SocialMediaSearchView()
    
    # Dry run fetchers
    try:
        print("Testing YouTube...")
        yt = search_view._fetch_youtube(keyword)
        print(f"YouTube count: {len(yt)}")
    except Exception as e:
        print(f"YouTube error: {e}")
    
    try:
        print("Testing Twitter...")
        tw = search_view._fetch_twitter(keyword)
        print(f"Twitter count: {len(tw)}")
    except Exception as e:
        print(f"Twitter error: {e}")

if __name__ == "__main__":
    kw = sys.argv[1] if len(sys.argv) > 1 else "lucknow murdar case"
    debug_search(kw)
