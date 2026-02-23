from django.urls import path
from .views import create_platform, get_platform

urlpatterns = [
    path("platforms/", create_platform, name="create_platform"),
    path("platforms/get", get_platform, name="get_platform")
]