import json
import re
from typing import Any, Dict, List

import requests
from django.conf import settings


MINDMAP_PROMPT = """
Ban la cong cu tao so do tu duy bang tieng Viet. Chi dua tren noi dung tai lieu duoc cung cap, khong bia them thong tin.
Tra ve JSON thuan, khong markdown, khong giai thich ngoai JSON.
""".strip()


def normalize_mindmap(row: Dict[str, Any]) -> Dict[str, Any]:
    if not row:
        return {}
    data = row.get("mindmap_json")
    return {
        "id": row.get("id_mindmap"),
        "id_mindmap": row.get("id_mindmap"),
        "user_id": row.get("id_user"),
        "read_id": row.get("id_read"),
        "file_name": row.get("file_name"),
        "status": row.get("status"),
        "mindmap_json": data if isinstance(data, dict) else {},
        "markdown": row.get("markdown") or "",
        "error": row.get("error_message"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def generate_mindmap(*, source_text: str, file_name: str) -> Dict[str, Any]:
    api_key = str(getattr(settings, "GEMINI_API_KEY", "") or "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY chua duoc cau hinh.")

    source = (source_text or "").strip()
    if not source:
        raise RuntimeError("Khong co extracted_text de tao mindmap.")
    source = source[: int(getattr(settings, "MINDMAP_SOURCE_MAX_CHARS", 18000))]

    prompt = f"""
Tieu de tai lieu: {file_name or "Document"}

Yeu cau JSON:
{{
  "title": "Tieu de trung tam",
  "children": [
    {{"title": "Nhanh chinh", "children": [{{"title": "Y phu"}}]}}
  ]
}}

Quy tac:
- title va children viet bang tieng Viet.
- Tao 4 den 8 nhanh chinh neu tai lieu cho phep.
- Moi nhanh co toi da 5 y phu, ngan gon, de render mindmap.
- Khong lap y, khong bia ngoai tai lieu.
- Khong tra ve markdown, chi tra ve JSON.

Tai lieu:
{source}
""".strip()

    base_url = str(getattr(settings, "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")).rstrip("/")
    model = str(getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash"))
    timeout = int(getattr(settings, "GEMINI_TIMEOUT_SECONDS", 120))
    response = requests.post(
        f"{base_url}/models/{model}:generateContent",
        params={"key": api_key},
        json={
            "contents": [{"parts": [{"text": f"{MINDMAP_PROMPT}\n\n{prompt}"}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        },
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Gemini loi {response.status_code}: {response.text[:500]}")

    payload = response.json()
    text = _extract_gemini_text(payload)
    parsed = _parse_json(text)
    tree = _sanitize_node(parsed)
    markdown = mindmap_json_to_markdown(tree)
    return {
        "mindmap_json": tree,
        "markdown": markdown,
        "raw_response": text,
    }


def mindmap_json_to_markdown(node: Dict[str, Any], level: int = 0) -> str:
    title = str(node.get("title") or "Mindmap").strip()
    prefix = "# " if level == 0 else f"{'  ' * (level - 1)}- "
    lines = [f"{prefix}{title}"]
    for child in node.get("children", []):
        if isinstance(child, dict):
            lines.append(mindmap_json_to_markdown(child, level + 1))
    return "\n".join(lines)


def _extract_gemini_text(payload: Dict[str, Any]) -> str:
    candidates = payload.get("candidates") if isinstance(payload, dict) else None
    if not candidates:
        raise RuntimeError("Gemini khong tra ve candidates.")
    parts = (((candidates[0] or {}).get("content") or {}).get("parts") or [])
    text = "\n".join(str(part.get("text") or "") for part in parts if isinstance(part, dict)).strip()
    if not text:
        raise RuntimeError("Gemini tra ve noi dung rong.")
    return text


def _parse_json(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    match = re.search(r"\{[\s\S]*\}", text)
    candidate = match.group(0) if match else text
    return json.loads(candidate)


def _sanitize_node(raw: Any, depth: int = 0, max_depth: int = 4) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise RuntimeError("Mindmap JSON khong hop le.")
    title = str(raw.get("title") or "").strip()
    if not title:
        raise RuntimeError("Mindmap thieu title.")
    children: List[Dict[str, Any]] = []
    raw_children = raw.get("children")
    if depth < max_depth and isinstance(raw_children, list):
        for child in raw_children[:10]:
            try:
                children.append(_sanitize_node(child, depth + 1, max_depth))
            except RuntimeError:
                continue
    return {"title": title, "children": children}
