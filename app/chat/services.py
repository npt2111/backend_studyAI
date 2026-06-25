import time
from typing import Any, Dict, List, Optional

import requests
from django.conf import settings


CHAT_GREETING = (
    "Xin chao, minh la StudyBuddy AI. Minh da san sang doc cung ban tai lieu nay. "
    "Ban muon hoi phan nao truoc?"
)

CHAT_SYSTEM_PROMPT = """
Ban la StudyBuddy AI, tro ly hoc tap than thien bang tieng Viet.
Chi tra loi dua tren NOI DUNG TAI LIEU duoc cung cap va lich su hoi dap trong phien chat.
Neu tai lieu khong co du thong tin, noi ro "Trong tai lieu nay minh chua thay thong tin do" va goi y nguoi dung hoi theo phan co trong tai lieu.
Tra loi than thien, dung trong tam, khong dai dong.
Uu tien cau tra loi ngan gon 3-6 cau; chi dung bullet khi that su can.
Khong bia dat ngoai tai lieu.
""".strip()


class AiChatError(RuntimeError):
    public_message = "AI dang ban, vui long thu lai sau."
    status_code = 502

    def __init__(self, public_message: Optional[str] = None, *, status_code: int = 502, detail: str = ""):
        super().__init__(public_message or self.public_message)
        self.public_message = public_message or self.public_message
        self.status_code = status_code
        self.detail = detail


class AiChatTemporaryError(AiChatError):
    public_message = "AI dang qua tai, vui long thu lai sau it phut."
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
            reason="CHAT_GROQ_API_KEY hoac GROQ_API_KEY_2 chua duoc cau hinh.",
        )
    if not source and not context_chunks:
        return _fallback_chat_reply(
            source_text=source,
            file_name=file_name,
            history=history,
            context_chunks=context_chunks,
            reason="Khong co noi dung tai lieu de tra loi.",
        )

    source_context = _build_rag_context(source_text=source, context_chunks=context_chunks)
    history_text = _build_history_text(history)
    prompt = f"""
Ten tai lieu: {file_name or "Document"}

NGU CANH RAG TU TAI LIEU:
{source_context}

LICH SU CHAT GAN DAY:
{history_text}

CAU HOI CUA NGUOI HOC:
{user_message}

Yeu cau tra loi:
- Tra loi bang tieng Viet, tu nhien va than thien.
- Bam sat ngu canh RAG, dung trong tam cau hoi.
- Khong tra loi dai dong; mac dinh 3-6 cau.
- Neu can liet ke, dung bullet ngan.
- Neu ngu canh khong du thong tin, noi ro minh chua thay thong tin do trong tai lieu.
""".strip()

    base_url = str(getattr(settings, "GROQ_BASE_URL", "https://api.groq.com/openai/v1")).rstrip("/")
    timeout = int(getattr(settings, "CHAT_GROQ_TIMEOUT_SECONDS", getattr(settings, "GROQ_TIMEOUT_SECONDS", 120)))
    payload = {
        "systemInstruction": {
            "parts": [
                {
                    "text": CHAT_SYSTEM_PROMPT,
                }
            ]
        },
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": prompt,
                    }
                ],
            }
        ],
        "temperature": 0.25,
        "top_p": 0.9,
        "max_tokens": int(getattr(settings, "CHAT_MAX_OUTPUT_TOKENS", 850)),
    }

    try:
        response_payload = _post_gemini_with_retry(
            base_url=base_url,
            api_key=api_key,
            models=_chat_model_candidates(),
            payload=payload,
            timeout=timeout,
        )
        text = _extract_gemini_text(response_payload).strip()
        if text:
            return text
    except AiChatTemporaryError as exc:
        return _fallback_chat_reply(
            source_text=source,
            file_name=file_name,
            history=history,
            context_chunks=context_chunks,
            reason=exc.public_message,
        )
    except AiChatError as exc:
        return _fallback_chat_reply(
            source_text=source,
            file_name=file_name,
            history=history,
            context_chunks=context_chunks,
            reason=exc.public_message,
        )

    return _fallback_chat_reply(
        source_text=source,
        file_name=file_name,
        history=history,
        context_chunks=context_chunks,
        reason="AI chua tao duoc cau tra loi, vui long thu lai.",
    )


def _chat_groq_api_key() -> str:
    return str(
        getattr(settings, "CHAT_GROQ_API_KEY", "")
        or getattr(settings, "GROQ_API_KEY_2", "")
        or ""
    ).strip()


def _chat_model_candidates() -> List[str]:
    primary = str(
        getattr(settings, "CHAT_GEMINI_MODEL", getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash-lite"))
        or "gemini-2.5-flash-lite"
    ).strip()
    return primary or "gemini-2.5-flash-lite"


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
            blocks.append(f"[Doan {chunk_index}]\n{content[:max_chunk_chars]}")
        context = "\n\n".join(blocks).strip()
        if context:
            return context[:max_context_chars]

    return source_text[: int(getattr(settings, "CHAT_SOURCE_MAX_CHARS", 30000))]


def _build_history_text(history: List[Dict[str, Any]]) -> str:
    history_lines: List[str] = []
    for item in history[-int(getattr(settings, "CHAT_HISTORY_LIMIT", 12)):]:
        role = "Nguoi hoc" if item.get("role") == "user" else "StudyBuddy"
        content = str(item.get("content") or "").strip()
        if content:
            history_lines.append(f"{role}: {content}")
    return "\n".join(history_lines) if history_lines else "Chua co."


def _post_groq_with_retry(
    *,
    base_url: str,
    api_key: str,
    model: str,
    payload: Dict[str, Any],
    timeout: int,
) -> Dict[str, Any]:
    retry_count = max(1, int(getattr(settings, "GEMINI_RETRY_COUNT", 2)))
    retry_delay = float(getattr(settings, "GEMINI_RETRY_DELAY_SECONDS", 0.8))
    last_status = 0
    last_detail = ""

    for attempt in range(retry_count + 1):
        try:
            response = requests.post(
                f"{base_url}/models/{model}:generateContent",
                params={"key": api_key},
                json=payload,
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
                raise AiChatError("AI tra ve du lieu khong hop le.", detail=str(exc))

        last_status = response.status_code
        last_detail = _extract_ai_error_message(response)
        if response.status_code in {429, 500, 502, 503, 504} and attempt < retry_count:
            time.sleep(retry_delay * (attempt + 1))
            continue
        break

    if last_status in {429, 500, 502, 503, 504}:
        raise AiChatTemporaryError(detail=last_detail)
    raise AiChatError("AI chua tra loi duoc, vui long thu lai.", status_code=502, detail=last_detail)


def _extract_ai_error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:300]
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("status") or "")[:300]
    return str(payload)[:300]


def _extract_gemini_text(payload: Dict[str, Any]) -> str:
    candidates = payload.get("candidates") if isinstance(payload, dict) else None
    if not candidates:
        raise AiChatError("AI chua tao duoc cau tra loi, vui long thu lai.")
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first, dict) else {}
    text = str((message or {}).get("content") or "").strip()
    if text:
        return text
    finish_reason = str(first.get("finish_reason") or "").strip()
    if finish_reason:
        raise AiChatTemporaryError(detail=finish_reason)
    raise AiChatError("AI chua tao duoc cau tra loi, vui long thu lai.")


def _fallback_chat_reply(
    *,
    source_text: str,
    file_name: str,
    history: List[Dict[str, Any]],
    context_chunks: List[Dict[str, Any]],
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
        excerpt = "Minh chua trich duoc du noi dung lien quan tu tai lieu."

    recent_q = ""
    for item in reversed(history):
        if str(item.get("role") or "").lower() == "user":
            recent_q = str(item.get("content") or "").strip()
            if recent_q:
                break

    lead = f"Trong tai lieu {file_name or 'nay'}, minh thay phan lien quan nhat la:"
    if recent_q:
        lead = f'Voi cau hoi "{recent_q}", trong tai lieu {file_name or "nay"} minh thay phan lien quan nhat la:'

    tail = "Ban co the hoi cu the hon mot y de minh khoanh dung doan can xem."
    if reason:
        tail = f"{tail} (Tam thoi AI chua tao duoc cau tra loi truc tiep, nen minh tra loi bang noi dung tai lieu.)"
    return f"{lead}\n{excerpt}\n\n{tail}".strip()
