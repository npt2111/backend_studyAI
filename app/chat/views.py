from rest_framework import status
import logging
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from uuid import uuid4

from config.services import supabase_client
from config.services.supabase_client import SupabaseConfigError
from app.documents.rag import ensure_document_chunks_indexed, retrieve_relevant_chunks

from .serializers import (
    ChatMessageSerializer,
    ChatSessionListSerializer,
    ChatSessionQuerySerializer,
    ChatSessionStartSerializer,
)
from .services import (
    CHAT_GREETING,
    GeminiChatError,
    generate_document_chat_reply,
    normalize_chat_message,
    normalize_chat_session,
)

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
    elif isinstance(errors, str):
        return errors
    return "Du lieu khong hop le."


def _serializer_error_response(serializer, fallback: str):
    message = _extract_first_error(serializer.errors) or fallback
    return Response({"message": message, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


def _load_read_result(user_id: str, read_id: str):
    read_row, read_status = supabase_client.get_document_read_result(read_id)
    if read_status >= 400:
        return None, Response({"message": "Khong doc duoc ket qua doc file."}, status=status.HTTP_502_BAD_GATEWAY)
    if not read_row:
        return None, Response({"message": "Khong tim thay ket qua doc file."}, status=status.HTTP_404_NOT_FOUND)
    if str(read_row.get("id_user")) != user_id:
        return None, Response({"message": "Ban khong co quyen chat voi tai lieu nay."}, status=status.HTTP_403_FORBIDDEN)
    if str(read_row.get("status", "")).lower() != "done":
        return None, Response({"message": "File chua doc xong nen chua the chat."}, status=status.HTTP_409_CONFLICT)
    if not str(read_row.get("extracted_text") or "").strip():
        return None, Response({"message": "File khong co extracted_text de chat."}, status=status.HTTP_400_BAD_REQUEST)
    return read_row, None


class StartDocumentChatApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = ChatSessionStartSerializer(data=request.data)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Du lieu bat dau chat khong hop le.")

        user_id = str(serializer.validated_data["user_id"])
        read_id = str(serializer.validated_data["read_id"])
        try:
            read_row, error_response = _load_read_result(user_id, read_id)
            if error_response is not None:
                return error_response

            session_row, session_status = supabase_client.get_document_chat_session_by_read(
                user_id=user_id,
                read_id=read_id,
            )
            if session_status >= 400:
                return Response({"message": "Khong doc duoc phien chat."}, status=status.HTTP_502_BAD_GATEWAY)

            if not session_row:
                session_row, create_status = supabase_client.create_document_chat_session(
                    user_id=user_id,
                    read_id=read_id,
                    file_name=str(read_row.get("file_name") or "Document"),
                )
                if create_status >= 400:
                    return Response({"message": "Tao phien chat that bai.", "error": session_row}, status=status.HTTP_502_BAD_GATEWAY)

            session_id = str(session_row.get("id_chat_session") or "").strip()
            messages, messages_status = supabase_client.list_document_chat_messages(session_id=session_id, limit=100)
            if messages_status >= 400:
                return Response({"message": "Khong doc duoc lich su chat."}, status=status.HTTP_502_BAD_GATEWAY)

            if not messages:
                greeting_row, greeting_status = supabase_client.create_document_chat_message(
                    session_id=session_id,
                    user_id=user_id,
                    read_id=read_id,
                    role="assistant",
                    content=CHAT_GREETING,
                )
                if greeting_status >= 400:
                    return Response({"message": "Tao tin nhan chao that bai.", "error": greeting_row}, status=status.HTTP_502_BAD_GATEWAY)
                messages = [greeting_row]

            return Response(
                {
                    "message": "Mo phien chat thanh cong.",
                    "session": normalize_chat_session(session_row),
                    "messages": [normalize_chat_message(row) for row in messages],
                },
                status=status.HTTP_200_OK,
            )
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class DocumentChatSessionApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, session_id):
        serializer = ChatSessionQuerySerializer(data=request.query_params)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Query param khong hop le.")

        user_id = str(serializer.validated_data["user_id"])
        try:
            session_row, session_status = supabase_client.get_document_chat_session(str(session_id))
            if session_status >= 400:
                return Response({"message": "Khong doc duoc phien chat."}, status=status.HTTP_502_BAD_GATEWAY)
            if not session_row:
                return Response({"message": "Khong tim thay phien chat."}, status=status.HTTP_404_NOT_FOUND)
            if str(session_row.get("id_user")) != user_id:
                return Response({"message": "Ban khong co quyen xem phien chat nay."}, status=status.HTTP_403_FORBIDDEN)

            messages, messages_status = supabase_client.list_document_chat_messages(
                session_id=str(session_id),
                limit=100,
            )
            if messages_status >= 400:
                return Response({"message": "Khong doc duoc lich su chat."}, status=status.HTTP_502_BAD_GATEWAY)

            return Response(
                {
                    "session": normalize_chat_session(session_row),
                    "messages": [normalize_chat_message(row) for row in messages],
                },
                status=status.HTTP_200_OK,
            )
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request, session_id):
        serializer = ChatSessionQuerySerializer(data=request.query_params)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Query param khong hop le.")

        user_id = str(serializer.validated_data["user_id"])
        try:
            session_row, session_status = supabase_client.get_document_chat_session(str(session_id))
            if session_status >= 400:
                return Response({"message": "Khong doc duoc phien chat."}, status=status.HTTP_502_BAD_GATEWAY)
            if not session_row:
                return Response({"message": "Khong tim thay phien chat."}, status=status.HTTP_404_NOT_FOUND)
            if str(session_row.get("id_user")) != user_id:
                return Response({"message": "Ban khong co quyen xoa phien chat nay."}, status=status.HTTP_403_FORBIDDEN)

            deleted_row, delete_status = supabase_client.delete_document_chat_session(str(session_id))
            if delete_status >= 400:
                return Response({"message": "Xoa phien chat that bai.", "error": deleted_row}, status=status.HTTP_502_BAD_GATEWAY)

            return Response(
                {
                    "message": "Da xoa phien chat.",
                    "session": normalize_chat_session(deleted_row or session_row),
                },
                status=status.HTTP_200_OK,
            )
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class DocumentChatSessionListApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        serializer = ChatSessionListSerializer(data=request.query_params)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Query param khong hop le.")

        user_id = str(serializer.validated_data["user_id"])
        limit = int(serializer.validated_data.get("limit") or 50)
        offset = int(serializer.validated_data.get("offset") or 0)
        try:
            sessions, sessions_status = supabase_client.list_document_chat_sessions(
                user_id=user_id,
                limit=limit,
                offset=offset,
            )
            if sessions_status >= 400:
                return Response({"message": "Khong lay duoc danh sach chat."}, status=status.HTTP_502_BAD_GATEWAY)

            return Response(
                {
                    "sessions": [normalize_chat_session(row) for row in sessions],
                },
                status=status.HTTP_200_OK,
            )
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SendDocumentChatMessageApiView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = ChatMessageSerializer(data=request.data)
        if not serializer.is_valid():
            return _serializer_error_response(serializer, "Du lieu tin nhan khong hop le.")

        user_id = str(serializer.validated_data["user_id"])
        session_id = str(serializer.validated_data["session_id"])
        user_message = str(serializer.validated_data["message"]).strip()
        try:
            session_row, session_status = supabase_client.get_document_chat_session(session_id)
            if session_status >= 400:
                return Response({"message": "Khong doc duoc phien chat."}, status=status.HTTP_502_BAD_GATEWAY)
            if not session_row:
                return Response({"message": "Khong tim thay phien chat."}, status=status.HTTP_404_NOT_FOUND)
            if str(session_row.get("id_user")) != user_id:
                return Response({"message": "Ban khong co quyen chat trong phien nay."}, status=status.HTTP_403_FORBIDDEN)

            read_id = str(session_row.get("id_read") or "")
            read_row, error_response = _load_read_result(user_id, read_id)
            if error_response is not None:
                return error_response

            history_rows, history_status = supabase_client.list_document_chat_messages(session_id=session_id, limit=100)
            if history_status >= 400:
                return Response({"message": "Khong doc duoc lich su chat."}, status=status.HTTP_502_BAD_GATEWAY)

            user_row, user_status = supabase_client.create_document_chat_message(
                session_id=session_id,
                user_id=user_id,
                read_id=read_id,
                role="user",
                content=user_message,
            )
            if user_status >= 400:
                return Response({"message": "Luu tin nhan that bai.", "error": user_row}, status=status.HTTP_502_BAD_GATEWAY)

            try:
                try:
                    ensure_document_chunks_indexed(
                        user_id=user_id,
                        read_id=read_id,
                        source_text=str(read_row.get("extracted_text") or ""),
                    )
                    context_chunks = retrieve_relevant_chunks(
                        user_id=user_id,
                        read_id=read_id,
                        query=user_message,
                    )
                except Exception as exc:
                    logger.warning("Document RAG retrieval failed for session_id=%s: %s", session_id, exc)
                    context_chunks = []
                reply = generate_document_chat_reply(
                    source_text=str(read_row.get("extracted_text") or ""),
                    file_name=str(read_row.get("file_name") or session_row.get("file_name") or "Document"),
                    history=history_rows,
                    user_message=user_message,
                    context_chunks=context_chunks,
                )
                assistant_row, assistant_status = supabase_client.create_document_chat_message(
                    session_id=session_id,
                    user_id=user_id,
                    read_id=read_id,
                    role="assistant",
                    content=reply,
                )
                if assistant_status >= 400:
                    logger.warning(
                        "Failed to persist assistant reply for session_id=%s status=%s error=%s",
                        session_id,
                        assistant_status,
                        assistant_row,
                    )
                    assistant_row = {
                        "id_message": str(uuid4()),
                        "id_chat_session": session_id,
                        "id_user": user_id,
                        "id_read": read_id,
                        "role": "assistant",
                        "content": reply,
                    }
                supabase_client.touch_document_chat_session(session_id)
            except GeminiChatError as exc:
                logger.warning(
                    "Document chat AI failed for session_id=%s status=%s detail=%s",
                    session_id,
                    exc.status_code,
                    exc.detail,
                )
                return Response(
                    {"message": exc.public_message},
                    status=exc.status_code,
                )
            except Exception as exc:
                logger.exception("Unexpected document chat AI failure for session_id=%s", session_id)
                return Response(
                    {"message": "AI chua tra loi duoc, vui long thu lai."},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            return Response(
                {
                    "message": "Gui tin nhan thanh cong.",
                    "session": normalize_chat_session(session_row),
                    "user_message": normalize_chat_message(user_row),
                    "assistant_message": normalize_chat_message(assistant_row),
                },
                status=status.HTTP_201_CREATED,
            )
        except SupabaseConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
