from django.urls import path
from . import views

urlpatterns = [
    # Platform CRUD
    path("create/", views.PlatformCreateView.as_view(), name="platform-create"),
    path("get/", views.PlatformListView.as_view(), name="platform-list"),
    path("channels/", views.ChannelsListView.as_view(), name="channels-list"),
    path("<uuid:pk>/", views.PlatformDetailView.as_view(), name="platform-detail"),
    path(
        "refresh/<uuid:platform_id>/",
        views.PlatformRefreshView.as_view(),
        name="platform-refresh",
    ),
    path("refresh/", views.PlatformRefreshView.as_view(), name="platform-refresh-all"),
    # Dashboard
    path(
        "dashboard/", views.PlatformDashboardView.as_view(), name="platform-dashboard"
    ),
    # Channel-specific data
    path(
        "<str:platform_name>/<path:channel_id>/",
        views.PlatformChannelDataView.as_view(),
        name="platform-channel",
    ),
    # Fetch tasks
    path("tasks/", views.PlatformFetchTasksView.as_view(), name="platform-tasks"),
    # Sentiment analysis triggers
    path(
        "<uuid:platform_id>/analyze-sentiment/",
        views.SentimentSearchTriggerView.as_view(),
        name="platform-analyze-sentiment",
    ),
]
