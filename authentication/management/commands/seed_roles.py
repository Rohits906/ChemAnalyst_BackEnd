from django.core.management.base import BaseCommand
from authentication.models import Permission, Role

class Command(BaseCommand):
    help = 'Seed initial permissions and roles'

    def handle(self, *args, **options):
        # 1. Define Permissions
        permissions_data = [
            {'id': 'group_manage', 'desc': 'Create, Edit, and Delete groups (Roles)'},
            {'id': 'member_manage', 'desc': 'Add or Remove members from the account'},
            {'id': 'role_assign', 'desc': 'Assign roles to existing members'},
            {'id': 'role_create_custom', 'desc': 'Create custom roles within an account'},
            {'id': 'permission_manage', 'desc': 'Add or remove specific permissions from roles'},
        ]

        created_perms = {}
        for perm in permissions_data:
            obj, created = Permission.objects.update_or_create(
                permission_id=perm['id'],
                defaults={'description': perm['desc']}
            )
            created_perms[perm['id']] = obj
            if created:
                self.stdout.write(self.style.SUCCESS(f"Created permission: {perm['id']}"))

        # 2. Define System Roles
        # Superadmin (System Role)
        superadmin, created = Role.objects.update_or_create(
            role_name='Superadmin',
            is_system_role=True,
            defaults={'account': None}
        )
        # Give Superadmin all permissions
        superadmin.permissions.set(created_perms.values())
        if created:
            self.stdout.write(self.style.SUCCESS("Created Superadmin system role"))

        # Admin (System Template Role - used as default for new accounts)
        admin_template, created = Role.objects.update_or_create(
            role_name='Admin',
            is_system_role=True,
            defaults={'account': None}
        )
        admin_template.permissions.set(created_perms.values()) # Admin also gets full control for their account
        if created:
            self.stdout.write(self.style.SUCCESS("Created Admin template system role"))

        # User (System Template Role)
        user_template, created = Role.objects.update_or_create(
            role_name='User',
            is_system_role=True,
            defaults={'account': None}
        )
        # User gets no administrative permissions by default
        if created:
            self.stdout.write(self.style.SUCCESS("Created User template system role"))

        self.stdout.write(self.style.SUCCESS("Seeding completed successfully!"))
