from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from config.services import supabase_client
from config.services.supabase_client import SupabaseConfigError

from .serializers import CheckinSerializer, UserQuerySerializer
from .services import build_overview, local_today


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


class AnalyticsOverviewApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        serializer = UserQuerySerializer(data=request.query_params)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Query param khong hop le.")

        user_id = str(serializer.validated_data["user_id"])
        try:
            return Response({"stats": build_overview(user_id)}, status=status.HTTP_200_OK)
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except RuntimeError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)


class DailyCheckinApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = CheckinSerializer(data=request.data)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Du lieu check-in khong hop le.")

        user_id = str(serializer.validated_data["user_id"])
        checkin_date = local_today().isoformat()

        try:
            existing, existing_status = supabase_client.get_daily_checkin(
                user_id=user_id,
                checkin_date=checkin_date,
            )
            if existing_status >= 400:
                return Response({"message": "Khong doc duoc check-in."}, status=status.HTTP_502_BAD_GATEWAY)
            if existing:
                return Response({"checkin": existing, "created": False}, status=status.HTTP_200_OK)

            row, row_status = supabase_client.create_daily_checkin(
                user_id=user_id,
                checkin_date=checkin_date,
            )
            if row_status >= 400:
                return Response({"message": "Tao check-in that bai.", "error": row}, status=status.HTTP_502_BAD_GATEWAY)
            return Response({"checkin": row, "created": True}, status=status.HTTP_201_CREATED)
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
