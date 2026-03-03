import os
import django
import sys

# Setup Django environment
sys.path.append(r"d:\django_projects\chemanalyst_project\backend")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from authentication.models import Account

User = get_user_model()
user = User.objects.first()

if user:
    print(f"Testing with user: {user.username}")
    client = APIClient()
    client.force_authenticate(user=user)
    
    response = client.post('/api/auth/logout-all/')
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
else:
    print("No users found to test with.")
