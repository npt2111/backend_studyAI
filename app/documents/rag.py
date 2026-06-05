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
