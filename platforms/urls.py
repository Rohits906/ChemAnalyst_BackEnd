from django.urls import path
from . import views

urlpatterns = [
    # OAuth endpoints - MUST come before generic patterns
    path('oauth/initiate/<str:platform>/', views.OAuthInitiateView.as_view(), name='platform-oauth-init'),
    path('oauth/callback/<str:platform>/', views.OAuthCallbackView.as_view(), name='platform-oauth-callback'),
    
    # Twitter-specific OAuth endpoints
    path('oauth/initiate/twitter/', views.TwitterOAuthInitiateView.as_view(), name='twitter-oauth-init'),
    path('oauth/callback/twitter/', views.TwitterOAuthCallbackView.as_view(), name='twitter-oauth-callback'),
    
    # System connect for Meta - MUST come before generic patterns
    path('system-connect/<str:platform>/', views.SystemMetaConnectView.as_view(), name='platform-system-connect'),
    
    # System Twitter connect
    path('system-connect/twitter/', views.SystemTwitterConnectView.as_view(), name='twitter-system-connect'),
    
    # Platform CRUD
    path('create/', views.PlatformCreateView.as_view(), name='platform-create'),
    path('get/', views.PlatformListView.as_view(), name='platform-list'),
    path('channels/', views.ChannelsListView.as_view(), name='channels-list'),
    path('refresh/<uuid:platform_id>/', views.PlatformRefreshView.as_view(), name='platform-refresh'),
    path('refresh/', views.PlatformRefreshView.as_view(), name='platform-refresh-all'),
    
    # Dashboard
    path('dashboard/', views.PlatformDashboardView.as_view(), name='platform-dashboard'),
    
    # Fetch tasks
    path('tasks/', views.PlatformFetchTasksView.as_view(), name='platform-tasks'),
    
    # Channel-specific data - MUST come after specific patterns
    path('<str:platform_name>/<path:channel_id>/', 
         views.PlatformChannelDataView.as_view(), 
         name='platform-channel'),
    
    # Platform detail - MUST come last (catches UUIDs)
    path('<uuid:pk>/', views.PlatformDetailView.as_view(), name='platform-detail'),
    
    # Sentiment analysis triggers
    path('<uuid:platform_id>/analyze-sentiment/', 
         views.SentimentSearchTriggerView.as_view(), 
         name='platform-analyze-sentiment'),
]

