import json
import re
from typing import Any, Dict, List

import requests
from django.conf import settings

from config.services import supabase_client


def split_text_into_chunks(text: str) -> List[Dict[str, Any]]:
    words = (text or "").split()
    if not words:
        return []

    chunk_words = max(120, int(getattr(settings, "DOCUMENT_CHUNK_WORDS", 450)))
    overlap = max(0, min(int(getattr(settings, "DOCUMENT_CHUNK_OVERLAP_WORDS", 80)), chunk_words // 2))
    step = max(1, chunk_words - overlap)

    chunks: List[Dict[str, Any]] = []
    start = 0
    while start < len(words):
        selected = words[start:start + chunk_words]
        content = " ".join(selected).strip()
        if content:
            chunks.append(
                {
                    "chunk_index": len(chunks),
                    "content": content,
                    "token_count": len(selected),
                }
            )
        if start + chunk_words >= len(words):
            break
        start += step
    return chunks


def embed_text(text: str, *, task_type: str) -> List[float]:
    embeddings = embed_texts([text], task_type=task_type)
    if not embeddings:
        raise RuntimeError("Gemini embedding tra ve vector rong.")
    return embeddings[0]


def embed_texts(texts: List[str], *, task_type: str) -> List[List[float]]:
    clean_texts = [str(text or "").strip() for text in texts if str(text or "").strip()]
    if not clean_texts:
        return []

    api_key = str(getattr(settings, "GEMINI_API_KEY", "") or "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY chua duoc cau hinh.")

    model = str(getattr(settings, "GEMINI_EMBEDDING_MODEL", "gemini-embedding-001") or "").strip()
    if not model:
        raise RuntimeError("GEMINI_EMBEDDING_MODEL chua duoc cau hinh.")
    model_path = model if model.startswith("models/") else f"models/{model}"

    base_url = str(getattr(settings, "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")).rstrip("/")
    timeout = int(getattr(settings, "GEMINI_TIMEOUT_SECONDS", 120))
    output_dimensions = int(getattr(settings, "GEMINI_EMBEDDING_DIMENSIONS", 768))
    requests_payload = [
        {
            "model": model_path,
            "content": {"parts": [{"text": text}]},
            "taskType": task_type,
            "outputDimensionality": output_dimensions,
        }
        for text in clean_texts
    ]
    response = requests.post(
        f"{base_url}/{model_path}:batchEmbedContents",
        params={"key": api_key},
        json={"requests": requests_payload},
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Gemini embedding loi {response.status_code}: {response.text[:500]}")

    data = response.json()
    raw_embeddings = data.get("embeddings") if isinstance(data, dict) else None
    if not isinstance(raw_embeddings, list) or not raw_embeddings:
        raise RuntimeError("Gemini embedding tra ve vector rong.")

    embeddings: List[List[float]] = []
    for item in raw_embeddings:
        values = (item.get("values") or []) if isinstance(item, dict) else []
        if not isinstance(values, list) or not values:
            raise RuntimeError("Gemini embedding tra ve vector rong.")
        embedding = [float(value) for value in values]
        if len(embedding) != output_dimensions:
            raise RuntimeError(f"Gemini embedding tra ve {len(embedding)} chieu, can {output_dimensions} chieu.")
        embeddings.append(embedding)
    if len(embeddings) != len(clean_texts):
        raise RuntimeError(f"Gemini embedding tra ve {len(embeddings)}/{len(clean_texts)} vector.")
    return embeddings


def index_document_chunks(*, user_id: str, read_id: str, source_text: str) -> int:
    chunks = split_text_into_chunks(source_text)
    if not chunks:
        return 0

    supabase_client.delete_document_chunks_by_read(read_id)
    indexed = 0
    batch_size = max(1, min(int(getattr(settings, "GEMINI_EMBEDDING_BATCH_SIZE", 50)), 100))
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start:start + batch_size]
        embeddings = embed_texts(
            [str(chunk["content"]) for chunk in batch],
            task_type="RETRIEVAL_DOCUMENT",
        )
        for chunk, embedding in zip(batch, embeddings):
            row, status_code = supabase_client.create_document_chunk(
                user_id=user_id,
                read_id=read_id,
                chunk_index=int(chunk["chunk_index"]),
                content=str(chunk["content"]),
                embedding=embedding,
                token_count=int(chunk["token_count"]),
            )
            if status_code >= 400:
                raise RuntimeError(f"Luu document chunk that bai: {row}")
            indexed += 1
    return indexed


def ensure_document_chunks_indexed(*, user_id: str, read_id: str, source_text: str) -> int:
    count, status_code = supabase_client.count_document_chunks_by_read(user_id=user_id, read_id=read_id)
    if status_code < 400 and count > 0:
        return count
    return index_document_chunks(user_id=user_id, read_id=read_id, source_text=source_text)


def retrieve_relevant_chunks(*, user_id: str, read_id: str, query: str) -> List[Dict[str, Any]]:
    query_embedding = embed_text(query, task_type="RETRIEVAL_QUERY")
    rows, status_code = supabase_client.match_document_chunks(
        user_id=user_id,
        read_id=read_id,
        query_embedding=query_embedding,
        match_count=int(getattr(settings, "RAG_MATCH_LIMIT", 5)),
        match_threshold=float(getattr(settings, "RAG_MATCH_THRESHOLD", 0.2)),
    )
    if status_code >= 400:
        raise RuntimeError("Truy van document chunks that bai.")
    return rows


def retrieve_task_chunks(
    *,
    user_id: str,
    read_id: str,
    query: str,
    match_count: int,
    match_threshold: float = None,
) -> List[Dict[str, Any]]:
    query_embedding = embed_text(query, task_type="RETRIEVAL_QUERY")
    rows, status_code = supabase_client.match_document_chunks(
        user_id=user_id,
        read_id=read_id,
        query_embedding=query_embedding,
        match_count=match_count,
        match_threshold=(
            float(match_threshold)
            if match_threshold is not None
            else float(getattr(settings, "RAG_MATCH_THRESHOLD", 0.2))
        ),
    )
    if status_code >= 400:
        raise RuntimeError("Truy van document chunks that bai.")
    return rows


def get_or_create_document_summary(
    *,
    user_id: str,
    read_id: str,
    source_text: str,
    file_name: str,
) -> Dict[str, Any]:
    existing, existing_status = supabase_client.get_document_summary_by_read(user_id=user_id, read_id=read_id)
    if existing_status < 400 and existing and str(existing.get("status") or "") == "done":
        if str(existing.get("summary") or "").strip():
            return existing

    result = generate_document_summary(source_text=source_text, file_name=file_name)
    saved, saved_status = supabase_client.upsert_document_summary(
        user_id=user_id,
        read_id=read_id,
        file_name=file_name,
        summary=result["summary"],
        key_points=result["key_points"],
        raw_response=result["raw_response"],
    )
    if saved_status >= 400:
        raise RuntimeError(f"Luu document summary that bai: {saved}")
    return saved


def generate_document_summary(*, source_text: str, file_name: str) -> Dict[str, Any]:
    api_key = str(getattr(settings, "GROQ_API_KEY", "") or "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY chua duoc cau hinh.")

    sampled_text = _sample_document_text(source_text)
    if not sampled_text:
        raise RuntimeError("Khong co noi dung de tom tat tai lieu.")

    prompt = f"""
Ten tai lieu: {file_name or "Document"}

Hay tom tat tai lieu de tai su dung cho tao quiz, flashcard va mindmap.
Chi dua tren noi dung duoc cung cap, khong bia them thong tin.

Tra ve JSON thuan:
{{
  "summary": "Tom tat ngan gon 8-12 cau, bao phu cac phan chinh cua tai lieu.",
  "key_points": ["Y chinh 1", "Y chinh 2", "Y chinh 3"]
}}

Yeu cau:
- Viet bang tieng Viet.
- key_points gom 10 den 20 y ngan gon.
- Uu tien khai niem, dinh nghia, quy trinh, so sanh, ket luan va thong tin co the ra cau hoi.
- Khong markdown, khong giai thich ngoai JSON.

Noi dung tai lieu:
{sampled_text}
""".strip()

    base_url = str(getattr(settings, "GROQ_BASE_URL", "https://api.groq.com/openai/v1")).rstrip("/")
    model = str(getattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile") or "llama-3.3-70b-versatile").strip()
    timeout = int(getattr(settings, "GROQ_TIMEOUT_SECONDS", 120))
    response = requests.post(
        f"{base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "Ban la cong cu tom tat tai lieu bang tieng Viet. Tra ve JSON thuan, khong markdown.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.15,
            "response_format": {"type": "json_object"},
        },
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Groq summary loi {response.status_code}: {response.text[:500]}")

    raw_text = _extract_groq_text(response.json())
    parsed = _parse_json(raw_text)
    summary = str(parsed.get("summary") or "").strip() if isinstance(parsed, dict) else ""
    raw_points = parsed.get("key_points") if isinstance(parsed, dict) else []
    key_points = [
        str(item).strip()
        for item in raw_points
        if str(item).strip()
    ][:24] if isinstance(raw_points, list) else []
    if not summary:
        raise RuntimeError("Summary thieu noi dung tom tat.")
    if not key_points:
        key_points = _fallback_key_points(summary)
    return {
        "summary": summary,
        "key_points": key_points,
        "raw_response": raw_text,
    }


def build_ai_generation_context(
    *,
    user_id: str,
    read_id: str,
    source_text: str,
    file_name: str,
    purpose: str,
    max_chars: int = None,
) -> str:
    source = (source_text or "").strip()
    if not source:
        raise RuntimeError("Khong co noi dung tai lieu.")

    max_len = int(max_chars or getattr(settings, "AI_CONTEXT_MAX_CHARS", 16000))
    ensure_document_chunks_indexed(user_id=user_id, read_id=read_id, source_text=source)
    summary_row = get_or_create_document_summary(
        user_id=user_id,
        read_id=read_id,
        source_text=source,
        file_name=file_name,
    )

    query = _task_query(purpose=purpose, file_name=file_name)
    top_chunks = retrieve_task_chunks(
        user_id=user_id,
        read_id=read_id,
        query=query,
        match_count=_task_chunk_count(purpose),
        match_threshold=0.0,
    )
    if not top_chunks:
        top_chunks = _representative_chunks(split_text_into_chunks(source), max_count=4)

    parts: List[str] = []
    summary = str(summary_row.get("summary") or "").strip()
    if summary:
        parts.append(f"TOM TAT TAI LIEU:\n{summary}")

    key_points = summary_row.get("key_points") if isinstance(summary_row.get("key_points"), list) else []
    clean_points = [str(item).strip() for item in key_points if str(item).strip()]
    if clean_points:
        parts.append("Y CHINH:\n" + "\n".join(f"- {item}" for item in clean_points[:20]))

    chunk_lines = []
    seen = set()
    for chunk in top_chunks:
        content = str(chunk.get("content") or "").strip()
        if not content:
            continue
        key = re.sub(r"\s+", " ", content.lower())[:160]
        if key in seen:
            continue
        seen.add(key)
        index = chunk.get("chunk_index", len(chunk_lines))
        chunk_lines.append(f"[Doan {index}]\n{content}")
    if chunk_lines:
        parts.append("CAC DOAN LIEN QUAN:\n" + "\n\n".join(chunk_lines))

    context = "\n\n".join(parts).strip()
    return context[:max_len] if context else source[:max_len]


def _sample_document_text(source_text: str) -> str:
    chunks = split_text_into_chunks(source_text)
    if not chunks:
        return ""
    max_count = max(3, int(getattr(settings, "DOCUMENT_SUMMARY_SAMPLE_CHUNKS", 10)))
    selected = _representative_chunks(chunks, max_count=max_count)
    text = "\n\n".join(
        f"[Doan {chunk.get('chunk_index', index)}]\n{chunk.get('content', '')}"
        for index, chunk in enumerate(selected)
        if str(chunk.get("content") or "").strip()
    )
    max_len = int(getattr(settings, "AI_CONTEXT_MAX_CHARS", 16000))
    return text[:max_len]


def _representative_chunks(chunks: List[Dict[str, Any]], *, max_count: int) -> List[Dict[str, Any]]:
    if len(chunks) <= max_count:
        return chunks
    indexes = {0, len(chunks) - 1}
    if max_count > 2:
        step = (len(chunks) - 1) / float(max_count - 1)
        for pos in range(max_count):
            indexes.add(round(pos * step))
    return [chunks[index] for index in sorted(indexes)[:max_count]]


def _task_query(*, purpose: str, file_name: str) -> str:
    base = f"Tai lieu {file_name or 'Document'}."
    if purpose == "quiz":
        return base + " Cac y quan trong de tao cau hoi quiz, dinh nghia, quy trinh, so sanh, ket luan."
    if purpose == "flashcard":
        return base + " Cac khai niem, thuat ngu, dinh nghia va y ngan gon de tao flashcard."
    if purpose == "mindmap":
        return base + " Cac chu de chinh, nhanh chinh, cau truc noi dung de tao so do tu duy."
    return base + " Cac noi dung quan trong cua tai lieu."


def _task_chunk_count(purpose: str) -> int:
    if purpose == "mindmap":
        return 8
    if purpose == "quiz":
        return 8
    if purpose == "flashcard":
        return 6
    return int(getattr(settings, "RAG_MATCH_LIMIT", 5))


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


def _fallback_key_points(summary: str) -> List[str]:
    sentences = re.split(r"(?<=[.!?])\s+", summary)
    return [item.strip() for item in sentences if item.strip()][:12]
