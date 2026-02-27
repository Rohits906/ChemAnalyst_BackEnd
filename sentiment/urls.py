from django.urls import path
from .views import (
    sentiment_dashboard,
    publish_test_sentiment,
    SentimentDashboardView, 
    SocialMediaSearchView, 
    AddKeywordView, 
    UserSentimentView,
    UserKeywordSearchTriggerView
)

urlpatterns = [
    # Old endpoints (from HEAD)
    path("old-dashboard/", sentiment_dashboard),
    path("publish/", publish_test_sentiment),
    
    # New endpoints (from origin/main)
    path("dashboard/", SentimentDashboardView.as_view()),
    path("search/", SocialMediaSearchView.as_view()),
    path("keywords/", AddKeywordView.as_view()),
    path("my-sentiments/", UserSentimentView.as_view()),
    path("trigger-keyword-search/", UserKeywordSearchTriggerView.as_view()),
]