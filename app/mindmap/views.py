import logging

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from config.services import supabase_client
from config.services.supabase_client import SupabaseConfigError
from app.documents.rag import build_ai_generation_context

from .serializers import MindmapGenerateSerializer
from .services import generate_mindmap, normalize_mindmap

logger = logging.getLogger(__name__)


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
    return "Du lieu khong hop le."


def _public_ai_error(raw: str) -> str:
    text = str(raw or "")
    lowered = text.lower()
    if (
        "gemini" in lowered
        or "groq" in lowered
        or "unavailable" in lowered
        or "high demand" in lowered
        or "rate limit" in lowered
        or "rate_limit" in lowered
        or "quota" in lowered
        or "503" in lowered
        or "429" in lowered
    ):
        return "AI dang qua tai, vui long thu lai sau it phut."
    return text if text else "Tao mindmap that bai."


class GenerateMindmapApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = MindmapGenerateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"message": _extract_first_error(serializer.errors), "errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_id = str(serializer.validated_data["user_id"])
        read_id = str(serializer.validated_data["read_id"])
        try:
            cached_row, cached_status = supabase_client.get_mindmap_by_read_id(read_id)
            if cached_status < 400 and cached_row and str(cached_row.get("id_user")) == user_id:
                if str(cached_row.get("status")) == "done" and str(cached_row.get("markdown") or "").strip():
                    return Response(
                        {"message": "Lay mindmap tu cache.", "mindmap": normalize_mindmap(cached_row), "cached": True},
                        status=status.HTTP_200_OK,
                    )

            read_row, read_status = supabase_client.get_document_read_result(read_id)
            if read_status >= 400:
                return Response({"message": "Khong doc duoc ket qua doc file."}, status=status.HTTP_502_BAD_GATEWAY)
            if not read_row:
                return Response({"message": "Khong tim thay ket qua doc file."}, status=status.HTTP_404_NOT_FOUND)
            if str(read_row.get("id_user")) != user_id:
                return Response({"message": "Ban khong co quyen tao mindmap tu file nay."}, status=status.HTTP_403_FORBIDDEN)
            if str(read_row.get("status", "")).lower() != "done":
                return Response({"message": "File chua doc xong nen chua the tao mindmap."}, status=status.HTTP_409_CONFLICT)

            source_text = str(read_row.get("extracted_text") or "").strip()
            if not source_text:
                return Response({"message": "File khong co extracted_text de tao mindmap."}, status=status.HTTP_400_BAD_REQUEST)
            file_name = str(read_row.get("file_name") or "Document")
            ai_source_text = source_text
            try:
                ai_source_text = build_ai_generation_context(
                    user_id=user_id,
                    read_id=read_id,
                    source_text=source_text,
                    file_name=file_name,
                    purpose="mindmap",
                    max_chars=int(getattr(settings, "MINDMAP_SOURCE_MAX_CHARS", 18000)),
                )
            except Exception as exc:
                logger.warning("Mindmap AI context fallback for read_id=%s: %s", read_id, exc)

            mindmap_row = cached_row if cached_row else None
            if not mindmap_row:
                mindmap_row, create_status = supabase_client.create_mindmap(
                    user_id=user_id,
                    read_id=read_id,
                    file_name=file_name,
                )
                if create_status >= 400:
                    return Response({"message": "Tao mindmap record that bai.", "error": mindmap_row}, status=status.HTTP_502_BAD_GATEWAY)

            mindmap_id = str(mindmap_row.get("id_mindmap") or "").strip()
            if not mindmap_id:
                return Response({"message": "Mindmap record thieu id_mindmap."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            try:
                supabase_client.update_mindmap(
                    mindmap_id,
                    {
                        "status": "processing",
                        "error_message": None,
                    },
                )
                result = generate_mindmap(
                    source_text=ai_source_text,
                    file_name=file_name,
                )
                mindmap_row, update_status = supabase_client.update_mindmap(
                    mindmap_id,
                    {
                        "status": "done",
                        "mindmap_json": result["mindmap_json"],
                        "markdown": result["markdown"],
                        "raw_response": result["raw_response"],
                        "error_message": None,
                    },
                )
                if update_status >= 400:
                    return Response({"message": "Luu mindmap that bai.", "error": mindmap_row}, status=status.HTTP_502_BAD_GATEWAY)
            except Exception as exc:
                public_message = _public_ai_error(str(exc))
                failed_row, _ = supabase_client.update_mindmap(
                    mindmap_id,
                    {
                        "status": "failed",
                        "error_message": public_message[:1000],
                    },
                )
                return Response(
                    {
                        "message": public_message,
                        "mindmap": normalize_mindmap(failed_row or mindmap_row),
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            return Response(
                {"message": "Tao mindmap thanh cong.", "mindmap": normalize_mindmap(mindmap_row), "cached": False},
                status=status.HTTP_201_CREATED,
            )
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class MindmapByReadApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, read_id):
        user_id = str(request.query_params.get("user_id") or "").strip()
        if not user_id:
            return Response({"message": "Thieu user_id."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            row, row_status = supabase_client.get_mindmap_by_read_id(str(read_id))
            if row_status >= 400:
                return Response({"message": "Khong doc duoc mindmap.", "error": row}, status=status.HTTP_502_BAD_GATEWAY)
            if not row:
                return Response({"message": "Chua co mindmap cho tai lieu nay."}, status=status.HTTP_404_NOT_FOUND)
            if str(row.get("id_user")) != user_id:
                return Response({"message": "Ban khong co quyen xem mindmap nay."}, status=status.HTTP_403_FORBIDDEN)
            return Response(
                {"message": "Lay mindmap thanh cong.", "mindmap": normalize_mindmap(row), "cached": True},
                status=status.HTTP_200_OK,
            )
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
