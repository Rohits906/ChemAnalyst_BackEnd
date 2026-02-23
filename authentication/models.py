from django.db import models
from django.contrib.auth.models import AbstractUser


class Permission(models.Model):
    permission_id = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255)

    def __str__(self):
        return self.permission_id


class Role(models.Model):
    role_name = models.CharField(max_length=50, unique=True)
    permissions = models.ManyToManyField(
        Permission,
        related_name="roles",
        blank=True
    )

    def __str__(self):
        return self.role_name


class User(AbstractUser):
    roles = models.ManyToManyField(
        Role,
        related_name="users",
        blank=True
    )

    def __str__(self):
        return self.username

   
    def has_permission(self, permission_code):
        for role in self.roles.all():
            if role.permissions.filter(permission_id=permission_code).exists():
                return True
        return False
    



