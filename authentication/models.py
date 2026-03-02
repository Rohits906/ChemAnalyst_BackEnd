from django.db import models
from django.contrib.auth.models import User
import uuid


ACCOUNT_TYPE_CHOICES = [
    ("individual", "Individual"),
    ("business", "Business"),
]


class Account(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)

    account_type = models.CharField(
        max_length=20, choices=ACCOUNT_TYPE_CHOICES, default="individual"
    )

    account_owner = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="owned_account"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    is_active = models.BooleanField(default=True)
    theme = models.CharField(max_length=20, default="light")
    timezone = models.CharField(max_length=50, default="UTC")
    
    # 2FA Fields (Email based)
    two_factor_enabled = models.BooleanField(default=False)
    otp_code = models.CharField(max_length=6, blank=True, null=True)
    otp_expiry = models.DateTimeField(blank=True, null=True)
    jwt_version = models.IntegerField(default=1)

    def __str__(self):
        return self.name


class Permission(models.Model):
    permission_id = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255)

    def __str__(self):
        return self.permission_id


from django.core.exceptions import ValidationError


class Role(models.Model):
    account = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="roles", null=True, blank=True
    )

    role_name = models.CharField(max_length=50)

    permissions = models.ManyToManyField(Permission, related_name="roles", blank=True)

    is_system_role = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["account", "role_name"], name="unique_role_per_account"
            )
        ]

    def clean(self):

        if not self.is_system_role and not self.account:
            raise ValidationError("Account is required for non-system roles.")

        if self.is_system_role and self.account:
            raise ValidationError("System roles cannot belong to an account.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        if self.account:
            return f"{self.role_name} ({self.account.name})"
        return f"{self.role_name} (System)"

   
    def has_permission(self, permission_code):
        for role in self.roles.all():
            if role.permissions.filter(permission_id=permission_code).exists():
                return True
        return False
    


class AccountMember(models.Model):
    account = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="members"
    )

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="account_memberships"
    )

    role = models.ForeignKey(
        Role, on_delete=models.CASCADE, related_name="assigned_members"
    )

    joined_at = models.DateTimeField(auto_now_add=True)
    is_accepted = models.BooleanField(default=False)
    invitation_token = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        unique_together = ("account", "user")

    def __str__(self):
        return f"{self.user.username} in {self.account.name}"


class SecurityQuestion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.CharField(max_length=255)

    def __str__(self):
        return self.question


class UserSecurityAnswer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="security_answers")
    question = models.ForeignKey(SecurityQuestion, on_delete=models.CASCADE)
    answer = models.CharField(max_length=255)  # Should ideally be hashed

    def __str__(self):
        return f"{self.user.username} - {self.question.question}"
