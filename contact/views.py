from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from .models import ContactMessage

@api_view(["POST"])
@permission_classes([AllowAny])
def contact_api(request):
    try:
        data = request.data
        name = data.get("name")
        email = data.get("email")
        message = data.get("message")
        timestamp = data.get("timestamp")

        if not name or not email or not message:
            return Response({"message": "All fields are required"}, status=status.HTTP_400_BAD_REQUEST)

        # Persist the message to DB
        ContactMessage.objects.create(name=name, email=email, message=message, timestamp=timestamp)

        return Response({"message": "Message sent successfully"}, status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response({"message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)