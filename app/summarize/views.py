from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from config.services import supabase_client
from config.services.supabase_client import SupabaseConfigError

from .background import submit_summary_job
from .serializers import JobListQuerySerializer, JobQuerySerializer, SummaryStartSerializer
from .services import normalize_job, now_iso


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


class StartSummaryJobApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = SummaryStartSerializer(data=request.data)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Du lieu tao tom tat khong hop le.")

        user_id = str(serializer.validated_data["user_id"])
        read_id = str(serializer.validated_data["read_id"])

        try:
            read_row, read_status = supabase_client.get_document_read_result(read_id)
            if read_status >= 400:
                return Response({"message": "Khong doc duoc ket qua doc file."}, status=status.HTTP_502_BAD_GATEWAY)
            if not read_row:
                return Response({"message": "Khong tim thay ket qua doc file."}, status=status.HTTP_404_NOT_FOUND)
            if str(read_row.get("id_user")) != user_id:
                return Response({"message": "Ban khong co quyen tom tat file nay."}, status=status.HTTP_403_FORBIDDEN)
            if str(read_row.get("status", "")).lower() != "done":
                return Response({"message": "File chua doc xong nen chua the tom tat."}, status=status.HTTP_409_CONFLICT)

            job_row, job_status = supabase_client.create_summary_job(
                user_id=user_id,
                file_name=str(read_row.get("file_name") or "Document"),
                storage_path=str(read_row.get("storage_path") or ""),
                mime_type=str(read_row.get("mime_type") or ""),
            )
            if job_status >= 400:
                return Response(
                    {"message": "Tao summary job that bai.", "error": job_row},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            job_id = str(job_row.get("id_job", "")).strip()
            if not job_id:
                return Response({"message": "Da tao job nhung thieu id_job."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            worker_started = _maybe_start_inline_summary_job(job_id)
            return Response(
                {
                    "message": "Da tao job tom tat.",
                    "job": normalize_job(job_row),
                    "worker_started": worker_started,
                },
                status=status.HTTP_202_ACCEPTED,
            )

        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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
