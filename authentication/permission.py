from rest_framework.permissions import BasePermission

class HasPermission(BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        required_permission = getattr(view, "required_permission", None)

        if not required_permission:
            return True

        return request.user.role.permissions.filter(
            permission_id=required_permission
        ).exists()

