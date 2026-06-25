import json
import re
import time
from typing import Any, Dict, List

import requests
from django.conf import settings


MINDMAP_PROMPT = """
Ban la cong cu tao so do tu duy bang tieng Viet. Chi dua tren noi dung tai lieu duoc cung cap, khong bia them thong tin.
Tra ve JSON thuan, khong markdown, khong giai thich ngoai JSON.
So do can co dang cay ro rang, khong duoc qua ngan.
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
    api_key = str(getattr(settings, "GROQ_API_KEY", "") or "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY chua duoc cau hinh.")

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
- Tao 6 den 10 nhanh chinh neu tai lieu co du noi dung.
- Moi nhanh co 3 den 6 y phu, ngan gon nhung khong duoc qua tiet kiem.
- Khong lap y, khong bia ngoai tai lieu.
- Khong tra ve markdown, chi tra ve JSON.
- Neu tai lieu dai, uu tien bao phu day du noi dung hon la rut gon.
- Khong lam so do 1-2 nhanh; phai mo rong cac y chinh co trong tai lieu.

Tai lieu:
{source}
""".strip()

    base_url = str(getattr(settings, "GROQ_BASE_URL", "https://api.groq.com/openai/v1")).rstrip("/")
    timeout = int(getattr(settings, "GROQ_TIMEOUT_SECONDS", 120))
    payload = _post_groq_with_retry(
        base_url=base_url,
        api_key=api_key,
        models=_mindmap_model_candidates(),
        payload={
            "messages": [
                {"role": "system", "content": MINDMAP_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 1400,
            "response_format": {"type": "json_object"},
        },
        timeout=timeout,
    )
    text = _extract_groq_text(payload)
    parsed = _parse_json(text)
    tree = _sanitize_node(parsed)
    if _mindmap_too_shallow(tree):
        tree = _fallback_mindmap_from_text(source_text=source, file_name=file_name)
    markdown = mindmap_json_to_markdown(tree)
    return {
        "mindmap_json": tree,
        "markdown": markdown,
        "raw_response": text,
    }


def _mindmap_model_candidates() -> List[str]:
    primary = str(
        getattr(settings, "MINDMAP_GROQ_MODEL", getattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile"))
        or "llama-3.3-70b-versatile"
    ).strip()
    fallback_raw = str(getattr(settings, "GROQ_FALLBACK_MODELS", "llama-3.1-8b-instant") or "")
    candidates = [primary]
    candidates.extend(item.strip() for item in fallback_raw.split(",") if item.strip())
    unique: List[str] = []
    for model in candidates:
        if model and model not in unique:
            unique.append(model)
    return unique or ["llama-3.3-70b-versatile"]


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
    last_error = ""

    for model in models:
        for attempt in range(retry_count + 1):
            try:
                response = requests.post(
                    f"{base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={**payload, "model": model},
                    timeout=timeout,
                )
            except requests.RequestException as exc:
                last_error = str(exc)
                if attempt < retry_count:
                    time.sleep(retry_delay * (attempt + 1))
                    continue
                break

            if response.status_code < 400:
                return response.json()

            last_error = f"Groq loi {response.status_code}: {response.text[:300]}"
            if response.status_code in {429, 500, 502, 503, 504} and attempt < retry_count:
                time.sleep(retry_delay * (attempt + 1))
                continue
            break

    raise RuntimeError(last_error or "Groq tao mindmap that bai.")


def mindmap_json_to_markdown(node: Dict[str, Any], level: int = 0) -> str:
    title = str(node.get("title") or "Mindmap").strip()
    prefix = "# " if level == 0 else f"{'  ' * (level - 1)}- "
    lines = [f"{prefix}{title}"]
    for child in node.get("children", []):
        if isinstance(child, dict):
            lines.append(mindmap_json_to_markdown(child, level + 1))
    return "\n".join(lines)


def _extract_groq_text(payload: Dict[str, Any]) -> str:
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not choices:
        raise RuntimeError("Groq khong tra ve choices.")
    message = (choices[0] or {}).get("message") if isinstance(choices[0], dict) else {}
    text = str((message or {}).get("content") or "").strip()
    if not text:
        raise RuntimeError("Groq tra ve noi dung rong.")
    return text


def _parse_json(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    match = re.search(r"\{[\s\S]*\}", text)
    candidate = match.group(0) if match else text
    return json.loads(candidate)


def _sanitize_node(raw: Any, depth: int = 0, max_depth: int = 5) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise RuntimeError("Mindmap JSON khong hop le.")
    title = str(raw.get("title") or "").strip()
    if not title:
        raise RuntimeError("Mindmap thieu title.")
    children: List[Dict[str, Any]] = []
    raw_children = raw.get("children")
    if depth < max_depth and isinstance(raw_children, list):
        for child in raw_children[:12]:
            try:
                children.append(_sanitize_node(child, depth + 1, max_depth))
            except RuntimeError:
                continue
    return {"title": title, "children": children}


def _mindmap_too_shallow(tree: Dict[str, Any]) -> bool:
    if not isinstance(tree, dict):
        return True
    children = tree.get("children")
    if not isinstance(children, list):
        return True
    node_count = 0
    stack = [tree]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        node_count += 1
        raw_children = node.get("children")
        if isinstance(raw_children, list):
            stack.extend(child for child in raw_children if isinstance(child, dict))
    return len(children) < 4 or node_count < 8


def _fallback_mindmap_from_text(*, source_text: str, file_name: str) -> Dict[str, Any]:
    text = (source_text or "").strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    key_lines: List[str] = []
    for line in lines:
        if line.startswith("- "):
            candidate = line[2:].strip()
            if candidate:
                key_lines.append(candidate)
        elif line.startswith("[Doan "):
            continue
    if not key_lines:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        key_lines = [sentence.strip() for sentence in sentences if sentence.strip()]

    children = []
    seen = set()
    for item in key_lines:
        normalized = re.sub(r"\s+", " ", item).strip()
        if not normalized:
            continue
        key = normalized.lower()[:120]
        if key in seen:
            continue
        seen.add(key)
        children.append(
            {
                "title": normalized[:120],
                "children": [],
            }
        )
        if len(children) >= 10:
            break

    if not children:
        children = [{"title": "Noi dung tai lieu", "children": []}]

    return {
        "title": file_name or "Document",
        "children": children,
    }
