from django.db import models
from django.contrib.auth.models import AbstractUser


class Permission(models.Model):
    permission_id = models.CharField(max_length=100)
    description = models.CharField(max_length=255)

    def __str__(self):
        return self.permission_id


class Role(models.Model):
    role_name = models.CharField(max_length=50)
    permissions = models.ManyToManyField(Permission, related_name="roles")

    def __str__(self):
        return self.role_name


class User(AbstractUser):
    role = models.OneToOneField(
        Role,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    
    def __str__(self):
        return self.username



