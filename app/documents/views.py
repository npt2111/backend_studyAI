from pathlib import Path
from typing import Dict
from uuid import uuid4

from django.conf import settings
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from config.services import supabase_client
from config.services.supabase_client import SupabaseConfigError

from .serializers import JobListQuerySerializer, JobQuerySerializer, UploadDocumentSerializer
from .services import (
    _extract_docx_markdown,
    _extract_pdf_markdown,
    _validate_document_file,
    _validate_readable_text,
    normalize_read_result,
)

ALLOWED_EXTS = {".pdf", ".docx"}


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


def _serializer_error_response(serializer, fallback: str):
    message = _extract_first_error(serializer.errors) or fallback
    return Response({"message": message, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


def _safe_name(file_name: str) -> str:
    base = Path(file_name).name
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in base)
    return cleaned or "document"


class UploadDocumentApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        serializer = UploadDocumentSerializer(data=request.data)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "user_id khong hop le.")

        upload = request.FILES.get("file")
        if not upload:
            return Response({"message": "Thieu file upload."}, status=status.HTTP_400_BAD_REQUEST)

        user_id = str(serializer.validated_data["user_id"])
        file_name = str(upload.name or "document")
        ext = Path(file_name).suffix.lower()
        if ext not in ALLOWED_EXTS:
            return Response({"message": "Chi ho tro PDF va DOCX."}, status=status.HTTP_400_BAD_REQUEST)

        max_mb = int(getattr(settings, "DOCUMENT_MAX_FILE_MB", 20))
        if upload.size > max_mb * 1024 * 1024:
            return Response({"message": f"File vuot qua {max_mb}MB."}, status=status.HTTP_400_BAD_REQUEST)

        safe_name = _safe_name(file_name)
        storage_path = f"{user_id}/{uuid4().hex}_{safe_name}"
        mime_type = upload.content_type or "application/octet-stream"

        try:
            file_bytes = upload.read()
            if not file_bytes:
                return Response(
                    {"message": "File rong hoac khong doc duoc."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            _validate_document_file(file_name, mime_type, file_bytes)

            storage_payload, storage_status = supabase_client.upload_storage_file(
                bucket=getattr(settings, "SUPABASE_STORAGE_BUCKET", "study-documents"),
                object_path=storage_path,
                file_bytes=file_bytes,
                content_type=mime_type,
            )
            if storage_status >= 400:
                return Response(
                    {"message": "Upload Storage that bai.", "error": storage_payload},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            read_row, read_status = supabase_client.create_document_read_result(
                user_id=user_id,
                file_name=file_name,
                storage_path=storage_path,
                mime_type=mime_type,
            )
            if read_status >= 400:
                return Response(
                    {"message": "Tao ket qua doc file that bai.", "error": read_row},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            read_id = str(read_row.get("id_read", "")).strip()
            if not read_id:
                return Response(
                    {"message": "Da tao ket qua doc file nhung thieu id_read."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            try:
                if ext == ".pdf":
                    extracted_text = _extract_pdf_markdown(file_bytes)
                else:
                    extracted_text = _extract_docx_markdown(file_bytes)
                _validate_readable_text(extracted_text)
                read_row, read_status = supabase_client.update_document_read_result(
                    read_id,
                    {
                        "status": "done",
                        "extracted_text": extracted_text,
                        "source_word_count": len(extracted_text.split()),
                        "error_message": None,
                    },
                )
                if read_status >= 400:
                    return Response(
                        {"message": "Luu ket qua doc file that bai.", "error": read_row},
                        status=status.HTTP_502_BAD_GATEWAY,
                    )
                try:
                    supabase_client.create_study_activity(
                        user_id=user_id,
                        activity_type="document",
                        title="Tài liệu",
                        description=f"Đã đọc tài liệu {file_name}",
                        duration_seconds=max(60, len(extracted_text.split()) // 3),
                        read_id=read_id,
                        source_id=read_id,
                        metadata={"file_name": file_name, "source_word_count": len(extracted_text.split())},
                    )
                except Exception:
                    pass
            except Exception as exc:
                failed_row, _ = supabase_client.update_document_read_result(
                    read_id,
                    {
                        "status": "failed",
                        "error_message": str(exc)[:1000] if str(exc) else "Khong ro loi.",
                    },
                )
                return Response(
                    {
                        "message": str(exc) if str(exc) else "Khong doc duoc noi dung file.",
                        "read_result": normalize_read_result(failed_row or read_row),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            return Response(
                {
                    "message": "Upload thanh cong, da doc noi dung file.",
                    "read_result": normalize_read_result(read_row),
                },
                status=status.HTTP_201_CREATED,
            )

        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except RuntimeError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({"message": f"Upload that bai: {exc}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class DocumentReadResultDetailApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, read_id):
        query = JobQuerySerializer(data=request.query_params)
        if not query.is_valid():
            return _serializer_error_response(query, "Query param khong hop le.")

        user_id = str(query.validated_data["user_id"])

        try:
            row, row_status = supabase_client.get_document_read_result(str(read_id))
            if row_status >= 400:
                return Response({"message": "Khong doc duoc ket qua doc file."}, status=status.HTTP_502_BAD_GATEWAY)
            if not row:
                return Response({"message": "Khong tim thay ket qua doc file."}, status=status.HTTP_404_NOT_FOUND)
            if str(row.get("id_user")) != user_id:
                return Response({"message": "Ban khong co quyen xem ket qua nay."}, status=status.HTTP_403_FORBIDDEN)

            return Response({"read_result": normalize_read_result(row)}, status=status.HTTP_200_OK)

        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request, read_id):
        query = JobQuerySerializer(data=request.query_params)
        if not query.is_valid():
            return _serializer_error_response(query, "Query param khong hop le.")

        user_id = str(query.validated_data["user_id"])

        try:
            row, row_status = supabase_client.get_document_read_result(str(read_id))
            if row_status >= 400:
                return Response({"message": "Khong doc duoc ket qua doc file."}, status=status.HTTP_502_BAD_GATEWAY)
            if not row:
                return Response({"message": "Khong tim thay ket qua doc file."}, status=status.HTTP_404_NOT_FOUND)
            if str(row.get("id_user")) != user_id:
                return Response({"message": "Ban khong co quyen xoa ket qua nay."}, status=status.HTTP_403_FORBIDDEN)

            deleted_row, deleted_status = supabase_client.delete_document_read_result(str(read_id))
            if deleted_status >= 400:
                return Response({"message": "Xoa document that bai.", "error": deleted_row}, status=status.HTTP_502_BAD_GATEWAY)

            return Response(
                {
                    "message": "Da xoa document.",
                    "read_result": normalize_read_result(deleted_row or row),
                },
                status=status.HTTP_200_OK,
            )

        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class DocumentReadResultListApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        serializer = JobListQuerySerializer(data=request.query_params)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Query param khong hop le.")

        user_id = str(serializer.validated_data["user_id"])
        limit = int(serializer.validated_data["limit"])

        try:
            rows, rows_status = supabase_client.list_document_read_results(user_id=user_id, limit=limit)
            if rows_status >= 400:
                return Response({"message": "Khong lay duoc danh sach ket qua doc file."}, status=status.HTTP_502_BAD_GATEWAY)

            return Response({"read_results": [normalize_read_result(r) for r in rows]}, status=status.HTTP_200_OK)

        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



