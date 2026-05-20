from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from config.services import supabase_client
from config.services.supabase_client import SupabaseConfigError

from .serializers import PlanTaskSerializer, PlanTaskStatusSerializer


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


class PlanTaskApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        user_id = str(request.query_params.get("id_user", "")).strip()
        task_date = str(request.query_params.get("task_date", "")).strip()
        if not user_id:
            return Response(
                {"message": "Thieu id_user."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            tasks, list_status = supabase_client.list_plan_tasks(
                user_id=user_id,
                task_date=task_date,
            )
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if list_status >= 400:
            return Response(
                {"message": "Lay danh sach nhiem vu that bai."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({"tasks": tasks}, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = PlanTaskSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "message": _extract_first_error(serializer.errors),
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data
        try:
            created_task, created_status = supabase_client.create_plan_task(
                user_id=str(data["id_user"]),
                task_name=data["task_name"].strip(),
                subject=data.get("subject", "").strip(),
                task_date=str(data["task_date"]),
                start_time=data["start_time"].strftime("%H:%M:%S"),
                end_time=data["end_time"].strftime("%H:%M:%S"),
                priority=data["priority"],
                status=data.get("status", "pending"),
            )
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if created_status >= 400:
            return Response(
                {"message": "Them nhiem vu that bai.", "error": created_task},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {
                "message": "Them nhiem vu thanh cong.",
                "task": created_task,
            },
            status=status.HTTP_201_CREATED,
        )


class PlanTaskStatusApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def patch(self, request, task_id):
        serializer = PlanTaskStatusSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "message": _extract_first_error(serializer.errors),
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            updated_task, update_status = supabase_client.update_plan_task_status(
                str(task_id),
                serializer.validated_data["status"],
            )
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if update_status >= 400:
            return Response(
                {"message": "Cap nhat trang thai nhiem vu that bai.", "error": updated_task},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {
                "message": "Cap nhat trang thai nhiem vu thanh cong.",
                "task": updated_task,
            },
            status=status.HTTP_200_OK,
        )
