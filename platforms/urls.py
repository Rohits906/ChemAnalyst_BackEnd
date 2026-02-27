from django.urls import path
from .views import PlatformListCreateView, PlatformDeleteView
from . import views

urlpatterns = [
    path(
        "platforms/", PlatformListCreateView.as_view(), name="platform-list-create"
    ),  # Will probably just use /api/platforms/ inside main urls.py wait...
    path(
        "create/", PlatformListCreateView.as_view(), name="create-platform"
    ),  # Keep old for compat if it was mapped via /platforms/create/
    path(
        "get/", PlatformListCreateView.as_view(), name="get-platform"
    ),  # Keep old for compat if it was mapped via /platforms/get/
    path("delete/<int:pk>/", PlatformDeleteView.as_view(), name="delete-platform"),
    path("create/", views.PlatformCreateView.as_view(), name="platform-create"),
    path("get/", views.PlatformListView.as_view(), name="platform-list"),
    path("<uuid:pk>/", views.PlatformDetailView.as_view(), name="platform-detail"),
    path(
        "refresh/<uuid:platform_id>/",
        views.PlatformRefreshView.as_view(),
        name="platform-refresh",
    ),
    path("refresh/", views.PlatformRefreshView.as_view(), name="platform-refresh-all"),
    path(
        "dashboard/", views.PlatformDashboardView.as_view(), name="platform-dashboard"
    ),
    path(
        "<str:platform_name>/<path:channel_id>/",
        views.PlatformChannelDataView.as_view(),
        name="platform-channel",
    ),
    path("tasks/", views.PlatformFetchTasksView.as_view(), name="platform-tasks"),
    path(
        "<uuid:platform_id>/analyze-sentiment/",
        views.SentimentSearchTriggerView.as_view(),
        name="platform-analyze-sentiment",
    ),
]
