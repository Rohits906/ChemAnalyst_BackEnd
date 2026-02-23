from django.urls import path
from .views import create_platform, get_platform

urlpatterns = [
    path("create/", create_platform, name="create-platform"),
    path("", get_platform, name="get-platform"),
]