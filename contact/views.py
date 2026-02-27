import json
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from .models import ContactMessage

@csrf_exempt
def contact_api(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            print(data)
            name = data.get("name")
            email = data.get("email")
            message = data.get("message")
            timestamp = data.get("timestamp")

            if not name or not email or not message:
                return JsonResponse({"message": "All fields are required"}, status=400)

            # Persist the message to DB
            ContactMessage.objects.create(name=name, email=email, message=message, timestamp=timestamp)

            return JsonResponse({"message": "Message sent successfully"}, status=201)

        except Exception as e:
            return JsonResponse({"message": str(e)}, status=500)

    return JsonResponse({"message": "Invalid request"}, status=405)