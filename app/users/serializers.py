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
