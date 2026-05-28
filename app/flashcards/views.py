from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from config.services import supabase_client
from config.services.supabase_client import SupabaseConfigError

from .serializers import (
    FlashcardAttemptFinishSerializer,
    FlashcardAttemptProgressSerializer,
    FlashcardAttemptStartSerializer,
    FlashcardGenerateSerializer,
    FlashcardListQuerySerializer,
    FlashcardQuerySerializer,
)
from .services import (
    calculate_flashcard_progress,
    generate_flashcards,
    normalize_flashcard,
    normalize_flashcard_attempt,
)


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


class GenerateFlashcardApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = FlashcardGenerateSerializer(data=request.data)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Du lieu tao flashcard khong hop le.")

        user_id = str(serializer.validated_data["user_id"])
        read_id = str(serializer.validated_data["read_id"])
        difficulty = str(serializer.validated_data["difficulty"])
        card_count = int(serializer.validated_data["card_count"])

        try:
            read_row, read_status = supabase_client.get_document_read_result(read_id)
            if read_status >= 400:
                return Response({"message": "Khong doc duoc ket qua doc file."}, status=status.HTTP_502_BAD_GATEWAY)
            if not read_row:
                return Response({"message": "Khong tim thay ket qua doc file."}, status=status.HTTP_404_NOT_FOUND)
            if str(read_row.get("id_user")) != user_id:
                return Response({"message": "Ban khong co quyen tao flashcard tu file nay."}, status=status.HTTP_403_FORBIDDEN)
            if str(read_row.get("status", "")).lower() != "done":
                return Response({"message": "File chua doc xong nen chua the tao flashcard."}, status=status.HTTP_409_CONFLICT)

            source_text = str(read_row.get("extracted_text") or "").strip()
            if not source_text:
                return Response({"message": "File khong co extracted_text de tao flashcard."}, status=status.HTTP_400_BAD_REQUEST)

            flashcard_row, flashcard_status = supabase_client.create_flashcard_generation(
                user_id=user_id,
                read_id=read_id,
                file_name=str(read_row.get("file_name") or "Document"),
                difficulty=difficulty,
                card_count=card_count,
            )
            if flashcard_status >= 400:
                return Response({"message": "Tao flashcard record that bai.", "error": flashcard_row}, status=status.HTTP_502_BAD_GATEWAY)

            flashcard_id = str(flashcard_row.get("id_flashcard") or "").strip()
            if not flashcard_id:
                return Response({"message": "Da tao flashcard record nhung thieu id_flashcard."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            try:
                result = generate_flashcards(
                    source_text=source_text,
                    difficulty=difficulty,
                    card_count=card_count,
                )
                flashcard_row, update_status = supabase_client.update_flashcard_generation(
                    flashcard_id,
                    {
                        "status": "done",
                        "cards": result["cards"],
                        "raw_response": result["raw_response"],
                        "error_message": None,
                    },
                )
                if update_status >= 400:
                    supabase_client.delete_flashcard_generation(flashcard_id)
                    return Response({"message": "Luu flashcard that bai.", "error": flashcard_row}, status=status.HTTP_502_BAD_GATEWAY)
            except Exception as exc:
                supabase_client.delete_flashcard_generation(flashcard_id)
                return Response(
                    {
                        "message": str(exc) if str(exc) else "Tao flashcard that bai.",
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            return Response(
                {
                    "message": "Tao flashcard thanh cong.",
                    "flashcard": normalize_flashcard(flashcard_row),
                },
                status=status.HTTP_201_CREATED,
            )
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class FlashcardDetailApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, flashcard_id):
        serializer = FlashcardQuerySerializer(data=request.query_params)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Query param khong hop le.")

        user_id = str(serializer.validated_data["user_id"])
        try:
            row, row_status = supabase_client.get_flashcard_generation(str(flashcard_id))
            if row_status >= 400:
                return Response({"message": "Khong doc duoc flashcard."}, status=status.HTTP_502_BAD_GATEWAY)
            if not row:
                return Response({"message": "Khong tim thay flashcard."}, status=status.HTTP_404_NOT_FOUND)
            if str(row.get("id_user")) != user_id:
                return Response({"message": "Ban khong co quyen xem flashcard nay."}, status=status.HTTP_403_FORBIDDEN)
            return Response({"flashcard": normalize_flashcard(row)}, status=status.HTTP_200_OK)
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request, flashcard_id):
        serializer = FlashcardQuerySerializer(data=request.query_params)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Query param khong hop le.")

        user_id = str(serializer.validated_data["user_id"])
        try:
            row, row_status = supabase_client.get_flashcard_generation(str(flashcard_id))
            if row_status >= 400:
                return Response({"message": "Khong doc duoc flashcard."}, status=status.HTTP_502_BAD_GATEWAY)
            if not row:
                return Response({"message": "Khong tim thay flashcard."}, status=status.HTTP_404_NOT_FOUND)
            if str(row.get("id_user")) != user_id:
                return Response({"message": "Ban khong co quyen xoa flashcard nay."}, status=status.HTTP_403_FORBIDDEN)

            _, attempts_status = supabase_client.delete_flashcard_attempts_by_flashcard(
                user_id=user_id,
                flashcard_id=str(flashcard_id),
            )
            if attempts_status >= 400:
                return Response({"message": "Xoa attempt cua flashcard that bai."}, status=status.HTTP_502_BAD_GATEWAY)

            deleted_row, delete_status = supabase_client.delete_flashcard_generation(str(flashcard_id))
            if delete_status >= 400:
                return Response({"message": "Xoa flashcard that bai.", "error": deleted_row}, status=status.HTTP_502_BAD_GATEWAY)
            return Response(
                {"message": "Da xoa flashcard.", "flashcard": normalize_flashcard(deleted_row or row)},
                status=status.HTTP_200_OK,
            )
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class FlashcardListApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        serializer = FlashcardListQuerySerializer(data=request.query_params)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Query param khong hop le.")

        user_id = str(serializer.validated_data["user_id"])
        limit = int(serializer.validated_data["limit"])
        try:
            rows, rows_status = supabase_client.list_flashcard_generations(user_id=user_id, limit=limit)
            if rows_status >= 400:
                return Response({"message": "Khong lay duoc danh sach flashcard."}, status=status.HTTP_502_BAD_GATEWAY)
            return Response({"flashcards": [normalize_flashcard(row) for row in rows]}, status=status.HTTP_200_OK)
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class StartFlashcardAttemptApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = FlashcardAttemptStartSerializer(data=request.data)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Du lieu bat dau flashcard khong hop le.")

        user_id = str(serializer.validated_data["user_id"])
        flashcard_id = str(serializer.validated_data["flashcard_id"])
        try:
            flashcard_row, flashcard_status = supabase_client.get_flashcard_generation(flashcard_id)
            if flashcard_status >= 400:
                return Response({"message": "Khong doc duoc flashcard."}, status=status.HTTP_502_BAD_GATEWAY)
            if not flashcard_row:
                return Response({"message": "Khong tim thay flashcard."}, status=status.HTTP_404_NOT_FOUND)
            if str(flashcard_row.get("id_user")) != user_id:
                return Response({"message": "Ban khong co quyen hoc flashcard nay."}, status=status.HTTP_403_FORBIDDEN)

            cards = flashcard_row.get("cards")
            total = len(cards) if isinstance(cards, list) else int(flashcard_row.get("card_count") or 0)
            attempt_row, attempt_status = supabase_client.create_flashcard_attempt(
                user_id=user_id,
                flashcard_id=flashcard_id,
                read_id=str(flashcard_row.get("id_read") or ""),
                total_cards=total,
            )
            if attempt_status >= 400:
                return Response({"message": "Tao flashcard attempt that bai.", "error": attempt_row}, status=status.HTTP_502_BAD_GATEWAY)
            return Response({"attempt": normalize_flashcard_attempt(attempt_row)}, status=status.HTTP_201_CREATED)
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class UpdateFlashcardAttemptApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, attempt_id):
        serializer = FlashcardAttemptProgressSerializer(data=request.data)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Du lieu tien do flashcard khong hop le.")

        user_id = str(serializer.validated_data["user_id"])
        current_index = int(serializer.validated_data["current_index"])
        viewed_count = int(serializer.validated_data["viewed_count"])
        elapsed_seconds = int(serializer.validated_data["elapsed_seconds"])
        try:
            attempt_row, attempt_status = supabase_client.get_flashcard_attempt(str(attempt_id))
            if attempt_status >= 400:
                return Response({"message": "Khong doc duoc attempt."}, status=status.HTTP_502_BAD_GATEWAY)
            if not attempt_row:
                return Response({"message": "Khong tim thay attempt."}, status=status.HTTP_404_NOT_FOUND)
            if str(attempt_row.get("id_user")) != user_id:
                return Response({"message": "Ban khong co quyen cap nhat attempt nay."}, status=status.HTTP_403_FORBIDDEN)
            if str(attempt_row.get("status")) == "completed":
                return Response({"message": "Attempt da hoan thanh."}, status=status.HTTP_409_CONFLICT)

            total = int(attempt_row.get("total_cards") or 0)
            old_viewed = int(attempt_row.get("viewed_count") or 0)
            safe_viewed = max(old_viewed, viewed_count)
            progress = calculate_flashcard_progress(viewed_count=safe_viewed, total_cards=total)
            updated_row, update_status = supabase_client.update_flashcard_attempt(
                str(attempt_id),
                {
                    "current_index": current_index,
                    "elapsed_seconds": elapsed_seconds,
                    **progress,
                },
            )
            if update_status >= 400:
                return Response({"message": "Luu tien do flashcard that bai.", "error": updated_row}, status=status.HTTP_502_BAD_GATEWAY)
            return Response({"attempt": normalize_flashcard_attempt(updated_row)}, status=status.HTTP_200_OK)
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class FinishFlashcardAttemptApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, attempt_id):
        serializer = FlashcardAttemptFinishSerializer(data=request.data)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Du lieu ket thuc flashcard khong hop le.")

        user_id = str(serializer.validated_data["user_id"])
        elapsed_seconds = int(serializer.validated_data["elapsed_seconds"])
        try:
            attempt_row, attempt_status = supabase_client.get_flashcard_attempt(str(attempt_id))
            if attempt_status >= 400:
                return Response({"message": "Khong doc duoc attempt."}, status=status.HTTP_502_BAD_GATEWAY)
            if not attempt_row:
                return Response({"message": "Khong tim thay attempt."}, status=status.HTTP_404_NOT_FOUND)
            if str(attempt_row.get("id_user")) != user_id:
                return Response({"message": "Ban khong co quyen ket thuc attempt nay."}, status=status.HTTP_403_FORBIDDEN)

            total = int(attempt_row.get("total_cards") or 0)
            progress = calculate_flashcard_progress(viewed_count=total, total_cards=total)
            updated_row, update_status = supabase_client.update_flashcard_attempt(
                str(attempt_id),
                {
                    "status": "completed",
                    "current_index": max(total - 1, 0),
                    "elapsed_seconds": elapsed_seconds,
                    "finished_at": supabase_client._now_iso(),
                    **progress,
                },
            )
            if update_status >= 400:
                return Response({"message": "Ket thuc flashcard attempt that bai.", "error": updated_row}, status=status.HTTP_502_BAD_GATEWAY)
            try:
                supabase_client.create_study_activity(
                    user_id=user_id,
                    activity_type="flashcard",
                    title="Flash Card",
                    description=f"Ôn tập {total} thẻ",
                    duration_seconds=elapsed_seconds,
                    read_id=str(attempt_row.get("id_read") or ""),
                    source_id=str(attempt_id),
                    metadata={"total_cards": total},
                )
            except Exception:
                pass
            return Response({"attempt": normalize_flashcard_attempt(updated_row)}, status=status.HTTP_200_OK)
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
