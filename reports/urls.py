from django.urls import path
from .views import platform_data_status, export_report

urlpatterns = [
    path("platform-status/", platform_data_status),
    path("export/<str:platform>/<str:file_type>/", export_report),
]