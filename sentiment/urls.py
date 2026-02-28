from django.urls import path
from .views import (
    SentimentDashboardView, 
    SocialMediaSearchView, 
    AddKeywordView, 
    UserSentimentView,
    UserKeywordSearchTriggerView,
    ScraperStatusView,
    LiveSearchView
)

urlpatterns = [
    path("dashboard/", SentimentDashboardView.as_view()),
    path("search/", SocialMediaSearchView.as_view()),
    path("keywords/", AddKeywordView.as_view()),
    path("my-sentiments/", UserSentimentView.as_view()),
    path("trigger-keyword-search/", UserKeywordSearchTriggerView.as_view()),
    path("scraper-status/", ScraperStatusView.as_view()),
    path("live-search/", LiveSearchView.as_view()),
]