import json
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from .models import ContactMessage


def _cors_json_response(data, status=200):
    response = JsonResponse(data, status=status)
    response["Access-Control-Allow-Origin"] = "*"
    response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    response["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response


@csrf_exempt
def contact_api(request):
    # Respond to preflight CORS requests
    if request.method == "OPTIONS":
        return _cors_json_response({}, status=200)

    if request.method == "POST":
        try:
            data = json.loads(request.body)

            name = data.get("name")
            email = data.get("email")
            message = data.get("message")
            timestamp = data.get("timestamp")

            if not name or not email or not message:
                return _cors_json_response({"message": "All fields are required"}, status=400)

            # Optionally persist the message to DB here
            # ContactMessage.objects.create(name=name, email=email, message=message, timestamp=timestamp)

            return _cors_json_response({"message": "Message sent successfully"}, status=201)

        except Exception as e:
            return _cors_json_response({"message": str(e)}, status=500)

    return _cors_json_response({"message": "Invalid request"}, status=405)