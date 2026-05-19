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

from .background import submit_summary_job
from .serializers import JobListQuerySerializer, JobQuerySerializer, UploadDocumentSerializer
from .services import _validate_document_file, normalize_job, now_iso

ALLOWED_EXTS = {".pdf", ".docx"}


def _maybe_start_inline_summary_job(job_id: str) -> bool:
    return submit_summary_job(str(job_id))


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

        max_mb = int(getattr(settings, "SUMMARY_MAX_FILE_MB", 20))
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

            job_row, job_status = supabase_client.create_summary_job(
                user_id=user_id,
                file_name=file_name,
                storage_path=storage_path,
                mime_type=mime_type,
            )
            if job_status >= 400:
                return Response(
                    {"message": "Tao summary job that bai.", "error": job_row},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            job_id = str(job_row.get("id_job", "")).strip()
            if not job_id:
                return Response(
                    {"message": "Da tao job nhung thieu id_job."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            worker_started = _maybe_start_inline_summary_job(job_id)

            return Response(
                {
                    "message": "Upload thanh cong, da tao job cho worker xu ly.",
                    "job": normalize_job(job_row),
                    "worker_started": worker_started,
                },
                status=status.HTTP_202_ACCEPTED,
            )

        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except RuntimeError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({"message": f"Upload that bai: {exc}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SummaryJobDetailApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, job_id):
        query = JobQuerySerializer(data=request.query_params)
        if not query.is_valid():
            return _serializer_error_response(query, "Query param khong hop le.")

        user_id = str(query.validated_data["user_id"])

        try:
            row, row_status = supabase_client.get_summary_job(str(job_id))
            if row_status >= 400:
                return Response({"message": "Khong doc duoc summary job."}, status=status.HTTP_502_BAD_GATEWAY)
            if not row:
                return Response({"message": "Khong tim thay summary job."}, status=status.HTTP_404_NOT_FOUND)

            if str(row.get("id_user")) != user_id:
                return Response({"message": "Ban khong co quyen xem job nay."}, status=status.HTTP_403_FORBIDDEN)

            if str(row.get("status", "")).lower() == "queued":
                _maybe_start_inline_summary_job(str(row.get("id_job")))

            return Response({"job": normalize_job(row)}, status=status.HTTP_200_OK)

        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SummaryJobListApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        serializer = JobListQuerySerializer(data=request.query_params)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Query param khong hop le.")

        user_id = str(serializer.validated_data["user_id"])
        limit = int(serializer.validated_data["limit"])

        try:
            rows, rows_status = supabase_client.list_summary_jobs(user_id=user_id, limit=limit)
            if rows_status >= 400:
                return Response({"message": "Khong lay duoc danh sach jobs."}, status=status.HTTP_502_BAD_GATEWAY)

            for row in rows:
                if str(row.get("status", "")).lower() == "queued":
                    _maybe_start_inline_summary_job(str(row.get("id_job")))

            return Response({"jobs": [normalize_job(r) for r in rows]}, status=status.HTTP_200_OK)

        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class RetrySummaryJobApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, job_id):
        serializer = JobQuerySerializer(data=request.data)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "user_id khong hop le.")

        user_id = str(serializer.validated_data["user_id"])

        try:
            row, row_status = supabase_client.get_summary_job(str(job_id))
            if row_status >= 400:
                return Response({"message": "Khong doc duoc summary job."}, status=status.HTTP_502_BAD_GATEWAY)
            if not row:
                return Response({"message": "Khong tim thay summary job."}, status=status.HTTP_404_NOT_FOUND)

            if str(row.get("id_user")) != user_id:
                return Response({"message": "Ban khong co quyen retry job nay."}, status=status.HTTP_403_FORBIDDEN)

            if str(row.get("status", "")).lower() == "processing":
                return Response({"message": "Job dang duoc xu ly."}, status=status.HTTP_409_CONFLICT)

            updated_row, updated_status = supabase_client.update_summary_job(
                str(job_id),
                {
                    "status": "queued",
                    "progress": 0,
                    "summary_text": None,
                    "summary_json": None,
                    "key_points": [],
                    "error_message": None,
                    "started_at": None,
                    "finished_at": None,
                    "updated_at": now_iso(),
                },
            )
            if updated_status >= 400:
                return Response({"message": "Khong retry duoc job."}, status=status.HTTP_502_BAD_GATEWAY)

            worker_started = _maybe_start_inline_summary_job(str(job_id))
            return Response(
                {
                    "message": "Da retry job.",
                    "job": normalize_job(updated_row),
                    "worker_started": worker_started,
                },
                status=status.HTTP_202_ACCEPTED,
            )

        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



