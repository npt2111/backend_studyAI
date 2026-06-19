from rest_framework import serializers


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField(
        error_messages={
            "required": "Vui long nhap email.",
            "blank": "Vui long nhap email.",
            "invalid": "Email khong hop le.",
        }
    )
    password = serializers.CharField(
        write_only=True,
        min_length=6,
        error_messages={
            "required": "Vui long nhap mat khau.",
            "blank": "Vui long nhap mat khau.",
            "min_length": "Mat khau phai co it nhat 6 ky tu.",
        },
    )
    full_name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=150,
        error_messages={
            "max_length": "Ho ten khong duoc vuot qua 150 ky tu.",
        },
    )
    phone = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=30,
        error_messages={
            "max_length": "So dien thoai khong duoc vuot qua 30 ky tu.",
        },
    )
    address = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=1000,
        error_messages={
            "max_length": "Dia chi khong duoc vuot qua 1000 ky tu.",
        },
    )
    birthday = serializers.DateField(
        required=False,
        allow_null=True,
        error_messages={
            "invalid": "Ngay sinh phai theo dinh dang YYYY-MM-DD.",
        },
    )

    def validate_email(self, value):
        return value.strip().lower()


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(
        error_messages={
            "required": "Vui long nhap email.",
            "blank": "Vui long nhap email.",
            "invalid": "Email khong hop le.",
        }
    )
    password = serializers.CharField(
        write_only=True,
        error_messages={
            "required": "Vui long nhap mat khau.",
            "blank": "Vui long nhap mat khau.",
        },
    )

    def validate_email(self, value):
        return value.strip().lower()


class GoogleLoginSerializer(serializers.Serializer):
    id_token = serializers.CharField(
        error_messages={
            "required": "Thieu Google ID token.",
            "blank": "Thieu Google ID token.",
        }
    )


class RefreshTokenSerializer(serializers.Serializer):
    refresh_token = serializers.CharField(
        error_messages={
            "required": "Thieu refresh token.",
            "blank": "Thieu refresh token.",
        }
    )


class UpdateProfileSerializer(serializers.Serializer):
    full_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    email = serializers.EmailField(required=False)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=30)
    address = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    birthday = serializers.CharField(required=False, allow_blank=True, max_length=10)

    def validate_email(self, value):
        return value.strip().lower()

    def validate_birthday(self, value):
        text = value.strip()
        if not text:
            return ""
        try:
            serializers.DateField().to_internal_value(text)
        except serializers.ValidationError:
            raise serializers.ValidationError("Ngay sinh phai theo dinh dang YYYY-MM-DD.")
        return text


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(
        error_messages={
            "required": "Vui long nhap mat khau hien tai.",
            "blank": "Vui long nhap mat khau hien tai.",
        }
    )
    new_password = serializers.CharField(
        min_length=6,
        error_messages={
            "required": "Vui long nhap mat khau moi.",
            "blank": "Vui long nhap mat khau moi.",
            "min_length": "Mat khau moi phai co it nhat 6 ky tu.",
        },
    )
    confirm_password = serializers.CharField(
        error_messages={
            "required": "Vui long xac nhan mat khau moi.",
            "blank": "Vui long xac nhan mat khau moi.",
        }
    )

    def validate(self, attrs):
        if attrs["current_password"] == attrs["new_password"]:
            raise serializers.ValidationError(
                {"new_password": ["Mat khau moi khong duoc trung mat khau hien tai."]}
            )
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError(
                {"confirm_password": ["Xac nhan mat khau khong trung khop."]}
            )
        return attrs


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField(
        error_messages={
            "required": "Vui long nhap email.",
            "blank": "Vui long nhap email.",
            "invalid": "Email khong hop le.",
        }
    )

    def validate_email(self, value):
        return value.strip().lower()


class ResetPasswordSerializer(serializers.Serializer):
    token = serializers.CharField(
        error_messages={
            "required": "Thieu ma xac thuc.",
            "blank": "Thieu ma xac thuc.",
        }
    )
    new_password = serializers.CharField(
        min_length=6,
        error_messages={
            "required": "Vui long nhap mat khau moi.",
            "blank": "Vui long nhap mat khau moi.",
            "min_length": "Mat khau moi phai co it nhat 6 ky tu.",
        },
    )
    confirm_password = serializers.CharField(
        error_messages={
            "required": "Vui long xac nhan mat khau moi.",
            "blank": "Vui long xac nhan mat khau moi.",
        }
    )

    def validate(self, attrs):
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError(
                {"confirm_password": ["Xac nhan mat khau khong trung khop."]}
            )
        return attrs
