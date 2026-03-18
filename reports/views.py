import json
import pandas as pd
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from rest_framework.decorators import api_view
from django.conf import settings
import os
from platforms.models import ChannelPost
from sentiment.models import Post, Sentiment
from django.db.models import Count, Q
from datetime import datetime, timedelta

@api_view(["GET"])
def platform_data_status(request):
    try:
        from_date = request.GET.get('from_date')
        to_date = request.GET.get('to_date')
        
        # Base filters
        date_q = Q()
        if from_date:
            date_q &= Q(published_at__gte=from_date)
        if to_date:
            date_q &= Q(published_at__lte=to_date)

        platforms_to_check = ["twitter", "facebook", "instagram", "linkedin", "youtube"]
        response_data = {}

        for p_name in platforms_to_check:
            # Check ChannelPost
            cp_count = ChannelPost.objects.filter(date_q, platform__name=p_name).count()
            # Check Sentiment Post
            sp_count = Post.objects.filter(date_q, platform=p_name).count()
            
            total_count = cp_count + sp_count
            response_data[p_name] = {
                "status": "Completed" if total_count > 0 else "No Data",
                "count": total_count,
            }

        return JsonResponse(response_data)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

@api_view(["GET"])
def export_report(request, platform, file_type):
    try:
        platform = platform.lower()
        from_date = request.GET.get('from_date')
        to_date = request.GET.get('to_date')

        date_q = Q()
        if from_date:
            date_q &= Q(published_at__gte=from_date)
        if to_date:
            date_q &= Q(published_at__lte=to_date)

        report_data = []
        
        # 1. Fetch from ChannelPost
        cp_posts = ChannelPost.objects.filter(date_q, platform__name=platform).select_related('platform')
        for post in cp_posts:
            report_data.append({
                "Sr": len(report_data) + 1,
                "Post_Subject": post.title or (post.content[:100] + "..." if post.content else "No Title"),
                "Post_link": post.post_url,
                "Platform": platform.capitalize(),
                "Sentiment": post.sentiment_label or "Neutral",
                "Likes": post.likes,
                "Comments": post.comments,
                "Shares": post.shares,
                "Published_At": post.published_at.strftime("%Y-%m-%d %H:%M:%S")
            })

        # 2. Fetch from Sentiment Post
        sp_posts = Post.objects.filter(date_q, platform=platform).prefetch_related('sentiments')
        for post in sp_posts:
            # Get the first sentiment label if available
            sentiment_obj = post.sentiments.first()
            sentiment_label = sentiment_obj.sentiment_label if sentiment_obj else "Neutral"
            
            report_data.append({
                "Sr": len(report_data) + 1,
                "Post_Subject": post.post_title or (post.post_text[:100] + "..." if post.post_text else "No Title"),
                "Post_link": post.post_url,
                "Platform": platform.capitalize(),
                "Sentiment": sentiment_label,
                "Likes": post.likes,
                "Comments": post.comments,
                "Shares": post.shares,
                "Published_At": post.published_at.strftime("%Y-%m-%d %H:%M:%S")
            })

        if not report_data:
            return HttpResponse("No data found for this period", status=404)

        df = pd.DataFrame(report_data)

        if file_type == "json":
            response = HttpResponse(
                json.dumps(report_data, indent=4, ensure_ascii=False),
                content_type="application/json",
            )
            response["Content-Disposition"] = f"attachment; filename={platform}_report.json"
            return response

        elif file_type == "csv":
            response = HttpResponse(content_type="text/csv")
            response["Content-Disposition"] = f"attachment; filename={platform}_report.csv"
            df.to_csv(response, index=False, encoding='utf-8-sig')
            return response

        elif file_type == "excel":
            response = HttpResponse(
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            response["Content-Disposition"] = f"attachment; filename={platform}_report.xlsx"
            df.to_excel(response, index=False)
            return response

        return HttpResponse("Invalid type", status=400)

    except Exception as e:
        return HttpResponse(str(e), status=500)