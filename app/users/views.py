import json
import smtplib
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict
from uuid import uuid4

import firebase_admin
import jwt
from django.conf import settings
from django.contrib.auth.hashers import check_password, identify_hasher, make_password
from django.core.mail import get_connection, send_mail
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.http import HttpResponse
from django.urls import reverse
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials as firebase_credentials
from firebase_admin import exceptions as firebase_exceptions
from jwt import ExpiredSignatureError, InvalidTokenError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from config.services import supabase_client
from config.services.supabase_client import SupabaseConfigError

from .serializers import ChangePasswordSerializer, ForgotPasswordSerializer, GoogleLoginSerializer, LoginSerializer, RefreshTokenSerializer, RegisterSerializer, ResetPasswordSerializer, UpdateProfileSerializer


def _extract_first_error(errors) -> str:
    if isinstance(errors, dict):
        for value in errors.values():
            if isinstance(value, list) and value:
                return str(value[0])
            if isinstance(value, dict):
                nested = _extract_first_error(value)
                if nested:
                    return nested
            if isinstance(value, str):
                return value
    elif isinstance(errors, list) and errors:
        return str(errors[0])
    elif isinstance(errors, str):
        return errors
    return "Du lieu khong hop le."


def _serializer_error_response(serializer, fallback_message: str = "Du lieu khong hop le."):
    message = _extract_first_error(serializer.errors) or fallback_message
    return Response(
        {
            "message": message,
            "errors": serializer.errors,
        },
        status=status.HTTP_400_BAD_REQUEST,
    )


def _extract_profile(row: Dict) -> Dict:
    if not row:
        return {
            "id": None,
            "id_user": None,
            "email": None,
            "email_user": None,
            "full_name": "",
            "full_name_user": "",
            "phone": "",
            "phone_user": "",
            "address": "",
            "address_user": "",
            "birthday": "",
            "birthday_user": "",
            "avatar_url": "",
            "created_at": None,
            "is_profile_complete": False,
        }
    phone = row.get("phone_user") or ""
    address = row.get("address_user") or ""
    birthday = row.get("birthday_user") or ""
    return {
        "id": row.get("id_user"),
        "id_user": row.get("id_user"),
        "email": row.get("email_user"),
        "email_user": row.get("email_user"),
        "full_name": row.get("full_name_user") or "",
        "full_name_user": row.get("full_name_user") or "",
        "phone": phone,
        "phone_user": phone,
        "address": address,
        "address_user": address,
        "birthday": birthday,
        "birthday_user": birthday,
        "avatar_url": row.get("avatar_url") or "",
        "created_at": row.get("created_at"),
        "is_profile_complete": bool(phone and address and birthday),
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


def _is_duplicate_email_error(payload: Dict) -> bool:
    if not isinstance(payload, dict):
        return False
    code = str(payload.get("code", "")).strip()
    message = str(payload.get("message", "")).lower()
    details = str(payload.get("details", "")).lower()
    if code == "23505":
        return True
    if "duplicate key value" in message:
        return True
    if "email_user" in message or "email_user" in details:
        return True
    return False


def _is_hashed_password(value: str) -> bool:
    if not value:
        return False
    try:
        identify_hasher(value)
        return True
    except ValueError:
        return False


def _hash_password(raw_password: str) -> str:
    return make_password(raw_password)


def _verify_password(raw_password: str, stored_password: str) -> bool:
    if not raw_password or not stored_password:
        return False
    if _is_hashed_password(stored_password):
        return check_password(raw_password, stored_password)
    return stored_password == raw_password


def _upgrade_plain_password_if_needed(user_id: str, raw_password: str, stored_password: str) -> None:
    if not stored_password or _is_hashed_password(stored_password):
        return
    try:
        supabase_client.update_user_profile(
            str(user_id),
            {"password_user": _hash_password(raw_password)},
        )
    except Exception:
        pass


def _reset_signer() -> TimestampSigner:
    return TimestampSigner(salt="studyassistant.password-reset")


def _make_password_reset_token(user_row: Dict) -> str:
    payload = {
        "id_user": user_row.get("id_user"),
        "email_user": user_row.get("email_user"),
    }
    return _reset_signer().sign_object(payload)


def _read_password_reset_token(token: str) -> Dict:
    max_age = getattr(settings, "PASSWORD_RESET_TOKEN_MINUTES", 30) * 60
    return _reset_signer().unsign_object(token, max_age=max_age)


def _password_reset_link(request, token: str) -> str:
    path = reverse("users-password-reset-confirm")
    if getattr(settings, "BACKEND_PUBLIC_URL", ""):
        return f"{settings.BACKEND_PUBLIC_URL}{path}?token={token}"
    return request.build_absolute_uri(f"{path}?token={token}")


def _password_reset_html(token: str, message: str = "", is_error: bool = False) -> str:
    color = "#dc2626" if is_error else "#0e62cf"
    return f"""
<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Dat lai mat khau</title>
  <style>
    body {{ margin:0; font-family:Arial, sans-serif; background:#f5f7ff; color:#111827; }}
    .wrap {{ min-height:100vh; display:flex; align-items:center; justify-content:center; padding:24px; }}
    .card {{ width:100%; max-width:420px; background:#fff; border-radius:18px; padding:28px; box-shadow:0 18px 45px rgba(15,23,42,.12); }}
    h1 {{ margin:0 0 10px; font-size:26px; }}
    p {{ color:#4b5563; line-height:1.55; }}
    label {{ display:block; margin:16px 0 8px; font-weight:700; }}
    input {{ box-sizing:border-box; width:100%; height:48px; border:1px solid #cbd5e1; border-radius:12px; padding:0 14px; font-size:16px; }}
    button {{ width:100%; height:50px; margin-top:20px; border:0; border-radius:999px; background:#0e62cf; color:#fff; font-size:16px; font-weight:700; cursor:pointer; }}
    .msg {{ color:{color}; font-weight:700; }}
  </style>
</head>
<body>
  <main class="wrap">
    <form class="card" method="post">
      <h1>Dat lai mat khau</h1>
      <p>Nhap mat khau moi cho tai khoan Lumio Study cua ban.</p>
      {"<p class='msg'>" + message + "</p>" if message else ""}
      <input type="hidden" name="token" value="{token}">
      <label>Mat khau moi</label>
      <input name="new_password" type="password" minlength="6" required>
      <label>Xac nhan mat khau</label>
      <input name="confirm_password" type="password" minlength="6" required>
      <button type="submit">Cap nhat mat khau</button>
    </form>
  </main>
</body>
</html>
"""


def _email_error_message(exc: Exception) -> str:
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return (
            "Gmail SMTP tu choi dang nhap. Hay kiem tra EMAIL_HOST_USER va "
            "EMAIL_HOST_PASSWORD phai la Google App Password 16 ky tu."
        )
    if isinstance(exc, (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, TimeoutError, socket.timeout)):
        return "Khong ket noi duoc Gmail SMTP. Hay thu EMAIL_PORT=465, EMAIL_USE_SSL=True, EMAIL_USE_TLS=False."
    if isinstance(exc, OSError):
        return (
            "Server khong mo duoc ket noi toi Gmail SMTP. Neu dang deploy tren hosting, "
            "hay thu port 465 SSL; neu van loi thi hosting dang chan outbound SMTP."
        )
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "Dia chi email nguoi nhan bi Gmail tu choi."
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return "Dia chi nguoi gui bi Gmail tu choi. DEFAULT_FROM_EMAIL nen trung voi EMAIL_HOST_USER."
    if isinstance(exc, smtplib.SMTPException):
        return f"Gmail SMTP loi: {exc}"
    return f"Khong gui duoc email dat lai mat khau: {exc}"


def _firebase_app():
    try:
        return firebase_admin.get_app()
    except ValueError:
        raw_json = getattr(settings, "FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
        if raw_json:
            try:
                service_account = json.loads(raw_json)
            except json.JSONDecodeError as exc:
                raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_JSON khong hop le.") from exc
            cred = firebase_credentials.Certificate(service_account)
            return firebase_admin.initialize_app(cred)
        return firebase_admin.initialize_app()


def _auth_response(profile: Dict, message: str, response_status: int, is_new_user: bool = False) -> Response:
    tokens = _create_tokens(profile)
    return Response(
        {
            "message": message,
            "user": profile,
            "id_user": profile.get("id"),
            "email_user": profile.get("email"),
            "full_name_user": profile.get("full_name"),
            "tokens": tokens,
            "is_new_user": is_new_user,
        },
        status=response_status,
    )


class RegisterApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Du lieu dang ky khong hop le.")
        data = serializer.validated_data

        email = data["email"].strip().lower()
        full_name = data.get("full_name", "").strip()

        try:
            existed, error_response = _read_user_by_email(email)
            if error_response:
                return error_response
            if existed:
                return Response(
                    {
                        "message": "Email da ton tai. Vui long dung email khac.",
                        "errors": {"email": ["Email da ton tai. Vui long dung email khac."]},
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            password_value = _hash_password(data["password"])
            created_row, created_status = supabase_client.create_user(
                full_name=full_name,
                email=email,
                password_value=password_value,
                phone=data.get("phone", "").strip(),
                address=data.get("address", "").strip(),
                birthday=(str(data["birthday"]) if data.get("birthday") else ""),
            )
        except SupabaseConfigError as exc:
            return Response(
                {"message": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if _is_duplicate_email_error(created_row):
            return Response(
                {
                    "message": "Email da ton tai. Vui long dung email khac.",
                    "errors": {"email": ["Email da ton tai. Vui long dung email khac."]},
                },
                status=status.HTTP_400_BAD_REQUEST,
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
                "id_user": profile.get("id"),
                "email_user": profile.get("email"),
                "full_name_user": profile.get("full_name"),
                "tokens": tokens,
            },
            status=status.HTTP_201_CREATED,
        )


class LoginApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Du lieu dang nhap khong hop le.")
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
                {
                    "message": "Email hoac mat khau khong dung.",
                    "errors": {"email": ["Email hoac mat khau khong dung."]},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        stored_password = user_row.get("password_user") or ""
        valid_password = _verify_password(raw_password, stored_password)

        if not valid_password:
            return Response(
                {
                    "message": "Email hoac mat khau khong dung.",
                    "errors": {"email": ["Email hoac mat khau khong dung."]},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        profile = _extract_profile(user_row)
        if not profile.get("id"):
            return Response(
                {"message": "User data khong hop le (thieu id_user)."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        _upgrade_plain_password_if_needed(str(profile.get("id")), raw_password, stored_password)
        tokens = _create_tokens(profile)
        return Response(
            {
                "message": "Dang nhap thanh cong.",
                "user": profile,
                "id_user": profile.get("id"),
                "email_user": profile.get("email"),
                "full_name_user": profile.get("full_name"),
                "tokens": tokens,
            },
            status=status.HTTP_200_OK,
        )


class GoogleLoginApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = GoogleLoginSerializer(data=request.data)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Google ID token khong hop le.")

        id_token = serializer.validated_data["id_token"]
        try:
            _firebase_app()
            decoded = firebase_auth.verify_id_token(id_token)
        except (
            firebase_auth.ExpiredIdTokenError,
            firebase_auth.InvalidIdTokenError,
            firebase_auth.RevokedIdTokenError,
            firebase_auth.CertificateFetchError,
            ValueError,
        ) as exc:
            return Response(
                {"message": f"Google ID token khong hop le: {exc}"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        except (firebase_exceptions.FirebaseError, RuntimeError) as exc:
            return Response(
                {"message": f"Khong the xac thuc Firebase: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        email = str(decoded.get("email") or "").strip().lower()
        if not email:
            return Response(
                {"message": "Tai khoan Google khong co email."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        full_name = str(decoded.get("name") or decoded.get("display_name") or "").strip()
        if not full_name:
            full_name = email.split("@", 1)[0]

        is_new_user = False
        try:
            user_row, error_response = _read_user_by_email(email)
            if error_response:
                return error_response

            if not user_row:
                is_new_user = True
                created_row, created_status = supabase_client.create_user(
                    full_name=full_name,
                    email=email,
                    password_value=_hash_password(uuid4().hex),
                )
                if _is_duplicate_email_error(created_row):
                    user_row, error_response = _read_user_by_email(email)
                    if error_response:
                        return error_response
                elif created_status >= 400:
                    return Response(
                        {"message": "Tao user Google that bai.", "error": created_row},
                        status=status.HTTP_502_BAD_GATEWAY,
                    )
                else:
                    user_row = created_row

                if not user_row:
                    refetched, error_response = _read_user_by_email(email)
                    if error_response:
                        return error_response
                    user_row = refetched
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

        return _auth_response(
            profile,
            "Dang nhap Google thanh cong.",
            status.HTTP_200_OK,
            is_new_user=is_new_user,
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


class UserProfileApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, user_id):
        try:
            user_row, error_response = _read_user_by_id(str(user_id))
            if error_response:
                return error_response
        except SupabaseConfigError as exc:
            return Response(
                {"message": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(_extract_profile(user_row), status=status.HTTP_200_OK)

    def patch(self, request, user_id):
        serializer = UpdateProfileSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Thong tin cap nhat khong hop le.")

        data = serializer.validated_data
        fields = {}
        if "full_name" in data:
            fields["full_name_user"] = data.get("full_name", "").strip()
        if "email" in data:
            fields["email_user"] = data.get("email", "").strip().lower()
        if "phone" in data:
            fields["phone_user"] = data.get("phone", "").strip() or None
        if "address" in data:
            fields["address_user"] = data.get("address", "").strip() or None
        if "birthday" in data:
            fields["birthday_user"] = data.get("birthday", "").strip() or None

        if not fields:
            user_row, error_response = _read_user_by_id(str(user_id))
            if error_response:
                return error_response
            return Response(_extract_profile(user_row), status=status.HTTP_200_OK)

        try:
            updated_row, update_status = supabase_client.update_user_profile(str(user_id), fields)
        except SupabaseConfigError as exc:
            return Response(
                {"message": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if _is_duplicate_email_error(updated_row):
            return Response(
                {
                    "message": "Email da ton tai. Vui long dung email khac.",
                    "errors": {"email": ["Email da ton tai. Vui long dung email khac."]},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if update_status >= 400:
            return Response(
                {"message": "Cap nhat ho so that bai.", "error": updated_row},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if not updated_row or not updated_row.get("id_user"):
            updated_row, error_response = _read_user_by_id(str(user_id))
            if error_response:
                return error_response

        return Response(_extract_profile(updated_row), status=status.HTTP_200_OK)


class UserAvatarApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, user_id):
        upload = request.FILES.get("file")
        if not upload:
            return Response({"message": "Thieu file anh."}, status=status.HTTP_400_BAD_REQUEST)

        file_name = str(upload.name or "avatar.jpg")
        ext = Path(file_name).suffix.lower()
        allowed_exts = {".jpg", ".jpeg", ".png", ".webp"}
        if ext not in allowed_exts:
            return Response(
                {"message": "Chi ho tro anh JPG, PNG hoac WEBP."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        mime_type = upload.content_type or "application/octet-stream"
        allowed_mimes = {"image/jpeg", "image/png", "image/webp"}
        if mime_type not in allowed_mimes:
            return Response(
                {"message": "Dinh dang anh khong hop le."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if upload.size > 5 * 1024 * 1024:
            return Response({"message": "Anh vuot qua 5MB."}, status=status.HTTP_400_BAD_REQUEST)

        safe_ext = ".jpg" if ext == ".jpeg" else ext
        storage_path = f"{user_id}/{uuid4().hex}{safe_ext}"
        bucket = getattr(settings, "SUPABASE_AVATAR_BUCKET", "avatar")

        try:
            file_bytes = upload.read()
            if not file_bytes:
                return Response({"message": "Anh rong hoac khong doc duoc."}, status=status.HTTP_400_BAD_REQUEST)

            storage_payload, storage_status = supabase_client.upload_storage_file(
                bucket=bucket,
                object_path=storage_path,
                file_bytes=file_bytes,
                content_type=mime_type,
            )
            if storage_status >= 400:
                return Response(
                    {"message": "Upload avatar len Storage that bai.", "error": storage_payload},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            avatar_url = supabase_client.public_storage_url(bucket=bucket, object_path=storage_path)
            updated_row, update_status = supabase_client.update_user_profile(
                str(user_id),
                {"avatar_url": avatar_url},
            )
            if update_status >= 400:
                return Response(
                    {"message": "Luu avatar vao user that bai.", "error": updated_row},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            if not updated_row or not updated_row.get("id_user"):
                updated_row, error_response = _read_user_by_id(str(user_id))
                if error_response:
                    return error_response

            return Response(
                {
                    "message": "Cap nhat avatar thanh cong.",
                    "avatar_url": avatar_url,
                    "user": _extract_profile(updated_row),
                },
                status=status.HTTP_200_OK,
            )
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ForgotPasswordApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Email khong hop le.")

        email = serializer.validated_data["email"]
        generic_message = "Neu email ton tai, lien ket dat lai mat khau da duoc gui."

        try:
            user_row, error_response = _read_user_by_email(email)
            if error_response:
                return error_response
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if not user_row:
            return Response({"message": generic_message}, status=status.HTTP_200_OK)

        token = _make_password_reset_token(user_row)
        reset_link = _password_reset_link(request, token)
        subject = "Dat lai mat khau Lumio Study"
        message = (
            "Ban vua yeu cau dat lai mat khau Lumio Study.\n\n"
            f"Nhan vao lien ket sau de tao mat khau moi:\n{reset_link}\n\n"
            f"Lien ket co hieu luc trong {getattr(settings, 'PASSWORD_RESET_TOKEN_MINUTES', 30)} phut.\n"
            "Neu ban khong yeu cau, hay bo qua email nay."
        )

        try:
            if not getattr(settings, "EMAIL_HOST_USER", "") or not getattr(settings, "EMAIL_HOST_PASSWORD", ""):
                return Response(
                    {"message": "Backend chua cau hinh EMAIL_HOST_USER hoac EMAIL_HOST_PASSWORD."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
            connection = get_connection(timeout=getattr(settings, "EMAIL_TIMEOUT", 10))
            send_mail(
                subject=subject,
                message=message,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                recipient_list=[email],
                fail_silently=False,
                connection=connection,
            )
        except Exception as exc:
            return Response(
                {"message": _email_error_message(exc), "error": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({"message": generic_message}, status=status.HTTP_200_OK)


class ResetPasswordApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        token = request.query_params.get("token", "")
        return HttpResponse(_password_reset_html(token), content_type="text/html; charset=utf-8")

    def post(self, request):
        data = request.data if request.content_type == "application/json" else request.POST
        serializer = ResetPasswordSerializer(data=data)
        if not serializer.is_valid():
            message = _extract_first_error(serializer.errors)
            if data.get("token"):
                return HttpResponse(
                    _password_reset_html(data.get("token", ""), message, is_error=True),
                    status=status.HTTP_400_BAD_REQUEST,
                    content_type="text/html; charset=utf-8",
                )
            return _serializer_error_response(serializer, "Thong tin dat lai mat khau khong hop le.")

        token = serializer.validated_data["token"]
        try:
            payload = _read_password_reset_token(token)
        except SignatureExpired:
            message = "Lien ket dat lai mat khau da het han."
            return HttpResponse(
                _password_reset_html(token, message, is_error=True),
                status=status.HTTP_400_BAD_REQUEST,
                content_type="text/html; charset=utf-8",
            )
        except BadSignature:
            message = "Lien ket dat lai mat khau khong hop le."
            return HttpResponse(
                _password_reset_html("", message, is_error=True),
                status=status.HTTP_400_BAD_REQUEST,
                content_type="text/html; charset=utf-8",
            )

        user_id = payload.get("id_user")
        email = payload.get("email_user")
        if not user_id or not email:
            message = "Lien ket dat lai mat khau khong hop le."
            return HttpResponse(
                _password_reset_html("", message, is_error=True),
                status=status.HTTP_400_BAD_REQUEST,
                content_type="text/html; charset=utf-8",
            )

        try:
            user_row, error_response = _read_user_by_id(str(user_id))
            if error_response:
                return error_response
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if (user_row.get("email_user") or "").strip().lower() != str(email).strip().lower():
            message = "Lien ket dat lai mat khau khong con hop le."
            return HttpResponse(
                _password_reset_html("", message, is_error=True),
                status=status.HTTP_400_BAD_REQUEST,
                content_type="text/html; charset=utf-8",
            )

        try:
            updated_row, update_status = supabase_client.update_user_profile(
                str(user_id),
                {"password_user": _hash_password(serializer.validated_data["new_password"])},
            )
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if update_status >= 400:
            return Response(
                {"message": "Dat lai mat khau that bai.", "error": updated_row},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return HttpResponse(
            _password_reset_html("", "Dat lai mat khau thanh cong. Ban co the quay lai app de dang nhap."),
            content_type="text/html; charset=utf-8",
        )


class ChangePasswordApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def patch(self, request, user_id):
        serializer = ChangePasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Thong tin mat khau khong hop le.")

        data = serializer.validated_data

        try:
            user_row, error_response = _read_user_by_id(str(user_id))
            if error_response:
                return error_response
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        stored_password = user_row.get("password_user") or ""
        if not _verify_password(data["current_password"], stored_password):
            return Response(
                {
                    "message": "Mat khau hien tai khong dung.",
                    "errors": {"current_password": ["Mat khau hien tai khong dung."]},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            updated_row, update_status = supabase_client.update_user_profile(
                str(user_id),
                {"password_user": _hash_password(data["new_password"])},
            )
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if update_status >= 400:
            return Response(
                {"message": "Doi mat khau that bai.", "error": updated_row},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({"message": "Doi mat khau thanh cong."}, status=status.HTTP_200_OK)


class RefreshTokenApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = RefreshTokenSerializer(data=request.data)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Refresh token khong hop le.")
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
                "id_user": profile.get("id"),
                "email_user": profile.get("email"),
                "full_name_user": profile.get("full_name"),
            },
            status=status.HTTP_200_OK,
        )
