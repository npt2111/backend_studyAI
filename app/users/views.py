from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from config.services import supabase_client
from config.services.supabase_client import SupabaseConfigError

from .serializers import LoginSerializer, RefreshTokenSerializer, RegisterSerializer


def _extract_auth_payload(payload):
    user = payload.get("user") or payload.get("session", {}).get("user") or {}
    access = payload.get("access_token") or payload.get("session", {}).get("access_token")
    refresh = payload.get("refresh_token") or payload.get("session", {}).get("refresh_token")
    user_metadata = user.get("user_metadata") or {}
    full_name = (
        user_metadata.get("full_name")
        or user_metadata.get("name")
        or user.get("email")
        or ""
    )
    return {
        "user": {
            "id": user.get("id"),
            "email": user.get("email"),
            "full_name": full_name,
        },
        "tokens": {
            "access": access,
            "refresh": refresh,
        },
    }


def _extract_profile(payload):
    if not payload:
        return {
            "id": None,
            "email": None,
            "full_name": "",
        }

    return {
        "id": payload.get("id") or payload.get("user_id"),
        "email": payload.get("email"),
        "full_name": payload.get("full_name")
        or payload.get("name")
        or payload.get("display_name")
        or "",
    }


def _bearer_token(request):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    return auth_header.replace("Bearer ", "", 1).strip()


class RegisterApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        email = data["email"].lower().strip()
        full_name = data.get("full_name", "").strip()

        try:
            signup_payload, signup_status = supabase_client.signup(
                email=email,
                password=data["password"],
                full_name=full_name,
            )
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if signup_status >= 400:
            return Response(
                {
                    "message": "Dang ky that bai.",
                    "error": signup_payload,
                },
                status=signup_status,
            )

        mapped = _extract_auth_payload(signup_payload)

        # Truong hop Supabase signup chua tra session (vi bat email confirm)
        if not mapped["tokens"]["access"] or not mapped["tokens"]["refresh"]:
            login_payload, login_status = supabase_client.login(
                email=email,
                password=data["password"],
            )
            if login_status < 400:
                mapped = _extract_auth_payload(login_payload)

        profile = mapped["user"]
        user_id = mapped["user"].get("id")

        if user_id:
            profile_payload, profile_status = supabase_client.upsert_profile(
                user_id=user_id,
                email=email,
                full_name=full_name,
            )
            if profile_status < 400:
                profile = _extract_profile(profile_payload)
            else:
                # Dang ky auth thanh cong, nhung profile table chua dong bo duoc.
                profile["profile_sync_error"] = profile_payload

        return Response(
            {
                "message": "Dang ky thanh cong.",
                "user": profile,
                "tokens": mapped["tokens"],
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

        try:
            payload, supabase_status = supabase_client.login(
                email=data["email"].lower().strip(),
                password=data["password"],
            )
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if supabase_status >= 400:
            return Response(
                {
                    "message": "Dang nhap that bai.",
                    "error": payload,
                },
                status=supabase_status,
            )

        mapped = _extract_auth_payload(payload)
        profile = mapped["user"]

        user_id = mapped["user"].get("id")
        if user_id:
            profile_payload, profile_status = supabase_client.get_profile_by_auth_id(user_id)
            if profile_status < 400 and profile_payload:
                profile = _extract_profile(profile_payload)
            else:
                profile_payload, profile_status = supabase_client.get_profile_by_email(
                    mapped["user"].get("email", "")
                )
                if profile_status < 400 and profile_payload:
                    profile = _extract_profile(profile_payload)

        return Response(
            {
                "message": "Dang nhap thanh cong.",
                "user": profile,
                "tokens": mapped["tokens"],
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
            payload, supabase_status = supabase_client.get_user(access_token=token)
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if supabase_status >= 400:
            return Response(
                {"message": "Token khong hop le.", "error": payload},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        user_id = payload.get("id")
        email = payload.get("email")
        user_metadata = payload.get("user_metadata") or {}
        profile = {
            "id": user_id,
            "email": email,
            "full_name": user_metadata.get("full_name") or user_metadata.get("name") or "",
        }

        if user_id:
            profile_payload, profile_status = supabase_client.get_profile_by_auth_id(user_id)
            if profile_status < 400 and profile_payload:
                profile = _extract_profile(profile_payload)
            elif email:
                profile_payload, profile_status = supabase_client.get_profile_by_email(email)
                if profile_status < 400 and profile_payload:
                    profile = _extract_profile(profile_payload)

        return Response(
            profile,
            status=status.HTTP_200_OK,
        )


class RefreshTokenApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = RefreshTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        refresh_token = serializer.validated_data["refresh_token"]

        try:
            payload, supabase_status = supabase_client.refresh_session(refresh_token=refresh_token)
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if supabase_status >= 400:
            return Response(
                {"message": "Refresh token that bai.", "error": payload},
                status=supabase_status,
            )

        mapped = _extract_auth_payload(payload)
        profile = mapped["user"]
        user_id = mapped["user"].get("id")
        if user_id:
            profile_payload, profile_status = supabase_client.get_profile_by_auth_id(user_id)
            if profile_status < 400 and profile_payload:
                profile = _extract_profile(profile_payload)
            else:
                profile_payload, profile_status = supabase_client.get_profile_by_email(
                    mapped["user"].get("email", "")
                )
                if profile_status < 400 and profile_payload:
                    profile = _extract_profile(profile_payload)

        return Response(
            {
                "message": "Lam moi token thanh cong.",
                "tokens": mapped["tokens"],
                "user": profile,
            },
            status=status.HTTP_200_OK,
        )
