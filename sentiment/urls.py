from django.urls import path
from .views import (
    sentiment_dashboard, 
    SocialMediaSearchView, 
    AddKeywordView, 
    UserSentimentView,
    UserKeywordSearchTriggerView
)

urlpatterns = [
    path("dashboard/", sentiment_dashboard),
    path("search/", SocialMediaSearchView.as_view()),
    path("keywords/", AddKeywordView.as_view()),
    path("my-sentiments/", UserSentimentView.as_view()),
    path("trigger-keyword-search/", UserKeywordSearchTriggerView.as_view()),
]