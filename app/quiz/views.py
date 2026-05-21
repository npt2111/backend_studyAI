from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from config.services import supabase_client
from config.services.supabase_client import SupabaseConfigError

from .serializers import (
    AttemptAnswerSerializer,
    AttemptDeleteSerializer,
    AttemptFinishSerializer,
    AttemptStartSerializer,
    QuizGenerateSerializer,
    QuizListQuerySerializer,
    QuizQuerySerializer,
)
from .services import (
    build_attempt_answer,
    generate_quiz_questions,
    merge_attempt_answer,
    normalize_attempt,
    normalize_quiz,
    summarize_attempt_answers,
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


class GenerateQuizApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = QuizGenerateSerializer(data=request.data)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Du lieu tao quiz khong hop le.")

        user_id = str(serializer.validated_data["user_id"])
        read_id = str(serializer.validated_data["read_id"])
        quiz_type = str(serializer.validated_data["quiz_type"])
        difficulty = str(serializer.validated_data["difficulty"])
        question_count = int(serializer.validated_data["question_count"])

        try:
            read_row, read_status = supabase_client.get_document_read_result(read_id)
            if read_status >= 400:
                return Response({"message": "Khong doc duoc ket qua doc file."}, status=status.HTTP_502_BAD_GATEWAY)
            if not read_row:
                return Response({"message": "Khong tim thay ket qua doc file."}, status=status.HTTP_404_NOT_FOUND)
            if str(read_row.get("id_user")) != user_id:
                return Response({"message": "Ban khong co quyen tao quiz tu file nay."}, status=status.HTTP_403_FORBIDDEN)
            if str(read_row.get("status", "")).lower() != "done":
                return Response({"message": "File chua doc xong nen chua the tao quiz."}, status=status.HTTP_409_CONFLICT)

            source_text = str(read_row.get("extracted_text") or "").strip()
            if not source_text:
                return Response({"message": "File khong co extracted_text de tao quiz."}, status=status.HTTP_400_BAD_REQUEST)

            quiz_row, quiz_status = supabase_client.create_quiz_generation(
                user_id=user_id,
                read_id=read_id,
                file_name=str(read_row.get("file_name") or "Document"),
                quiz_type=quiz_type,
                difficulty=difficulty,
                question_count=question_count,
            )
            if quiz_status >= 400:
                return Response({"message": "Tao quiz record that bai.", "error": quiz_row}, status=status.HTTP_502_BAD_GATEWAY)

            quiz_id = str(quiz_row.get("id_quiz") or "").strip()
            if not quiz_id:
                return Response({"message": "Da tao quiz record nhung thieu id_quiz."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            try:
                result = generate_quiz_questions(
                    source_text=source_text,
                    quiz_type=quiz_type,
                    difficulty=difficulty,
                    question_count=question_count,
                )
                quiz_row, update_status = supabase_client.update_quiz_generation(
                    quiz_id,
                    {
                        "status": "done",
                        "questions": result["questions"],
                        "raw_response": result["raw_response"],
                        "error_message": None,
                    },
                )
                if update_status >= 400:
                    return Response({"message": "Luu quiz that bai.", "error": quiz_row}, status=status.HTTP_502_BAD_GATEWAY)
            except Exception as exc:
                failed_row, _ = supabase_client.update_quiz_generation(
                    quiz_id,
                    {
                        "status": "failed",
                        "error_message": str(exc)[:1000] if str(exc) else "Khong ro loi.",
                    },
                )
                return Response(
                    {
                        "message": str(exc) if str(exc) else "Tao quiz that bai.",
                        "quiz": normalize_quiz(failed_row or quiz_row),
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            return Response(
                {
                    "message": "Tao quiz thanh cong.",
                    "quiz": normalize_quiz(quiz_row),
                },
                status=status.HTTP_201_CREATED,
            )

        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class QuizDetailApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, quiz_id):
        serializer = QuizQuerySerializer(data=request.query_params)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Query param khong hop le.")

        user_id = str(serializer.validated_data["user_id"])
        try:
            row, row_status = supabase_client.get_quiz_generation(str(quiz_id))
            if row_status >= 400:
                return Response({"message": "Khong doc duoc quiz."}, status=status.HTTP_502_BAD_GATEWAY)
            if not row:
                return Response({"message": "Khong tim thay quiz."}, status=status.HTTP_404_NOT_FOUND)
            if str(row.get("id_user")) != user_id:
                return Response({"message": "Ban khong co quyen xem quiz nay."}, status=status.HTTP_403_FORBIDDEN)
            return Response({"quiz": normalize_quiz(row)}, status=status.HTTP_200_OK)
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class QuizListApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        serializer = QuizListQuerySerializer(data=request.query_params)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Query param khong hop le.")

        user_id = str(serializer.validated_data["user_id"])
        limit = int(serializer.validated_data["limit"])
        try:
            rows, rows_status = supabase_client.list_quiz_generations(user_id=user_id, limit=limit)
            if rows_status >= 400:
                return Response({"message": "Khong lay duoc danh sach quiz."}, status=status.HTTP_502_BAD_GATEWAY)
            return Response({"quizzes": [normalize_quiz(row) for row in rows]}, status=status.HTTP_200_OK)
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class StartQuizAttemptApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = AttemptStartSerializer(data=request.data)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Du lieu bat dau quiz khong hop le.")

        user_id = str(serializer.validated_data["user_id"])
        quiz_id = str(serializer.validated_data["quiz_id"])
        try:
            quiz_row, quiz_status = supabase_client.get_quiz_generation(quiz_id)
            if quiz_status >= 400:
                return Response({"message": "Khong doc duoc quiz."}, status=status.HTTP_502_BAD_GATEWAY)
            if not quiz_row:
                return Response({"message": "Khong tim thay quiz."}, status=status.HTTP_404_NOT_FOUND)
            if str(quiz_row.get("id_user")) != user_id:
                return Response({"message": "Ban khong co quyen lam quiz nay."}, status=status.HTTP_403_FORBIDDEN)

            questions = quiz_row.get("questions")
            total = len(questions) if isinstance(questions, list) else int(quiz_row.get("question_count") or 0)
            attempt_row, attempt_status = supabase_client.create_quiz_attempt(
                user_id=user_id,
                quiz_id=quiz_id,
                read_id=str(quiz_row.get("id_read") or ""),
                total_questions=total,
            )
            if attempt_status >= 400:
                return Response({"message": "Tao attempt that bai.", "error": attempt_row}, status=status.HTTP_502_BAD_GATEWAY)
            return Response({"attempt": normalize_attempt(attempt_row)}, status=status.HTTP_201_CREATED)
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SubmitQuizAnswerApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, attempt_id):
        serializer = AttemptAnswerSerializer(data=request.data)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Du lieu dap an khong hop le.")

        user_id = str(serializer.validated_data["user_id"])
        question_index = int(serializer.validated_data["question_index"])
        selected_answer = str(serializer.validated_data["selected_answer"]).upper()
        elapsed_seconds = int(serializer.validated_data["elapsed_seconds"])

        try:
            attempt_row, attempt_status = supabase_client.get_quiz_attempt(str(attempt_id))
            if attempt_status >= 400:
                return Response({"message": "Khong doc duoc attempt."}, status=status.HTTP_502_BAD_GATEWAY)
            if not attempt_row:
                return Response({"message": "Khong tim thay attempt."}, status=status.HTTP_404_NOT_FOUND)
            if str(attempt_row.get("id_user")) != user_id:
                return Response({"message": "Ban khong co quyen cap nhat attempt nay."}, status=status.HTTP_403_FORBIDDEN)
            if str(attempt_row.get("status")) == "completed":
                return Response({"message": "Attempt da hoan thanh."}, status=status.HTTP_409_CONFLICT)

            quiz_row, quiz_status = supabase_client.get_quiz_generation(str(attempt_row.get("id_quiz")))
            if quiz_status >= 400 or not quiz_row:
                return Response({"message": "Khong doc duoc quiz."}, status=status.HTTP_502_BAD_GATEWAY)

            answer = build_attempt_answer(
                quiz_row=quiz_row,
                question_index=question_index,
                selected_answer=selected_answer,
            )
            answers = merge_attempt_answer(attempt_row.get("answers"), answer)
            total = int(attempt_row.get("total_questions") or len(quiz_row.get("questions") or []))
            summary = summarize_attempt_answers(answers, total)
            updated_row, update_status = supabase_client.update_quiz_attempt(
                str(attempt_id),
                {
                    "answers": answers,
                    "elapsed_seconds": elapsed_seconds,
                    **summary,
                },
            )
            if update_status >= 400:
                return Response({"message": "Luu dap an that bai.", "error": updated_row}, status=status.HTTP_502_BAD_GATEWAY)
            return Response({"attempt": normalize_attempt(updated_row), "answer": answer}, status=status.HTTP_200_OK)
        except RuntimeError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class FinishQuizAttemptApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, attempt_id):
        serializer = AttemptFinishSerializer(data=request.data)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Du lieu ket thuc attempt khong hop le.")

        user_id = str(serializer.validated_data["user_id"])
        elapsed_seconds = int(serializer.validated_data["elapsed_seconds"])
        try:
            attempt_row, attempt_status = supabase_client.get_quiz_attempt(str(attempt_id))
            if attempt_status >= 400:
                return Response({"message": "Khong doc duoc attempt."}, status=status.HTTP_502_BAD_GATEWAY)
            if not attempt_row:
                return Response({"message": "Khong tim thay attempt."}, status=status.HTTP_404_NOT_FOUND)
            if str(attempt_row.get("id_user")) != user_id:
                return Response({"message": "Ban khong co quyen ket thuc attempt nay."}, status=status.HTTP_403_FORBIDDEN)

            answers = attempt_row.get("answers") if isinstance(attempt_row.get("answers"), list) else []
            total = int(attempt_row.get("total_questions") or 0)
            summary = summarize_attempt_answers(answers, total)
            updated_row, update_status = supabase_client.update_quiz_attempt(
                str(attempt_id),
                {
                    "status": "completed",
                    "elapsed_seconds": elapsed_seconds,
                    "finished_at": supabase_client._now_iso(),
                    **summary,
                },
            )
            if update_status >= 400:
                return Response({"message": "Ket thuc attempt that bai.", "error": updated_row}, status=status.HTTP_502_BAD_GATEWAY)
            return Response({"attempt": normalize_attempt(updated_row)}, status=status.HTTP_200_OK)
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class DeleteQuizAttemptApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def delete(self, request, attempt_id):
        serializer = AttemptDeleteSerializer(data=request.query_params)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Query param khong hop le.")

        user_id = str(serializer.validated_data["user_id"])
        try:
            attempt_row, attempt_status = supabase_client.get_quiz_attempt(str(attempt_id))
            if attempt_status >= 400:
                return Response({"message": "Khong doc duoc attempt."}, status=status.HTTP_502_BAD_GATEWAY)
            if not attempt_row:
                return Response({"message": "Khong tim thay attempt."}, status=status.HTTP_404_NOT_FOUND)
            if str(attempt_row.get("id_user")) != user_id:
                return Response({"message": "Ban khong co quyen xoa attempt nay."}, status=status.HTTP_403_FORBIDDEN)

            deleted_row, delete_status = supabase_client.delete_quiz_attempt(str(attempt_id))
            if delete_status >= 400:
                return Response({"message": "Xoa attempt that bai.", "error": deleted_row}, status=status.HTTP_502_BAD_GATEWAY)
            return Response({"message": "Da xoa attempt.", "attempt": normalize_attempt(deleted_row)}, status=status.HTTP_200_OK)
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
