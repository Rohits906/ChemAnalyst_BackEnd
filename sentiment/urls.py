from django.urls import path
from .views import sentiment_dashboard

urlpatterns = [
    path("dashboard/", sentiment_dashboard),
]