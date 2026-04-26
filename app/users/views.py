from datetime import datetime, timedelta, timezone
from typing import Dict

import jwt
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from jwt import ExpiredSignatureError, InvalidTokenError
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from config.services import supabase_client
from config.services.supabase_client import SupabaseConfigError

from .serializers import LoginSerializer, RefreshTokenSerializer, RegisterSerializer


def _extract_profile(row: Dict) -> Dict:
    if not row:
        return {"id": None, "email": None, "full_name": ""}
    return {
        "id": row.get("id_user"),
        "email": row.get("email_user"),
        "full_name": row.get("full_name_user") or "",
    }


def _jwt_secret() -> str:
    return getattr(settings, "JWT_SECRET", settings.SECRET_KEY)


def _jwt_algorithm() -> str:
    return getattr(settings, "JWT_ALGORITHM", "HS256")


def _create_tokens(user_profile: Dict) -> Dict:
    now = datetime.now(timezone.utc)
    user_id = user_profile["id"]
    email = user_profile.get("email")

    access_minutes = getattr(settings, "ACCESS_TOKEN_MINUTES", 60 * 24 * 7)
    refresh_days = getattr(settings, "REFRESH_TOKEN_DAYS", 30)

    access_payload = {
        "sub": user_id,
        "email": email,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=access_minutes)).timestamp()),
    }
    refresh_payload = {
        "sub": user_id,
        "email": email,
        "type": "refresh",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=refresh_days)).timestamp()),
    }

    return {
        "access": jwt.encode(access_payload, _jwt_secret(), algorithm=_jwt_algorithm()),
        "refresh": jwt.encode(refresh_payload, _jwt_secret(), algorithm=_jwt_algorithm()),
    }


def _decode_token(token: str, token_type: str) -> Dict:
    payload = jwt.decode(token, _jwt_secret(), algorithms=[_jwt_algorithm()])
    if payload.get("type") != token_type:
        raise InvalidTokenError("Token type khong hop le.")
    return payload


def _bearer_token(request):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    return auth_header.replace("Bearer ", "", 1).strip()


def _read_user_by_email(email: str):
    user_row, user_status = supabase_client.get_user_by_email(email)
    if user_status >= 400:
        return None, Response(
            {"message": "Khong doc duoc user table.", "error": user_row},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    return user_row, None


def _read_user_by_id(user_id: str):
    user_row, user_status = supabase_client.get_user_by_id(user_id)
    if user_status >= 400:
        return None, Response(
            {"message": "Khong doc duoc user table.", "error": user_row},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    if not user_row:
        return None, Response(
            {"message": "Nguoi dung khong ton tai."},
            status=status.HTTP_404_NOT_FOUND,
        )
    return user_row, None


class RegisterApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        email = data["email"].strip().lower()
        full_name = data.get("full_name", "").strip()

        try:
            existed, error_response = _read_user_by_email(email)
            if error_response:
                return error_response
            if existed:
                return Response(
                    {"message": "Email da ton tai."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            password_hash = make_password(data["password"])
            created_row, created_status = supabase_client.create_user(
                full_name=full_name,
                email=email,
                password_hash=password_hash,
                phone=data.get("phone", "").strip(),
                address=data.get("address", "").strip(),
                birthday=(str(data["birthday"]) if data.get("birthday") else ""),
            )
        except SupabaseConfigError as exc:
            return Response(
                {"message": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if created_status >= 400:
            return Response(
                {"message": "Dang ky that bai.", "error": created_row},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        profile = _extract_profile(created_row)
        if not profile.get("id"):
            # Neu Supabase khong tra row do cau hinh RLS/Prefer, doc lai theo email.
            refetched, error_response = _read_user_by_email(email)
            if error_response:
                return error_response
            profile = _extract_profile(refetched)

        if not profile.get("id"):
            return Response(
                {"message": "Dang ky thanh cong nhung khong lay duoc id_user."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        tokens = _create_tokens(profile)
        return Response(
            {
                "message": "Dang ky thanh cong.",
                "user": profile,
                "tokens": tokens,
            },
            status=status.HTTP_201_CREATED,
        )


class LoginApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        email = data["email"].strip().lower()
        raw_password = data["password"]

        try:
            user_row, error_response = _read_user_by_email(email)
            if error_response:
                return error_response
        except SupabaseConfigError as exc:
            return Response(
                {"message": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if not user_row:
            return Response(
                {"message": "Email hoac mat khau khong dung."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        stored_password = user_row.get("password_user") or ""
        valid_password = False
        if stored_password:
            # Ho tro du lieu cu luu plaintext, uu tien hash.
            if stored_password.startswith("pbkdf2_"):
                valid_password = check_password(raw_password, stored_password)
            else:
                valid_password = stored_password == raw_password

        if not valid_password:
            return Response(
                {"message": "Email hoac mat khau khong dung."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        profile = _extract_profile(user_row)
        if not profile.get("id"):
            return Response(
                {"message": "User data khong hop le (thieu id_user)."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        tokens = _create_tokens(profile)
        return Response(
            {
                "message": "Dang nhap thanh cong.",
                "user": profile,
                "tokens": tokens,
            },
            status=status.HTTP_200_OK,
        )


class MeApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        token = _bearer_token(request)
        if not token:
            return Response(
                {"message": "Thieu Bearer access token."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            payload = _decode_token(token, "access")
            user_id = payload.get("sub")
            if not user_id:
                raise InvalidTokenError("Token khong co sub.")

            user_row, error_response = _read_user_by_id(user_id)
            if error_response:
                return error_response
        except ExpiredSignatureError:
            return Response(
                {"message": "Access token het han."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        except InvalidTokenError as exc:
            return Response(
                {"message": f"Access token khong hop le: {exc}"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        except SupabaseConfigError as exc:
            return Response(
                {"message": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(_extract_profile(user_row), status=status.HTTP_200_OK)


class RefreshTokenApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = RefreshTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        refresh_token = serializer.validated_data["refresh_token"]

        try:
            payload = _decode_token(refresh_token, "refresh")
            user_id = payload.get("sub")
            if not user_id:
                raise InvalidTokenError("Refresh token khong co sub.")

            user_row, error_response = _read_user_by_id(user_id)
            if error_response:
                return error_response
        except ExpiredSignatureError:
            return Response(
                {"message": "Refresh token het han."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        except InvalidTokenError as exc:
            return Response(
                {"message": f"Refresh token khong hop le: {exc}"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        except SupabaseConfigError as exc:
            return Response(
                {"message": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        profile = _extract_profile(user_row)
        if not profile.get("id"):
            return Response(
                {"message": "User data khong hop le (thieu id_user)."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        tokens = _create_tokens(profile)
        return Response(
            {
                "message": "Lam moi token thanh cong.",
                "tokens": tokens,
                "user": profile,
            },
            status=status.HTTP_200_OK,
        )
