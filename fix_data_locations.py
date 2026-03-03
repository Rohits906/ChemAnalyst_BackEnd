import os
import django
import sys

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.append(os.getcwd())
django.setup()

from sentiment.models import Post
from sentiment.views import SocialMediaSearchView

def fix_old_data():
    sv = SocialMediaSearchView()
    posts = Post.objects.all()
    count = 0
    print(f"Checking {posts.count()} posts...")
    
    for post in posts:
        # Re-extract using the new logic
        # We need the keyword, which is in the Sentiment objects associated with this post
        sentiment = post.sentiments.first()
        if not sentiment:
            continue
            
        keyword = sentiment.keyword
        text = post.post_text
        
        # We pass post as post_metadata if we have extra_details
        # but the main logic works on text/keyword anyway
        name, lat, lng = sv._extract_location(text, keyword)
        
        if post.location_name != name or post.latitude != lat:
            print(f"Updating Post {post.id}: '{post.location_name}' -> '{name}'")
            post.location_name = name
            post.latitude = lat
            post.longitude = lng
            post.save()
            count += 1
            
    print(f"Successfully updated {count} posts.")

if __name__ == "__main__":
    fix_old_data()
