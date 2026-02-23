import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import AddPlatform

@csrf_exempt
def create_platform(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)

            name = data.get("name")
            channel_url = data.get("channel_url")
            channel_id = data.get("channel_id")

            if not name or not channel_url or not channel_id:
                return JsonResponse({"message": "All fields required"}, status=400)

            AddPlatform.objects.create(
                name=name,
                channel_url=channel_url,
                channel_id=channel_id
            )

            return JsonResponse({"message": "Platform Added Successfully"}, status=201)

        except Exception as e:
            return JsonResponse({"message": str(e)}, status=500)

    return JsonResponse({"message": "Invalid request"}, status=405)

def get_platform(request):
    if request.method == "GET":
        try:
            platforms = AddPlatform.objects.all().order_by("-created_at")

            data = []
            for platform in platforms:
                data.append({
                    "id": platform.id,
                    "name": platform.name,
                    "channel_url": platform.channel_url,
                    "channel_id": platform.channel_id,
                    "created_at": platform.created_at,
                })

            return JsonResponse({
                "message": "Platforms fetched successfully",
                "data": data
            }, status=200)

        except Exception as e:
            return JsonResponse({"message": str(e)}, status=500)
