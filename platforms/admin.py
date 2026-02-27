from django.contrib import admin
from .models import Platform, ChannelStats, ChannelPost, PlatformFetchTask

admin.site.register(Platform)
admin.site.register(ChannelStats)
admin.site.register(ChannelPost)
admin.site.register(PlatformFetchTask)
