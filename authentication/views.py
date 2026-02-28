from rest_framework.views import APIView
from rest_framework.response import Response

from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView
from django.contrib.auth import get_user_model
from .serializers import SignupSerializer, SecurityQuestionSerializer, CustomTokenObtainPairSerializer
from .models import Account, SecurityQuestion, UserSecurityAnswer
from rest_framework.permissions import AllowAny
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from django.core.mail import send_mail
from django.utils import timezone
from datetime import timedelta
import random
from django.conf import settings


User = get_user_model()

def send_otp_email(user, otp_code):
    subject = "Your 2FA Verification Code"
    message = f"Hello {user.first_name},\n\nYour verification code is: {otp_code}\n\nThis code will expire in 10 minutes."
    from_email = settings.DEFAULT_FROM_EMAIL
    recipient_list = [user.email]
    
    try:
        sent = send_mail(subject, message, from_email, recipient_list)
        if sent:
            print(f"DEBUG: OTP {otp_code} sent to {user.email} from {from_email}")
            return True
        else:
            print(f"DEBUG: Email sending failed (returned 0)")
            return False
    except Exception as e:
        print(f"Error sending email: {e}")
        return False


class LoginView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            access_token = response.data.get("access")
            refresh_token = response.data.get("refresh")
            request_username = request.data.get("username", "")
            
            try:
                if '@' in request_username:
                    user = User.objects.get(email=request_username)
                else:
                    user = User.objects.get(username=request_username)
                
                account = getattr(user, 'owned_account', None)
                
                if account and account.two_factor_enabled:
                    # Generate OTP
                    otp = str(random.randint(100000, 999999))
                    account.otp_code = otp
                    account.otp_expiry = timezone.now() + timedelta(minutes=10)
                    account.save()
                    
                    # Send OTP email
                    send_otp_email(user, otp)
                    
                    # If 2FA enabled, don't return tokens yet
                    return Response({
                        "success": True,
                        "data": {
                            "two_factor_required": True,
                            "user_id": user.id,
                            "message": "A verification code has been sent to your email."
                        }
                    }, status=status.HTTP_200_OK)

                user_data = {
                    "email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "username": user.username,
                }
            except User.DoesNotExist:
                user_data = {}

            response.data = {
                "success": True,
                "data": {
                    "access": access_token,
                    "refresh": refresh_token,
                    "user": user_data,
                },
            }

            response.set_cookie(key="access_token", value=access_token, httponly=True, secure=True, samesite="Lax")
            response.set_cookie(key="refresh_token", value=refresh_token, httponly=True, secure=True, samesite="Lax")
        else:
            response.data = {"success": False, "error": "Invalid credentials"}

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
            # Create Account for the new user
            Account.objects.get_or_create(account_owner=user, defaults={'name': user.username})
            
            refresh = RefreshToken.for_user(user)
            access_token = str(refresh.access_token)
            refresh_token = str(refresh)

            user_data = {
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "username": user.username,
            }

            response = Response(
                {
                    "success": True,
                    "message": "User registered successfully",
                    "data": {
                        "access": access_token,
                        "refresh": refresh_token,
                        "user": user_data,
                    },
                },
                status=status.HTTP_201_CREATED,
            )

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
        user = request.user
        user_data = {
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "username": user.username,
        }
        return Response(
            {"success": True, "message": "User Authenticated", "data": user_data}, 200
        )

class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        account = getattr(user, "owned_account", None)
        security_questions_set = UserSecurityAnswer.objects.filter(user=user).exists()
        
        user_data = {
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "username": user.username,
            "theme": account.theme if account else "light",
            "timezone": account.timezone if account else "UTC",
            "two_factor_enabled": account.two_factor_enabled if account else False,
            "security_questions_set": security_questions_set
        }
        return Response({"success": True, "data": user_data}, status=status.HTTP_200_OK)

    def put(self, request):
        user = request.user
        data = request.data
        user.first_name = data.get("first_name", user.first_name)
        user.last_name = data.get("last_name", user.last_name)
        
        # Update email if provided, and keep username in sync if email is used as login
        new_email = data.get("email")
        if new_email and new_email != user.email:
            # Check if email is already taken
            if User.objects.filter(email=new_email).exclude(id=user.id).exists():
                return Response({"success": False, "message": "Email already in use by another account"}, status=status.HTTP_400_BAD_REQUEST)
            user.email = new_email
            # Assuming username is mapped to email based on login flow
            user.username = new_email.split("@")[0]

        user.save()
        
        # Update theme and timezone in Account model
        account, created = Account.objects.get_or_create(account_owner=user, defaults={'name': user.username})
        if "theme" in data:
            account.theme = data.get("theme")
        if "timezone" in data:
            account.timezone = data.get("timezone")
        account.save()
        return Response({"success": True, "message": "Profile updated successfully"}, status=status.HTTP_200_OK)

class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        current_password = request.data.get("current_password")
        new_password = request.data.get("new_password")

        if not current_password or not new_password:
            return Response({"success": False, "message": "Both current and new passwords are required"}, status=status.HTTP_400_BAD_REQUEST)

        if not user.check_password(current_password):
            return Response({"success": False, "message": "Incorrect current password"}, status=status.HTTP_400_BAD_REQUEST)
        
        if len(new_password) < 8:
            return Response({"success": False, "message": "Password must be at least 8 characters long"}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.save()
        return Response({"success": True, "message": "Password updated successfully"}, status=status.HTTP_200_OK)

class DeleteAccountView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        password = request.data.get("password")
        
        if not password:
            return Response({"success": False, "message": "Password is required to delete the account."}, status=status.HTTP_400_BAD_REQUEST)
            
        if not user.check_password(password):
            return Response({"success": False, "message": "Incorrect password. Account deletion failed."}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            user.delete()
            return Response({"success": True, "message": "Account deleted successfully"}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class DeactivateAccountView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        try:
            user.is_active = False
            user.save()
            return Response({"success": True, "message": "Account deactivated successfully"}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class Enable2FAView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        account, _ = Account.objects.get_or_create(account_owner=user, defaults={'name': user.username})
        
        # Generate and send OTP for verification
        otp = str(random.randint(100000, 999999))
        account.otp_code = otp
        account.otp_expiry = timezone.now() + timedelta(minutes=10)
        account.save()
        
        send_otp_email(user, otp)
        
        return Response({
            "success": True, 
            "message": "A verification code has been sent to your email."
        })

class Verify2FAView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        code = request.data.get("code")
        account = getattr(user, 'owned_account', None)
        
        if not account or not account.otp_code:
            return Response({"success": False, "message": "2FA setup not initiated"}, status=status.HTTP_400_BAD_REQUEST)
            
        if account.otp_code == code and account.otp_expiry > timezone.now():
            account.two_factor_enabled = True
            account.otp_code = None # Clear after use
            account.save()
            return Response({"success": True, "message": "2FA enabled successfully"})
        else:
            return Response({"success": False, "message": "Invalid or expired verification code"}, status=status.HTTP_400_BAD_REQUEST)

class Disable2FAView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        account = getattr(user, 'owned_account', None)
        if account:
            account.two_factor_enabled = False
            account.otp_code = None
            account.save()
        return Response({"success": True, "message": "2FA disabled successfully"})

class LoginVerify2FAView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        user_id = request.data.get("user_id")
        code = request.data.get("code")
        
        try:
            user = User.objects.get(id=user_id)
            account = getattr(user, 'owned_account', None)
            
            if not account or not account.two_factor_enabled:
                return Response({"success": False, "message": "2FA not enabled for this user"}, status=status.HTTP_400_BAD_REQUEST)
                
            if account.otp_code == code and account.otp_expiry > timezone.now():
                refresh = RefreshToken.for_user(user)
                # Add jwt_version to claims
                refresh['jwt_version'] = account.jwt_version
                
                access_token = str(refresh.access_token)
                refresh_token = str(refresh)
                
                account.otp_code = None # Clear after use
                account.save()

                user_data = {
                    "email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "username": user.username,
                }
                
                response = Response({
                    "success": True,
                    "data": {
                        "access": access_token,
                        "refresh": refresh_token,
                        "user": user_data,
                    },
                })
                response.set_cookie(key="access_token", value=access_token, httponly=True, secure=True, samesite="Lax")
                response.set_cookie(key="refresh_token", value=refresh_token, httponly=True, secure=True, samesite="Lax")
                return response
            else:
                return Response({"success": False, "message": "Invalid or expired 2FA code"}, status=status.HTTP_400_BAD_REQUEST)
        except User.DoesNotExist:
            return Response({"success": False, "message": "User not found"}, status=status.HTTP_404_NOT_FOUND)


class SecurityQuestionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        questions = SecurityQuestion.objects.all()
        serializer = SecurityQuestionSerializer(questions, many=True)
        return Response({"success": True, "data": serializer.data})

class SetupSecurityQuestionsView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        answers_data = request.data.get("answers", []) # Expected: [{"question_id": "...", "answer": "..."}]
        
        if not answers_data or len(answers_data) < 2:
            return Response({"success": False, "message": "Please set at least 2 security questions."}, status=status.HTTP_400_BAD_REQUEST)
            
        # Clear existing answers
        UserSecurityAnswer.objects.filter(user=user).delete()
        
        for item in answers_data:
            question_id = item.get("question_id")
            answer_text = item.get("answer", "").strip().lower()
            
            if not question_id or not answer_text:
                continue
                
            try:
                question = SecurityQuestion.objects.get(id=question_id)
                UserSecurityAnswer.objects.create(
                    user=user,
                    question=question,
                    answer=answer_text
                )
            except SecurityQuestion.DoesNotExist:
                continue
            
        return Response({"success": True, "message": "Security questions updated successfully."})

