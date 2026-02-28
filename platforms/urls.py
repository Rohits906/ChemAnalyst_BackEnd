from django.urls import path
from .views import PlatformListCreateView, PlatformDeleteView

urlpatterns = [
    path("platforms/", PlatformListCreateView.as_view(), name="platform-list-create"),  # Will probably just use /api/platforms/ inside main urls.py wait...
    path("create/", PlatformListCreateView.as_view(), name="create-platform"), # Keep old for compat if it was mapped via /platforms/create/
    path("get/", PlatformListCreateView.as_view(), name="get-platform"), # Keep old for compat if it was mapped via /platforms/get/
    path("delete/<int:pk>/", PlatformDeleteView.as_view(), name="delete-platform"),
]