from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from config.services.supabase_client import SupabaseConfigError

from .serializers import NotificationQuerySerializer, NotificationReadAllSerializer, NotificationReadSerializer
from .services import build_notifications, mark_all_notifications_read, mark_notification_read, unread_count


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
    return "Dữ liệu không hợp lệ."


def _serializer_error_response(serializer):
    return Response(
        {"message": _extract_first_error(serializer.errors), "errors": serializer.errors},
        status=status.HTTP_400_BAD_REQUEST,
    )


class NotificationListApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        serializer = NotificationQuerySerializer(data=request.query_params)
        if not serializer.is_valid():
            return _serializer_error_response(serializer)

        user_id = str(serializer.validated_data["user_id"])
        limit = int(serializer.validated_data.get("limit") or 30)

        try:
            notifications = build_notifications(user_id=user_id, limit=limit)
            return Response(
                {"notifications": notifications, "unread_count": unread_count(notifications)},
                status=status.HTTP_200_OK,
            )
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except RuntimeError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)


class MarkNotificationReadApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = NotificationReadSerializer(data=request.data)
        if not serializer.is_valid():
            return _serializer_error_response(serializer)

        user_id = str(serializer.validated_data["user_id"])
        notification_id = str(serializer.validated_data["notification_id"])

        try:
            mark_notification_read(user_id=user_id, notification_id=notification_id)
            notifications = build_notifications(user_id=user_id)
            return Response(
                {
                    "message": "Đã đánh dấu thông báo là đã đọc.",
                    "notifications": notifications,
                    "unread_count": unread_count(notifications),
                },
                status=status.HTTP_200_OK,
            )
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except RuntimeError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)


class MarkAllNotificationsReadApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = NotificationReadAllSerializer(data=request.data)
        if not serializer.is_valid():
            return _serializer_error_response(serializer)

        user_id = str(serializer.validated_data["user_id"])
        limit = int(serializer.validated_data.get("limit") or 30)

        try:
            mark_all_notifications_read(user_id=user_id, limit=limit)
            notifications = build_notifications(user_id=user_id, limit=limit)
            return Response(
                {
                    "message": "Đã đọc tất cả thông báo.",
                    "notifications": notifications,
                    "unread_count": unread_count(notifications),
                },
                status=status.HTTP_200_OK,
            )
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except RuntimeError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
