from django.core.mail import send_mail
from django.conf import settings
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

        # Send confirmation email to the user
        subject = f"Support Message Received: {name}"
        body = f"Hi {name},\n\nThank you for contacting us. We have received your message:\n\n\"{message}\"\n\nOur team will get back to you soon.\n\nBest regards,\nChemAnalyst Team"
        
        send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [email],
            fail_silently=False,
        )

        return Response({"message": "Message sent successfully"}, status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response({"message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)