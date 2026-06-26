import json
import re
from typing import Any, Dict, List

import requests
from django.conf import settings


FLASHCARD_SYSTEM_PROMPT = """
Ban la cong cu tao flashcard hoc tap bang tieng Viet. Chi tao the dua tren noi dung tai lieu duoc cung cap, khong bia them thong tin.
Tra ve JSON thuan, khong markdown, khong giai thich ngoai JSON.
""".strip()


def normalize_flashcard(row: Dict[str, Any]) -> Dict[str, Any]:
    if not row:
        return {}
    cards = row.get("cards")
    return {
        "id": row.get("id_flashcard"),
        "id_flashcard": row.get("id_flashcard"),
        "user_id": row.get("id_user"),
        "read_id": row.get("id_read"),
        "file_name": row.get("file_name"),
        "difficulty": row.get("difficulty"),
        "card_count": int(row.get("card_count") or 0),
        "status": row.get("status"),
        "cards": cards if isinstance(cards, list) else [],
        "error": row.get("error_message"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "latest_attempt": normalize_flashcard_attempt(row.get("latest_attempt") or {}) if row.get("latest_attempt") else None,
    }


def normalize_flashcard_attempt(row: Dict[str, Any]) -> Dict[str, Any]:
    if not row:
        return {}
    return {
        "id": row.get("id_attempt"),
        "id_attempt": row.get("id_attempt"),
        "flashcard_id": row.get("id_flashcard"),
        "user_id": row.get("id_user"),
        "read_id": row.get("id_read"),
        "status": row.get("status"),
        "viewed_count": int(row.get("viewed_count") or 0),
        "total_cards": int(row.get("total_cards") or 0),
        "current_index": int(row.get("current_index") or 0),
        "completion_percent": float(row.get("completion_percent") or 0),
        "elapsed_seconds": int(row.get("elapsed_seconds") or 0),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def calculate_flashcard_progress(*, viewed_count: int, total_cards: int) -> Dict[str, Any]:
    safe_total = max(total_cards, 1)
    safe_viewed = max(0, min(viewed_count, safe_total))
    return {
        "viewed_count": safe_viewed,
        "completion_percent": round((safe_viewed / safe_total) * 100, 2),
    }


def generate_flashcards(
    *,
    source_text: str,
    difficulty: str,
    card_count: int,
) -> Dict[str, Any]:
    api_key = str(getattr(settings, "GROQ_API_KEY", "") or "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY chua duoc cau hinh.")

    source = (source_text or "").strip()
    if not source:
        raise RuntimeError("Khong co noi dung tai lieu de tao flashcard.")

    max_chars = int(getattr(settings, "QUIZ_SOURCE_MAX_CHARS", 16000))
    source = source[:max_chars]

    target_count = int(card_count)
    batch_size = max(5, min(int(getattr(settings, "AI_GENERATION_BATCH_SIZE", 10)), 10))
    cards: List[Dict[str, Any]] = []
    raw_responses: List[str] = []
    attempts = 0
    max_attempts = max(4, (target_count // batch_size + 1) * 3)

    while len(cards) < target_count and attempts < max_attempts:
        attempts += 1
        batch_count = min(batch_size, target_count - len(cards))
        try:
            result = _generate_flashcard_batch(
                api_key=api_key,
                source=source,
                difficulty=difficulty,
                card_count=batch_count,
                target_count=target_count,
                existing_cards=cards,
            )
        except Exception:
            continue
        raw_responses.append(result["raw_response"])
        cards = _merge_unique_cards(cards, result["cards"], target_count=target_count)

    if len(cards) != target_count:
        raise RuntimeError(f"Groq tao {len(cards)}/{target_count} flashcard hop le.")

    return {
        "cards": _renumber_cards(cards),
        "raw_response": "\n\n---BATCH---\n\n".join(raw_responses),
    }


def _generate_flashcard_batch(
    *,
    api_key: str,
    source: str,
    difficulty: str,
    card_count: int,
    target_count: int,
    existing_cards: List[Dict[str, Any]],
) -> Dict[str, Any]:
    existing_text = _existing_cards_text(existing_cards)
    user_prompt = f"""
Do kho: {difficulty}
So the can tao trong lan nay: {card_count}
Tong so the muc tieu: {target_count}

Yeu cau:
- Tra ve dung schema:
{{"cards":[{{"front":"...","back":"..."}}]}}
- cards co dung {card_count} phan tu.
- Moi the co mat truoc (front) la cau hoi ngan gon hoac yeu cau goi nho mot khai niem trong tai lieu.
- Mat sau (back) la cau tra loi chinh xac, ngan gon, de hoc thuoc.
- Noi dung front/back viet bang tieng Viet.
- Moi the hoc mot y khac nhau; khong lap lai cau hoi, khong lap lai cung mot y bang cach doi tu ngu nhe.
- Khong bia dat thong tin ngoai tai lieu. Neu tai lieu khong du thong tin, tao the o muc tong quat nhung van phai dua tren noi dung co trong tai lieu.

Nhung the da co, khong duoc lap lai:
{existing_text}

Tai lieu:
{source}
""".strip()

    payload = {
        "model": getattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile"),
        "messages": [
            {"role": "system", "content": FLASHCARD_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "top_p": 0.9,
        "max_tokens": _flashcard_max_tokens(card_count=card_count),
        "response_format": {"type": "json_object"},
    }

    base_url = str(getattr(settings, "GROQ_BASE_URL", "https://api.groq.com/openai/v1")).rstrip("/")
    timeout = int(getattr(settings, "GROQ_TIMEOUT_SECONDS", 120))
    response = requests.post(
        f"{base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Groq loi {response.status_code}: {response.text[:500]}")

    data = response.json()
    choices = data.get("choices") if isinstance(data, dict) else None
    content = ""
    if choices:
        content = str(((choices[0] or {}).get("message") or {}).get("content") or "").strip()
    if not content:
        raise RuntimeError("Groq tra ve noi dung rong.")

    parsed = _parse_json(content)
    cards = _sanitize_cards(parsed.get("cards") if isinstance(parsed, dict) else None, card_count=card_count)
    return {
        "cards": cards,
        "raw_response": content,
    }


def _parse_json(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    match = re.search(r"\{[\s\S]*\}", text)
    candidate = match.group(0) if match else text
    return json.loads(candidate)


def _sanitize_cards(raw_cards: Any, *, card_count: int) -> List[Dict[str, Any]]:
    if not isinstance(raw_cards, list):
        return []
    cards: List[Dict[str, Any]] = []
    seen_fronts = set()
    for index, item in enumerate(raw_cards, start=1):
        if not isinstance(item, dict):
            continue
        front = str(item.get("front") or "").strip()
        back = str(item.get("back") or "").strip()
        key = re.sub(r"\s+", " ", front.lower())
        if not front or not back or key in seen_fronts:
            continue
        seen_fronts.add(key)
        cards.append({
            "number": len(cards) + 1,
            "front": front,
            "back": back,
        })
        if len(cards) == card_count:
            break
    return cards


def _flashcard_max_tokens(*, card_count: int) -> int:
    configured = int(getattr(settings, "FLASHCARD_MAX_OUTPUT_TOKENS", 9000))
    needed = 700 + 260 * max(1, card_count)
    return max(1600, min(configured, needed))


def _existing_cards_text(cards: List[Dict[str, Any]]) -> str:
    if not cards:
        return "Chua co."
    lines = []
    for index, item in enumerate(cards[-20:], start=1):
        front = str(item.get("front") or "").strip()
        if front:
            lines.append(f"{index}. {front[:220]}")
    return "\n".join(lines) if lines else "Chua co."


def _merge_unique_cards(
    current: List[Dict[str, Any]],
    incoming: List[Dict[str, Any]],
    *,
    target_count: int,
) -> List[Dict[str, Any]]:
    merged = list(current)
    seen = {_normalize_card_key(item.get("front")) for item in merged}
    for item in incoming:
        key = _normalize_card_key(item.get("front"))
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(item)
        if len(merged) >= target_count:
            break
    return merged


def _normalize_card_key(value: Any) -> str:
    return re.sub(r"\W+", " ", str(value or "").lower()).strip()


def _renumber_cards(cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            **item,
            "number": index,
        }
        for index, item in enumerate(cards, start=1)
    ]
