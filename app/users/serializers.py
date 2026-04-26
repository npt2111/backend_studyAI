from django.contrib.auth import authenticate, get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


def user_to_dict(user):
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "full_name": user.get_full_name() or user.username,
    }


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=6)
    full_name = serializers.CharField(required=False, allow_blank=True, max_length=150)

    def validate_email(self, value):
        email = value.lower().strip()
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError("Email da ton tai.")
        return email

    def create(self, validated_data):
        email = validated_data["email"]
        password = validated_data["password"]
        full_name = validated_data.get("full_name", "").strip()

        first_name = ""
        last_name = ""
        if full_name:
            parts = full_name.split()
            first_name = parts[0]
            last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

        # Su dung email lam username de Android login bang email/password don gian.
        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
        )

        refresh = RefreshToken.for_user(user)
        return {
            "message": "Dang ky thanh cong.",
            "user": user_to_dict(user),
            "tokens": {
                "refresh": str(refresh),
                "access": str(refresh.access_token),
            },
        }


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs["email"].lower().strip()
        password = attrs["password"]
        request = self.context.get("request")

        user = authenticate(request=request, username=email, password=password)
        if not user:
            raise serializers.ValidationError("Email hoac mat khau khong dung.")

        refresh = RefreshToken.for_user(user)
        return {
            "message": "Dang nhap thanh cong.",
            "user": user_to_dict(user),
            "tokens": {
                "refresh": str(refresh),
                "access": str(refresh.access_token),
            },
        }
