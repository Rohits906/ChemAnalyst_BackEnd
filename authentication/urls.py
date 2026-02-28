from django.urls import path
from .views import SignupView, LoginView, LogoutView, VerifyAuth, ProfileView, ChangePasswordView, DeleteAccountView, DeactivateAccountView, Enable2FAView, Verify2FAView, Disable2FAView, LoginVerify2FAView, SecurityQuestionListView, SetupSecurityQuestionsView

urlpatterns = [
    path("signup/", SignupView.as_view(), name="signup"),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("verify/", VerifyAuth.as_view(), name="verifyauth"),
    path("profile/", ProfileView.as_view(), name="profile"),
    path("change-password/", ChangePasswordView.as_view(), name="change-password"),
    path("delete/", DeleteAccountView.as_view(), name="delete-account"),
    path("deactivate/", DeactivateAccountView.as_view(), name="deactivate-account"),
    path("2fa/enable/", Enable2FAView.as_view(), name="enable-2fa"),
    path("2fa/verify/", Verify2FAView.as_view(), name="verify-2fa"),
    path("2fa/disable/", Disable2FAView.as_view(), name="disable-2fa"),
    path("2fa/login-verify/", LoginVerify2FAView.as_view(), name="login-verify-2fa"),
    path("security-questions/", SecurityQuestionListView.as_view(), name="security-questions"),
    path("setup-security-questions/", SetupSecurityQuestionsView.as_view(), name="setup-security-questions"),
]
