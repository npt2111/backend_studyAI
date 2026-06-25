import time
from typing import Any, Dict, List, Optional

import requests
from django.conf import settings


CHAT_GREETING = (
    "Xin chào, mình là StudyBuddy AI. Mình đã sẵn sàng đọc cùng bạn tài liệu này. "
    "Bạn muốn hỏi phần nào trước?"
)

CHAT_SYSTEM_PROMPT = """
Bạn là StudyBuddy AI, trợ lý học tập thân thiện.
Bắt buộc trả lời 100% bằng tiếng Việt có dấu.
Chỉ trả lời dựa trên NGỮ CẢNH RAG TỪ TÀI LIỆU và lịch sử chat được cung cấp.
Nếu tài liệu không có đủ thông tin, nói rõ "Trong tài liệu này mình chưa thấy thông tin đó" và gợi ý người dùng hỏi theo phần có trong tài liệu.
Trả lời đúng trọng tâm, tự nhiên, không dài dòng.
Ưu tiên 3-6 câu; chỉ dùng gạch đầu dòng ngắn khi thật sự cần.
Không dùng tiếng Anh trừ tên riêng, thuật ngữ kỹ thuật bắt buộc, mã lệnh hoặc ký hiệu trong tài liệu.
Không bịa đặt ngoài tài liệu.
""".strip()


class AiChatError(RuntimeError):
    public_message = "AI đang bận, vui lòng thử lại sau."
    status_code = 502

    def __init__(self, public_message: Optional[str] = None, *, status_code: int = 502, detail: str = ""):
        super().__init__(public_message or self.public_message)
        self.public_message = public_message or self.public_message
        self.status_code = status_code
        self.detail = detail


class AiChatTemporaryError(AiChatError):
    public_message = "AI đang quá tải, vui lòng thử lại sau ít phút."
    status_code = 503


# Backward-compatible import name for older view code.
GeminiChatError = AiChatError


def normalize_chat_session(row: Dict[str, Any]) -> Dict[str, Any]:
    if not row:
        return {}
    return {
        "id": row.get("id_chat_session"),
        "id_chat_session": row.get("id_chat_session"),
        "user_id": row.get("id_user"),
        "read_id": row.get("id_read"),
        "file_name": row.get("file_name"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def normalize_chat_message(row: Dict[str, Any]) -> Dict[str, Any]:
    if not row:
        return {}
    return {
        "id": row.get("id_message"),
        "id_message": row.get("id_message"),
        "session_id": row.get("id_chat_session"),
        "user_id": row.get("id_user"),
        "read_id": row.get("id_read"),
        "role": row.get("role"),
        "content": row.get("content") or "",
        "created_at": row.get("created_at"),
    }


def generate_document_chat_reply(
    *,
    source_text: str,
    file_name: str,
    history: List[Dict[str, Any]],
    user_message: str,
    context_chunks: List[Dict[str, Any]] = None,
) -> str:
    source = (source_text or "").strip()
    context_chunks = context_chunks or []
    api_key = _chat_groq_api_key()
    if not api_key:
        return _fallback_chat_reply(
            source_text=source,
            file_name=file_name,
            history=history,
            context_chunks=context_chunks,
            user_message=user_message,
            reason="CHAT_GROQ_API_KEY hoặc GROQ_API_KEY_2 chưa được cấu hình.",
        )
    if not source and not context_chunks:
        return _fallback_chat_reply(
            source_text=source,
            file_name=file_name,
            history=history,
            context_chunks=context_chunks,
            user_message=user_message,
            reason="Không có nội dung tài liệu để trả lời.",
        )

    source_context = _build_rag_context(source_text=source, context_chunks=context_chunks)
    history_text = _build_history_text(history)
    prompt = f"""
Tên tài liệu: {file_name or "Document"}

NGỮ CẢNH RAG TỪ TÀI LIỆU:
{source_context}

LỊCH SỬ CHAT GẦN ĐÂY:
{history_text}

CÂU HỎI CỦA NGƯỜI HỌC:
{user_message}

Yêu cầu trả lời:
- Trả lời 100% bằng tiếng Việt có dấu.
- Bám sát ngữ cảnh RAG, đúng trọng tâm câu hỏi.
- Không trả lời dài dòng; mặc định 3-6 câu.
- Nếu cần liệt kê, dùng gạch đầu dòng ngắn.
- Nếu ngữ cảnh không đủ thông tin, nói rõ mình chưa thấy thông tin đó trong tài liệu.
- Không dùng tiếng Anh trừ tên riêng, thuật ngữ kỹ thuật bắt buộc, mã lệnh hoặc ký hiệu trong tài liệu.
""".strip()

    base_url = str(getattr(settings, "GROQ_BASE_URL", "https://api.groq.com/openai/v1")).rstrip("/")
    timeout = int(getattr(settings, "CHAT_GROQ_TIMEOUT_SECONDS", getattr(settings, "GROQ_TIMEOUT_SECONDS", 120)))
    payload = {
        "messages": [
            {"role": "system", "content": CHAT_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.25,
        "top_p": 0.9,
        "max_tokens": int(getattr(settings, "CHAT_MAX_OUTPUT_TOKENS", 850)),
    }

    try:
        response_payload = _post_groq_with_retry(
            base_url=base_url,
            api_key=api_key,
            models=_chat_model_candidates(),
            payload=payload,
            timeout=timeout,
        )
        text = _extract_groq_text(response_payload).strip()
        if text:
            return text
    except AiChatTemporaryError as exc:
        return _fallback_chat_reply(
            source_text=source,
            file_name=file_name,
            history=history,
            context_chunks=context_chunks,
            user_message=user_message,
            reason=exc.public_message,
        )
    except AiChatError as exc:
        return _fallback_chat_reply(
            source_text=source,
            file_name=file_name,
            history=history,
            context_chunks=context_chunks,
            user_message=user_message,
            reason=exc.public_message,
        )
    except Exception as exc:
        return _fallback_chat_reply(
            source_text=source,
            file_name=file_name,
            history=history,
            context_chunks=context_chunks,
            user_message=user_message,
            reason=f"Lỗi ngoài ý muốn khi gọi AI: {exc}",
        )

    return _fallback_chat_reply(
        source_text=source,
        file_name=file_name,
        history=history,
        context_chunks=context_chunks,
        user_message=user_message,
        reason="AI chưa tạo được câu trả lời, vui lòng thử lại.",
    )


def _chat_groq_api_key() -> str:
    return str(
        getattr(settings, "CHAT_GROQ_API_KEY", "")
        or getattr(settings, "GROQ_API_KEY_2", "")
        or ""
    ).strip()


def _chat_model_candidates() -> List[str]:
    primary = str(getattr(settings, "CHAT_GROQ_MODEL", getattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile"))).strip()
    fallback_raw = str(getattr(settings, "GROQ_FALLBACK_MODELS", "") or "").strip()
    models = [primary] if primary else []
    models.extend(model.strip() for model in fallback_raw.split(",") if model.strip())
    unique_models: List[str] = []
    for model in models:
        if model and model not in unique_models:
            unique_models.append(model)
    return unique_models or ["llama-3.3-70b-versatile"]


def _build_rag_context(*, source_text: str, context_chunks: List[Dict[str, Any]]) -> str:
    if context_chunks:
        max_chunk_chars = int(getattr(settings, "CHAT_CONTEXT_CHUNK_MAX_CHARS", 3500))
        max_context_chars = int(getattr(settings, "CHAT_CONTEXT_MAX_CHARS", 26000))
        blocks: List[str] = []
        seen = set()
        for index, chunk in enumerate(context_chunks, start=1):
            content = str(chunk.get("content") or "").strip()
            if not content:
                continue
            key = " ".join(content.lower().split())[:180]
            if key in seen:
                continue
            seen.add(key)
            chunk_index = chunk.get("chunk_index", index)
            blocks.append(f"[Đoạn {chunk_index}]\n{content[:max_chunk_chars]}")
        context = "\n\n".join(blocks).strip()
        if context:
            return context[:max_context_chars]

    return source_text[: int(getattr(settings, "CHAT_SOURCE_MAX_CHARS", 30000))]


def _build_history_text(history: List[Dict[str, Any]]) -> str:
    history_lines: List[str] = []
    for item in history[-int(getattr(settings, "CHAT_HISTORY_LIMIT", 12)):]:
        role = "Người học" if item.get("role") == "user" else "StudyBuddy"
        content = str(item.get("content") or "").strip()
        if content:
            history_lines.append(f"{role}: {content}")
    return "\n".join(history_lines) if history_lines else "Chưa có."


def _post_groq_with_retry(
    *,
    base_url: str,
    api_key: str,
    models: List[str],
    payload: Dict[str, Any],
    timeout: int,
) -> Dict[str, Any]:
    retry_count = max(1, int(getattr(settings, "GROQ_RETRY_COUNT", 2)))
    retry_delay = float(getattr(settings, "GROQ_RETRY_DELAY_SECONDS", 0.8))
    last_status = 0
    last_detail = ""

    for model in models:
        model_payload = {**payload, "model": model}
        for attempt in range(retry_count + 1):
            try:
                response = requests.post(
                    f"{base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=model_payload,
                    timeout=timeout,
                )
            except requests.Timeout as exc:
                last_status = 504
                last_detail = str(exc)
                if attempt < retry_count:
                    time.sleep(retry_delay * (attempt + 1))
                    continue
                break
            except requests.RequestException as exc:
                last_status = 503
                last_detail = str(exc)
                if attempt < retry_count:
                    time.sleep(retry_delay * (attempt + 1))
                    continue
                break

            if response.status_code < 400:
                try:
                    return response.json()
                except ValueError as exc:
                    raise AiChatError("AI trả về dữ liệu không hợp lệ.", detail=str(exc))

            last_status = response.status_code
            last_detail = _extract_ai_error_message(response)
            if response.status_code in {400, 404}:
                break
            if response.status_code in {429, 500, 502, 503, 504} and attempt < retry_count:
                time.sleep(retry_delay * (attempt + 1))
                continue
            break

    if last_status in {429, 500, 502, 503, 504}:
        raise AiChatTemporaryError(detail=last_detail)
    raise AiChatError("AI chưa trả lời được, vui lòng thử lại.", status_code=502, detail=last_detail)


def _extract_ai_error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:300]
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("status") or "")[:300]
    return str(payload)[:300]


def _extract_groq_text(payload: Dict[str, Any]) -> str:
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not choices:
        raise AiChatError("AI chưa tạo được câu trả lời, vui lòng thử lại.")
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first, dict) else {}
    text = str((message or {}).get("content") or "").strip()
    if text:
        return text
    finish_reason = str(first.get("finish_reason") or "").strip()
    if finish_reason:
        raise AiChatTemporaryError(detail=finish_reason)
    raise AiChatError("AI chưa tạo được câu trả lời, vui lòng thử lại.")


def _fallback_chat_reply(
    *,
    source_text: str,
    file_name: str,
    history: List[Dict[str, Any]],
    context_chunks: List[Dict[str, Any]],
    user_message: str,
    reason: str,
) -> str:
    pieces: List[str] = []
    if context_chunks:
        for chunk in context_chunks[:4]:
            content = str(chunk.get("content") or "").strip()
            if content:
                pieces.append(content)
    if not pieces and source_text.strip():
        pieces = [source_text.strip()[:1600]]

    excerpt = "\n".join(f"- {text[:360]}" for text in pieces[:4]).strip()
    if not excerpt:
        excerpt = "Mình chưa trích được đủ nội dung liên quan từ tài liệu."

    lead = f"Trong tài liệu {file_name or 'này'}, mình thấy phần liên quan nhất là:"
    if user_message.strip():
        lead = f'Với câu hỏi "{user_message.strip()}", trong tài liệu {file_name or "này"} mình thấy phần liên quan nhất là:'

    tail = "Bạn có thể hỏi cụ thể hơn một ý để mình khoanh đúng đoạn cần xem."
    if reason:
        tail = f"{tail} Tạm thời AI chưa tạo được câu trả lời trực tiếp, nên mình trả lời bằng phần nội dung tài liệu liên quan nhất."
    return f"{lead}\n{excerpt}\n\n{tail}".strip()
