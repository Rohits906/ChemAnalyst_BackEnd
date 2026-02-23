from rest_framework.views import APIView
from rest_framework.response import Response

from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView
from django.contrib.auth import get_user_model
from .serializers import SignupSerializer
from rest_framework.permissions import AllowAny
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken


User = get_user_model()


class LoginView(TokenObtainPairView):
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            access_token = response.data.get("access")
            refresh_token = response.data.get("refresh")
            response.data = {
                "success": True,
                "data": {
                    "access": access_token,
                    "refresh": refresh_token,
                },
            }

            response.set_cookie(
                key="access_token",
                value=access_token,
                httponly=True,
                secure=True,
                samesite="Lax",
            )
            response.set_cookie(
                key="refresh_token",
                value=refresh_token,
                httponly=True,
                secure=True,
                samesite="Lax",
            )
        else:
            response.data = {
                "success": False,
                "error": "Invalid credentials",
            }

        return response


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        response = Response({"success": True, "message": "Logged out successfully"})
        response.delete_cookie("access_token")
        response.delete_cookie("refresh_token")
        return response


class SignupView(APIView):
    permission_classes = [AllowAny]   
    serializer_class = SignupSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            access_token = RefreshToken.for_user(user).access_token
            refresh_token = RefreshToken.for_user(user)
            response = Response(
                {"success": True, "message": "User registered successfully"},
                status=status.HTTP_201_CREATED,
            )

            response.set_cookie(
                key="access_token",
                value=str(access_token),
                httponly=True,
                secure=True,
                samesite="Lax",
            )
            response.set_cookie(
                key="refresh_token",
                value=str(refresh_token),
                httponly=True,
                secure=True,
                samesite="Lax",
            )
            return response

        return Response(
            {
                "success": False,
                "message": "Invalid data provided",
                "errors": serializer.errors,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )


class VerifyAuth(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"success": True, "message": "User Authenticated"}, 200)
