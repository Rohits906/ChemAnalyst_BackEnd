from django.core.mail import EmailMessage
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

        # Professional Email Template for Admin
        subject = f"Support Request: {name} (via ChemAnalyst)"
        body = f"""
Dear Admin,

You have received a new support request from the ChemAnalyst platform.

--------------------------------------------------
SENDER DETAILS
--------------------------------------------------
Name:     {name}
Email:    {email}
Received: {timestamp}

--------------------------------------------------
MESSAGE CONTENT
--------------------------------------------------
{message}

--------------------------------------------------

You can reply directly to this email to respond to the user.

Best regards,
ChemAnalyst System
"""
        
        email_msg = EmailMessage(
            subject=subject,
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[settings.DEFAULT_FROM_EMAIL],
            reply_to=[email],
        )
        email_msg.send(fail_silently=False)

        return Response({"message": "Message sent successfully"}, status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response({"message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
