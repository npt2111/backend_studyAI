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
Khong bia dat, khong lan man, khong tra loi qua dai.
Giai thich muot ma, dung trong tam, co the dung bullet ngan neu can.
""".strip()


class GeminiChatError(RuntimeError):
    public_message = "AI dang ban, vui long thu lai sau."
    status_code = 502

    def __init__(self, public_message: Optional[str] = None, *, status_code: int = 502, detail: str = ""):
        super().__init__(public_message or self.public_message)
        self.public_message = public_message or self.public_message
        self.status_code = status_code
        self.detail = detail


class GeminiChatTemporaryError(GeminiChatError):
    public_message = "AI dang qua tai, vui long thu lai sau it phut."
    status_code = 503


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
    api_key = str(getattr(settings, "GEMINI_API_KEY", "") or "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY chua duoc cau hinh.")

    source = (source_text or "").strip()
    if not source:
        raise RuntimeError("Khong co extracted_text de chat voi tai lieu.")
    context_chunks = context_chunks or []
    if context_chunks:
        context_blocks = []
        max_chunk_chars = int(getattr(settings, "CHAT_CONTEXT_CHUNK_MAX_CHARS", 2500))
        max_context_chars = int(getattr(settings, "CHAT_CONTEXT_MAX_CHARS", 12000))
        for index, chunk in enumerate(context_chunks, start=1):
            content = str(chunk.get("content") or "").strip()[:max_chunk_chars]
            if content:
                context_blocks.append(f"[Doan {index}]\n{content}")
        source_context = "\n\n".join(context_blocks).strip()[:max_context_chars]
    else:
        source_context = source[: int(getattr(settings, "CHAT_SOURCE_MAX_CHARS", 18000))]

    history_lines: List[str] = []
    for item in history[-int(getattr(settings, "CHAT_HISTORY_LIMIT", 12)):]:
        role = "Nguoi hoc" if item.get("role") == "user" else "StudyBuddy"
        content = str(item.get("content") or "").strip()
        if content:
            history_lines.append(f"{role}: {content}")

    prompt = f"""
Ten tai lieu: {file_name or "Document"}

NOI DUNG TAI LIEU:
{source_context}

LICH SU CHAT GAN DAY:
{chr(10).join(history_lines) if history_lines else "Chua co."}

CAU HOI CUA NGUOI HOC:
{user_message}

Hay tra loi nhu StudyBuddy AI: than thien, ro rang, dung tai lieu, khong bia dat.
""".strip()

    base_url = str(getattr(settings, "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")).rstrip("/")
    models = _chat_model_candidates()
    timeout = int(getattr(settings, "GEMINI_TIMEOUT_SECONDS", 60))
    payload = {
        "contents": [{"parts": [{"text": f"{CHAT_SYSTEM_PROMPT}\n\n{prompt}"}]}],
        "generationConfig": {
            "temperature": 0.35,
            "topP": 0.9,
            "maxOutputTokens": 700,
        },
    }
    response_payload = _post_gemini_with_retry(
        base_url=base_url,
        api_key=api_key,
        models=models,
        payload=payload,
        timeout=timeout,
    )

    text = _extract_gemini_text(response_payload).strip()
    if not text:
        raise GeminiChatError("AI chua tao duoc cau tra loi, vui long thu lai.")
    return text


def _chat_model_candidates() -> List[str]:
    primary = str(getattr(settings, "CHAT_GEMINI_MODEL", "gemini-2.5-flash-lite") or "gemini-2.5-flash-lite").strip()
    fallback_raw = str(getattr(settings, "CHAT_GEMINI_FALLBACK_MODELS", "gemini-2.0-flash-lite,gemini-1.5-flash") or "")
    candidates = [primary]
    candidates.extend(item.strip() for item in fallback_raw.split(",") if item.strip())
    unique: List[str] = []
    for model in candidates:
        if model and model not in unique:
            unique.append(model)
    return unique or ["gemini-2.5-flash-lite"]


def _post_gemini_with_retry(
    *,
    base_url: str,
    api_key: str,
    models: List[str],
    payload: Dict[str, Any],
    timeout: int,
) -> Dict[str, Any]:
    retry_count = max(1, int(getattr(settings, "CHAT_GEMINI_RETRY_COUNT", 2)))
    retry_delay = float(getattr(settings, "CHAT_GEMINI_RETRY_DELAY_SECONDS", 0.8))
    last_status = 0
    last_detail = ""

    for model in models:
        model_path = model if model.startswith("models/") else f"models/{model}"
        for attempt in range(retry_count + 1):
            try:
                response = requests.post(
                    f"{base_url}/{model_path}:generateContent",
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
                    raise GeminiChatError("AI tra ve du lieu khong hop le.", detail=str(exc))

            last_status = response.status_code
            last_detail = _extract_gemini_error_message(response)
            if response.status_code in {429, 500, 502, 503, 504} and attempt < retry_count:
                time.sleep(retry_delay * (attempt + 1))
                continue
            break

    if last_status in {429, 500, 502, 503, 504}:
        raise GeminiChatTemporaryError(detail=last_detail)
    raise GeminiChatError("AI chua tra loi duoc, vui long thu lai.", status_code=502, detail=last_detail)


def _extract_gemini_error_message(response: requests.Response) -> str:
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
        raise GeminiChatError("AI chua tao duoc cau tra loi, vui long thu lai.")
    parts = (((candidates[0] or {}).get("content") or {}).get("parts") or [])
    return "\n".join(str(part.get("text") or "") for part in parts if isinstance(part, dict)).strip()
