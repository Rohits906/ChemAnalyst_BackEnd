from rest_framework.views import APIView
from rest_framework.response import Response
import requests
import logging
from django.utils.crypto import get_random_string

from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView
from django.contrib.auth import get_user_model
from .serializers import (
    SignupSerializer, 
    SecurityQuestionSerializer, 
    CustomTokenObtainPairSerializer,
    AccountMemberSerializer,
    RoleSerializer,
    AvatarUploadSerializer
)
from .models import Account, SecurityQuestion, UserSecurityAnswer, AccountMember, Role
from django.db.models import Q
from rest_framework.permissions import AllowAny
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from django.core.mail import send_mail
from django.utils import timezone
from datetime import timedelta
import random
import uuid
from django.conf import settings


User = get_user_model()

def send_otp_email(user, otp_code, subject=None, message=None):
    if not subject:
        subject = "Your Verification Code"
    if not message:
        message = f"Hello {user.first_name or user.username},\n\nYour verification code is: {otp_code}\n\nThis code will expire in 10 minutes."
    
    from_email = settings.DEFAULT_FROM_EMAIL
    recipient_list = [user.email]
    
    print(f"DEBUG: Attempting to send email to {user.email} with code {otp_code}")
    
    try:
        sent = send_mail(subject, message, from_email, recipient_list)
        if sent:
            print(f"DEBUG: OTP {otp_code} sent to {user.email} from {from_email}")
            return True
        else:
            print(f"DEBUG: Email sending failed (returned 0) for {user.email}")
            return False
    except Exception as e:
        print(f"Error sending email to {user.email}: {e}")
        return False


def get_user_avatar_url(request, user):
    """Helper to get absolute avatar URL for a user."""
    account = getattr(user, 'owned_account', None)
    if account and account.avatar:
        try:
            return request.build_absolute_uri(account.avatar.url)
        except Exception as e:
            print(f"DEBUG: Error building avatar URI: {e}")
    return None


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
                enable_2fa_request = request.data.get("enable_2fa", False)
                
                if account and (account.two_factor_enabled or enable_2fa_request):
                    # Generate OTP
                    otp = str(random.randint(100000, 999999))
                    account.otp_code = otp
                    account.otp_expiry = timezone.now() + timedelta(minutes=10)
                    account.save()
                    
                    # Send OTP email
                    send_otp_email(user, otp)
                    
                    # If 2FA enabled or requested, don't return tokens yet
                    return Response({
                        "success": True,
                        "data": {
                            "two_factor_required": True,
                            "is_setup": enable_2fa_request and not account.two_factor_enabled,
                            "user_id": user.id,
                            "message": "A verification code has been sent to your email."
                        }
                    }, status=status.HTTP_200_OK)

                user_data = {
                    "email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "username": user.username,
                    "avatar": get_user_avatar_url(request, user)
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
            account, created = Account.objects.get_or_create(account_owner=user, defaults={'name': user.username})
            
            # Assign Admin role to the account owner
            # Look for the system 'Admin' template role
            admin_role = Role.objects.filter(role_name='Admin', is_system_role=True).first()
            if admin_role:
                AccountMember.objects.get_or_create(
                    account=account,
                    user=user,
                    defaults={'role': admin_role, 'is_accepted': True}
                )
            
            refresh = RefreshToken.for_user(user)
            access_token = str(refresh.access_token)
            refresh_token = str(refresh)

            user_data = {
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "username": user.username,
                "avatar": get_user_avatar_url(request, user)
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
        
        # Get role and permissions
        membership = AccountMember.objects.filter(user=user).select_related('role').first()
        role_name = membership.role.role_name if membership else None
        permissions = []
        if membership and membership.role:
            permissions = list(membership.role.permissions.values_list('permission_id', flat=True))
        
        user_data = {
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "username": user.username,
            "role": role_name,
            "permissions": permissions,
            "avatar": get_user_avatar_url(request, user)
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
            "security_questions_set": security_questions_set,
            "avatar": request.build_absolute_uri(account.avatar.url) if account and account.avatar else None
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
            
            is_setup = request.data.get("is_setup", False)
            if not account or (not account.two_factor_enabled and not is_setup):
                return Response({"success": False, "message": "2FA not enabled for this user"}, status=status.HTTP_400_BAD_REQUEST)
                
            if account.otp_code == code and account.otp_expiry > timezone.now():
                if is_setup:
                    account.two_factor_enabled = True
                
                refresh = RefreshToken.for_user(user)
                # Add jwt_version to claims
                refresh['jwt_version'] = account.jwt_version
                
                access_token = str(refresh.access_token)
                refresh_token = str(refresh)
                
                account.otp_code = None # Clear after use
                account.save()

                # Get role and permissions
                membership = AccountMember.objects.filter(user=user).select_related('role').first()
                role_name = membership.role.role_name if membership else None
                permissions = []
                if membership and membership.role:
                    permissions = list(membership.role.permissions.values_list('permission_id', flat=True))

                user_data = {
                    "email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "username": user.username,
                    "role": role_name,
                    "permissions": permissions,
                    "avatar": get_user_avatar_url(request, user)
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


class Check2FAStatusView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get("username")
        if not username:
            return Response({"success": False, "message": "Username/Email required"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            if '@' in username:
                user = User.objects.get(email=username)
            else:
                user = User.objects.get(username=username)
            
            account = getattr(user, 'owned_account', None)
            is_enabled = account.two_factor_enabled if account else False
            
            return Response({"success": True, "two_factor_enabled": is_enabled})
        except User.DoesNotExist:
            return Response({"success": False, "message": "User not found"}, status=status.HTTP_404_NOT_FOUND)

class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        identifier = request.data.get("email") # Identifier can be email or username
        print(f"DEBUG: ForgotPasswordView hit with identifier: {identifier}")
        
        if not identifier:
            return Response({"success": False, "message": "Email or Username is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        identifier = identifier.strip()
        
        try:
            # Match LoginView logic: handle email or username
            if '@' in identifier:
                user = User.objects.get(email__iexact=identifier)
            else:
                user = User.objects.get(username__iexact=identifier)
                
            print(f"DEBUG: User found: {user.username} (Email: {user.email})")
            
            if not user.email:
                print(f"DEBUG: User {user.username} has no email address set.")
                return Response({"success": False, "message": "This account does not have an email address associated with it."}, status=status.HTTP_400_BAD_REQUEST)

            account, _ = Account.objects.get_or_create(account_owner=user, defaults={'name': user.username})
            
            # Generate OTP
            otp = str(random.randint(100000, 999999))
            account.otp_code = otp
            account.otp_expiry = timezone.now() + timedelta(minutes=10)
            account.save()
            print(f"DEBUG: OTP generated and saved for {user.username}: {otp}")
            
            # Send OTP email with specific subject
            subject = "Password Reset Verification Code"
            message = f"Hello {user.first_name or user.username},\n\nYour password reset verification code is: {otp}\n\nThis code will expire in 10 minutes."
            
            if send_otp_email(user, otp, subject=subject, message=message):
                print(f"DEBUG: Forgot Password OTP sent successfully to {user.email}")
                return Response({"success": True, "message": "Verification code sent to your email."})
            else:
                print(f"DEBUG: Failed to send Forgot Password OTP to {user.email}")
                return Response({"success": False, "message": "Failed to send email. Please try again."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except User.DoesNotExist:
            print(f"DEBUG: No user found with identifier: {identifier}")
            return Response({"success": False, "message": "No account found with this email/username."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            print(f"DEBUG: Error in ForgotPasswordView for {identifier}: {e}")
            return Response({"success": False, "message": f"An error occurred: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class ResetPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        identifier = request.data.get("email") # Identifier can be email or username
        otp = request.data.get("otp")
        new_password = request.data.get("new_password")
        
        print(f"DEBUG: ResetPasswordView hit for: {identifier}")

        if not identifier or not otp or not new_password:
            return Response({"success": False, "message": "Email/Username, OTP and new password are required"}, status=status.HTTP_400_BAD_REQUEST)
            
        identifier = identifier.strip()

        try:
            if '@' in identifier:
                user = User.objects.get(email__iexact=identifier)
            else:
                user = User.objects.get(username__iexact=identifier)
                
            account = getattr(user, 'owned_account', None)
            
            if not account or account.otp_code != otp or account.otp_expiry < timezone.now():
                print(f"DEBUG: Invalid or expired OTP for {identifier}")
                return Response({"success": False, "message": "Invalid or expired verification code"}, status=status.HTTP_400_BAD_REQUEST)
            
            if len(new_password) < 8:
                return Response({"success": False, "message": "Password must be at least 8 characters long"}, status=status.HTTP_400_BAD_REQUEST)
                
            user.set_password(new_password)
            user.save()
            print(f"DEBUG: Password reset successful for {user.username}")
            
            # Clear OTP after successful reset
            account.otp_code = None
            account.otp_expiry = None
            # Increment jwt_version to invalidate existing tokens
            account.jwt_version += 1
            account.save()
            
            return Response({"success": True, "message": "Password reset successfully. You can now log in."})
            
        except User.DoesNotExist:
            print(f"DEBUG: User not found during reset: {identifier}")
            return Response({"success": False, "message": "User not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            print(f"DEBUG: Error in ResetPasswordView for {identifier}: {e}")
            return Response({"success": False, "message": f"An error occurred: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class AccountMemberListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Find the account associated with the user. 
        # For now, we'll assume the user is part of at least one account.
        membership = AccountMember.objects.filter(user=request.user).first()
        if not membership:
            # Fallback for owners who might not be in AccountMember explicitly
            account = Account.objects.filter(account_owner=request.user).first()
        else:
            account = membership.account

        if not account:
            return Response({"success": False, "message": "No account found for user."}, status=404)

        members = AccountMember.objects.filter(account=account).select_related("user", "role")
        serializer = AccountMemberSerializer(members, many=True)
        return Response({"success": True, "data": serializer.data})

class AccountRoleListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        membership = AccountMember.objects.filter(user=request.user).first()
        if not membership:
            account = Account.objects.filter(account_owner=request.user).first()
        else:
            account = membership.account

        # System roles + account-specific roles
        roles = Role.objects.filter(Q(is_system_role=True) | Q(account=account))
        serializer = RoleSerializer(roles, many=True)
        return Response({"success": True, "data": serializer.data})

class UpdateMemberRoleView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        member_id = request.data.get("member_id")
        role_id = request.data.get("role_id")

        try:
            member = AccountMember.objects.get(id=member_id)
            # Check if current user has permission to update roles (e.g., is owner or has 'manage_members')
            # For brevity in this step, we check if they are the account owner.
            if member.account.account_owner != request.user:
                 return Response({"success": False, "message": "Only account owners can update roles."}, status=403)

            role = Role.objects.get(id=role_id)
            member.role = role
            member.save()
            return Response({"success": True, "message": "Member role updated successfully."})
        except (AccountMember.DoesNotExist, Role.DoesNotExist):
            return Response({"success": False, "message": "Member or Role not found."}, status=404)

class RemoveMemberView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, member_id):
        try:
            member = AccountMember.objects.get(id=member_id)
            if member.account.account_owner != request.user:
                 return Response({"success": False, "message": "Only account owners can remove members."}, status=403)
            
            if member.user == request.user:
                 return Response({"success": False, "message": "You cannot remove yourself."}, status=400)

            member.delete()
            return Response({"success": True, "message": "Member removed successfully."})
        except AccountMember.DoesNotExist:
            return Response({"success": False, "message": "Member not found."}, status=404)

class InviteMemberView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        email = request.data.get("email")
        role_id = request.data.get("role_id")

        if not email or not role_id:
            return Response({"success": False, "message": "Email and Role are required."}, status=400)

        # 1. Get current user's account
        membership = AccountMember.objects.filter(user=request.user).first()
        if not membership:
            account = Account.objects.filter(account_owner=request.user).first()
        else:
            account = membership.account

        if not account or account.account_owner != request.user:
            return Response({"success": False, "message": "Only account owners can invite members."}, status=403)

        is_new_user = False
        temp_password = None
        
        try:
            target_user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            # Create a new user with placeholder details
            is_new_user = True
            username_prefix = email.split('@')[0]
            
            # Ensure unique username
            base_username = username_prefix
            counter = 1
            while User.objects.filter(username=base_username).exists():
                base_username = f"{username_prefix}{counter}"
                counter += 1
                
            temp_password = get_random_string(length=12)
            target_user = User.objects.create_user(
                username=base_username,
                email=email,
                password=temp_password,
                first_name=username_prefix.capitalize(),
                is_active=False
            )

        # 3. Check if already a member
        member = AccountMember.objects.filter(account=account, user=target_user).first()
        
        if member:
            if member.is_accepted:
                return Response({"success": False, "message": "User is already an active member of this account."}, status=400)
            
            # If already invited but not accepted, we "resend" by updating the role and token
            try:
                role = Role.objects.get(id=role_id)
            except Role.DoesNotExist:
                return Response({"success": False, "message": "Invalid role selected."}, status=400)
                
            member.role = role
            token = uuid.uuid4().hex
            member.invitation_token = token
            member.save()
            print(f"DEBUG: Resending invitation to {email} with new token {token}")
        else:
            # 4. Get Role
            try:
                role = Role.objects.get(id=role_id)
            except Role.DoesNotExist:
                return Response({"success": False, "message": "Invalid role selected."}, status=400)

            # 5. Create membership with token
            token = uuid.uuid4().hex
            AccountMember.objects.create(
                account=account, 
                user=target_user, 
                role=role,
                is_accepted=False,
                invitation_token=token
            )
        
        # 6. Send Email Notification with Frontend Link
        frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')
        accept_url = f"{frontend_url}/accept-invitation/{token}/"
        
        subject = f"Invitation: You've been added to {account.account_name if hasattr(account, 'account_name') else 'a team'} on ChemAnalyst"
        
        if is_new_user:
            message = (
                f"Hello {target_user.first_name},\n\n"
                f"You have been invited to join a team account on ChemAnalyst.\n\n"
                f"Role Assigned: {role.role_name}\n"
                f"Added by: {request.user.first_name or request.user.username}\n\n"
                f"An account has been created for you. Here are your temporary login credentials:\n"
                f"Email: {target_user.email}\n"
                f"Password: {temp_password}\n\n"
                f"Please click the link below to accept the invitation and activate your membership:\n"
                f"{accept_url}\n\n"
                f"Regards,\n"
                f"ChemAnalyst Team"
            )
        else:
            message = (
                f"Hello {target_user.first_name or target_user.username},\n\n"
                f"You have been invited to join a team account on ChemAnalyst.\n\n"
                f"Role Assigned: {role.role_name}\n"
                f"Added by: {request.user.first_name or request.user.username}\n\n"
                f"Please click the link below to accept the invitation and activate your membership:\n"
                f"{accept_url}\n\n"
                f"Regards,\n"
                f"ChemAnalyst Team"
            )
            
        from_email = settings.DEFAULT_FROM_EMAIL
        recipient_list = [target_user.email]

        email_sent = False
        try:
            sent = send_mail(subject, message, from_email, recipient_list)
            if sent:
                email_sent = True
        except Exception as e:
            print(f"Error sending invitation email: {e}")

        response_msg = f"Successfully invited {target_user.username} to the team."
        if not email_sent:
            response_msg += " (Note: Notification email could not be sent, but membership was created.)"

        return Response({"success": True, "message": response_msg})

from django.http import HttpResponseRedirect

class AcceptInvitationView(APIView):
    permission_classes = [AllowAny] # Anyone with the token can accept

    def get(self, request, token):
        try:
            membership = AccountMember.objects.get(invitation_token=token)
            # Instead of auto-accepting, we redirect to the frontend with the token
            frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')
            return HttpResponseRedirect(f"{frontend_url}/accept-invitation/{token}/")
        except AccountMember.DoesNotExist:
            return Response({"success": False, "message": "Invalid or expired invitation token."}, status=404)

class InvitationDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, token):
        try:
            membership = AccountMember.objects.select_related('account', 'role', 'user').get(invitation_token=token)
            data = {
                "account_name": membership.account.name,
                "role_name": membership.role.role_name,
                "invited_user": membership.user.username,
                "token": token
            }
            return Response({"success": True, "data": data})
        except AccountMember.DoesNotExist:
            return Response({"success": False, "message": "Invitation not found."}, status=404)

class ProcessInvitationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        token = request.data.get("token")
        action = request.data.get("action") # 'accept' or 'decline'

        if not token or action not in ['accept', 'decline']:
            return Response({"success": False, "message": "Token and valid action (accept/decline) are required."}, status=400)

        try:
            membership = AccountMember.objects.get(invitation_token=token)
            
            if action == 'accept':
                membership.is_accepted = True
                membership.invitation_token = None
                membership.save()
                
                # Activate the user account so they can log in
                user = membership.user
                if not user.is_active:
                    user.is_active = True
                    user.save()
                    
                return Response({"success": True, "message": "Invitation accepted successfully."})
            else:
                membership.delete()
                return Response({"success": True, "message": "Invitation declined."})

        except AccountMember.DoesNotExist:
            return Response({"success": False, "message": "Invitation not found or already processed."}, status=404)

class AvatarUploadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        print(f"DEBUG: Avatar upload request received for user {request.user}")
        user = request.user
        account, _ = Account.objects.get_or_create(account_owner=user, defaults={'name': user.username})
        
        if 'avatar' not in request.FILES:
            print("DEBUG: No 'avatar' in request.FILES")
            return Response({"success": False, "message": "No image provided"}, status=status.HTTP_400_BAD_REQUEST)

        print(f"DEBUG: Received file: {request.FILES['avatar'].name}, Size: {request.FILES['avatar'].size}")

        # Delete old avatar if it exists
        if account.avatar:
            try:
                account.avatar.delete(save=False)
                print("DEBUG: Deleted old avatar")
            except Exception as e:
                print(f"DEBUG: Error deleting old avatar: {e}")

        try:
            account.avatar = request.FILES['avatar']
            account.save()
            print("DEBUG: Avatar saved successfully")
        except Exception as e:
            print(f"DEBUG: Error saving avatar: {e}")
            return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        avatar_url = request.build_absolute_uri(account.avatar.url)
        print(f"DEBUG: Returning avatar URL: {avatar_url}")
        return Response({
            "success": True, 
            "message": "Avatar uploaded successfully",
            "data": {"avatar": avatar_url}
        })


logger = logging.getLogger(__name__)

class SocialAuthView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        provider = request.data.get('provider')
        code = request.data.get('code')

        if not provider or not code:
            return Response({"success": False, "message": "Provider and code are required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user_info = self.get_user_info(provider, code)
            if not user_info or not user_info.get('email'):
                logger.error(f"Social Auth Error: Failed to get user info or email from {provider}. Info: {user_info}")
                return Response({"success": False, "message": f"Failed to authenticate with {provider}"}, status=status.HTTP_401_UNAUTHORIZED)

            email = user_info['email']
            first_name = user_info.get('given_name') or user_info.get('first_name') or user_info.get('name', '').split(' ')[0]
            last_name = user_info.get('family_name') or user_info.get('last_name') or (' '.join(user_info.get('name', '').split(' ')[1:]) if ' ' in user_info.get('name', '') else '')
            
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                return Response({
                    "success": False,
                    "message": "No account found with this email. Please register first."
                }, status=status.HTTP_404_NOT_FOUND)

            # Generate tokens
            refresh = RefreshToken.for_user(user)
            
            # Get account data
            user_data = {
                "id": user.id,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "username": user.username,
                "avatar": get_user_avatar_url(request, user)
            }

            return Response({
                "success": True,
                "message": f"{provider.capitalize()} login successful",
                "data": {
                    "access": str(refresh.access_token),
                    "refresh": str(refresh),
                    "user": user_data
                }
            })

        except Exception as e:
            logger.error(f"Social Auth Error ({provider}): {str(e)}", exc_info=True)
            return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def get_user_info(self, provider, code):
        if provider == 'google':
            return self.get_google_user_info(code)
        elif provider == 'facebook':
            return self.get_facebook_user_info(code)
        elif provider == 'linkedin':
            return self.get_linkedin_user_info(code)
        return None

    def get_google_user_info(self, code):
        token_url = "https://oauth2.googleapis.com/token"
        data = {
            'client_id': settings.GOOGLE_CLIENT_ID,
            'client_secret': settings.GOOGLE_CLIENT_SECRET,
            'code': code,
            'grant_type': 'authorization_code',
            'redirect_uri': settings.GOOGLE_REDIRECT_URI
        }
        res = requests.post(token_url, data=data)
        token_data = res.json()
        if 'access_token' not in token_data:
            logger.error(f"Google Token Error: {token_data}")
            return None
        
        user_info_res = requests.get("https://www.googleapis.com/oauth2/v3/userinfo", 
                                     headers={'Authorization': f"Bearer {token_data['access_token']}"})
        return user_info_res.json()

    def get_facebook_user_info(self, code):
        token_url = f"https://graph.facebook.com/{settings.FACEBOOK_API_VERSION}/oauth/access_token"
        params = {
            'client_id': settings.FACEBOOK_APP_ID,
            'client_secret': settings.FACEBOOK_APP_SECRET,
            'code': code,
            'redirect_uri': settings.FACEBOOK_LOGIN_REDIRECT_URI
        }
        res = requests.get(token_url, params=params)
        token_data = res.json()
        if 'access_token' not in token_data:
            logger.error(f"Facebook Token Error: {token_data}")
            return None
            
        user_info_res = requests.get(f"https://graph.facebook.com/me?fields=id,name,email,picture&access_token={token_data['access_token']}")
        return user_info_res.json()

    def get_linkedin_user_info(self, code):
        token_url = "https://www.linkedin.com/oauth/v2/accessToken"
        data = {
            'grant_type': 'authorization_code',
            'code': code,
            'client_id': settings.LINKEDIN_CLIENT_ID,
            'client_secret': settings.LINKEDIN_CLIENT_SECRET,
            'redirect_uri': settings.LINKEDIN_REDIRECT_URI
        }
        res = requests.post(token_url, data=data)
        token_data = res.json()
        if 'access_token' not in token_data:
            logger.error(f"LinkedIn Token Error: {token_data}")
            return None
            
        # LinkedIn userinfo endpoint (OpenID Connect)
        user_info_res = requests.get("https://api.linkedin.com/v2/userinfo", 
                                     headers={'Authorization': f"Bearer {token_data['access_token']}"})
        return user_info_res.json()
