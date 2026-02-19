from rest_framework import serializers
from django.contrib.auth import get_user_model

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
