
import os
import django
import json

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from sentiment.views import SocialMediaSearchView
from django.contrib.auth.models import User

def test():
    user = User.objects.first()
    view = SocialMediaSearchView()
    print("--- Starting Test Search ---")
    try:
        # We use a keyword that likely has data
        keyword = "Stock"
        print(f"Testing keyword: {keyword}")
        counts = view.perform_search(keyword, hours="24", user=user)
        print(f"Search counts: {json.dumps(counts, indent=2)}")
    except Exception as e:
        print(f"Error during search: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test()
