from typing import Any, Dict, List

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
        for index, chunk in enumerate(context_chunks, start=1):
            content = str(chunk.get("content") or "").strip()
            if content:
                context_blocks.append(f"[Doan {index}]\n{content}")
        source_context = "\n\n".join(context_blocks).strip()
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
    model = str(getattr(settings, "CHAT_GEMINI_MODEL", "gemini-2.5-flash-lite") or "gemini-2.5-flash-lite").strip()
    timeout = int(getattr(settings, "GEMINI_TIMEOUT_SECONDS", 120))
    response = requests.post(
        f"{base_url}/models/{model}:generateContent",
        params={"key": api_key},
        json={
            "contents": [{"parts": [{"text": f"{CHAT_SYSTEM_PROMPT}\n\n{prompt}"}]}],
            "generationConfig": {
                "temperature": 0.35,
                "topP": 0.9,
                "maxOutputTokens": 700,
            },
        },
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Gemini loi {response.status_code}: {response.text[:500]}")

    text = _extract_gemini_text(response.json()).strip()
    if not text:
        raise RuntimeError("Gemini tra ve noi dung rong.")
    return text


def _extract_gemini_text(payload: Dict[str, Any]) -> str:
    candidates = payload.get("candidates") if isinstance(payload, dict) else None
    if not candidates:
        raise RuntimeError("Gemini khong tra ve candidates.")
    parts = (((candidates[0] or {}).get("content") or {}).get("parts") or [])
    return "\n".join(str(part.get("text") or "") for part in parts if isinstance(part, dict)).strip()
