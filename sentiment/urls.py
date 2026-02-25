from django.urls import path
from .views import sentiment_dashboard, publish_test_sentiment

urlpatterns = [
    path("dashboard/", sentiment_dashboard),
    path("publish/", publish_test_sentiment),
]