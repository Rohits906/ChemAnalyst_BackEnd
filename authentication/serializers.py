from rest_framework import serializers
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


class SignupSerializer(serializers.Serializer):
    password = serializers.CharField(max_length=128, write_only=True)
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()

    def create(self, validated_data):
        email = validated_data.get("email")
        password = validated_data["password"]
        username = validated_data["email"].split("@", -1)[0]
        print(validated_data)
        first_name = validated_data["first_name"]
        last_name = validated_data["last_name"]
        user = User.objects.create_user(
            email=email,
            username=username,
            password=password,
            first_name=first_name,
            last_name=last_name,
        )
        return user

    def validate_email(self, value):
        email = value
        if email and User.objects.filter(email=email).exists():
            raise serializers.ValidationError("Email already exists.")
        return value

    def validate_password(self, value):
        password = value
        if len(password) < 8:
            raise serializers.ValidationError(
                "Password must be at least 8 characters long."
            )
        return value
class SecurityQuestionSerializer(serializers.ModelSerializer):
    class Meta:
        from .models import SecurityQuestion
        model = SecurityQuestion
        fields = "__all__"


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        # The frontend sends email in the username field
        username = attrs.get('username')
        password = attrs.get('password')

        if username and '@' in username:
            try:
                user = User.objects.get(email=username)
                attrs['username'] = user.username
            except User.DoesNotExist:
                pass

        data = super().validate(attrs)
        return data



from .models import Permission, Role, AccountMember, Account

class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ["permission_id", "description"]

class RoleSerializer(serializers.ModelSerializer):
    permissions = PermissionSerializer(many=True, read_only=True)
    
    class Meta:
        model = Role
        fields = ["id", "role_name", "permissions", "is_system_role"]

class UserSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name"]

class AccountMemberSerializer(serializers.ModelSerializer):
    user = UserSummarySerializer(read_only=True)
    role = RoleSerializer(read_only=True)
    role_id = serializers.PrimaryKeyRelatedField(
        queryset=Role.objects.all(), source="role", write_only=True
    )

    class Meta:
        model = AccountMember
        fields = ["id", "user", "role", "role_id", "joined_at", "is_accepted"]
