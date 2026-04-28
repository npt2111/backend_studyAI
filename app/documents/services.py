import io
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from django.conf import settings
from docx import Document
from openai import OpenAI
from pypdf import PdfReader

from config.services import supabase_client


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_job(row: Dict) -> Dict:
    if not row:
        return {}

    raw_points = row.get("key_points")
    key_points = raw_points if isinstance(raw_points, list) else []

    return {
        "id": row.get("id_job"),
        "id_job": row.get("id_job"),
        "user_id": row.get("id_user"),
        "file_name": row.get("file_name"),
        "status": row.get("status"),
        "progress": int(row.get("progress") or 0),
        "summary": row.get("summary_text"),
        "summary_text": row.get("summary_text"),
        "key_points": key_points,
        "error": row.get("error_message"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _cleanup_text(raw_text: str) -> str:
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _extract_pdf_text(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    chunks = []
    for page in reader.pages:
        chunks.append((page.extract_text() or "").strip())
    return "\n\n".join([c for c in chunks if c])


def _extract_docx_text(file_bytes: bytes) -> str:
    doc = Document(io.BytesIO(file_bytes))
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
    return "\n\n".join(paragraphs)


def _extract_text(file_name: str, mime_type: str, file_bytes: bytes) -> str:
    lower_name = (file_name or "").lower()
    lower_mime = (mime_type or "").lower()

    if lower_name.endswith(".pdf") or "pdf" in lower_mime:
        return _extract_pdf_text(file_bytes)

    if lower_name.endswith(".docx") or "wordprocessingml" in lower_mime:
        return _extract_docx_text(file_bytes)

    raise RuntimeError("Chi ho tro PDF va DOCX.")


def _chunk_text(text: str, max_chars: int) -> List[str]:
    if len(text) <= max_chars:
        return [text]

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: List[str] = []
    current = ""
    for para in paragraphs:
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            if len(para) <= max_chars:
                current = para
            else:
                start = 0
                while start < len(para):
                    end = min(start + max_chars, len(para))
                    chunks.append(para[start:end])
                    start = end
                current = ""
    if current:
        chunks.append(current)
    return chunks


def _openai_client() -> OpenAI:
    api_key = getattr(settings, "OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY chua duoc cau hinh.")
    return OpenAI(api_key=api_key)


def _chat(client: OpenAI, system_prompt: str, user_prompt: str, max_tokens: int) -> str:
    model = getattr(settings, "OPENAI_MODEL", "gpt-4o-mini")
    response = client.chat.completions.create(
        model=model,
        temperature=0.2,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    content = response.choices[0].message.content if response.choices else ""
    if isinstance(content, list):
        texts = []
        for p in content:
            t = getattr(p, "text", None)
            if t:
                texts.append(t)
        content = "\n".join(texts)
    content = str(content or "").strip()
    if not content:
        raise RuntimeError("OpenAI tra ve noi dung rong.")
    return content


def _parse_key_points(raw: str) -> List[str]:
    lines = []
    for line in raw.splitlines():
        cleaned = re.sub(r"^[-•\d\.\)\(]+\s*", "", line.strip())
        if cleaned:
            lines.append(cleaned)
    return lines[:8]


def process_summary_job(job_id: str) -> None:
    claimed_row, claimed_status = supabase_client.claim_summary_job(job_id)
    if claimed_status >= 400:
        raise RuntimeError("Khong claim duoc job de xu ly.")
    if not claimed_row:
        return

    try:
        bucket = getattr(settings, "SUPABASE_STORAGE_BUCKET", "study-documents")
        blob, blob_status = supabase_client.download_storage_file(
            bucket=bucket,
            object_path=str(claimed_row.get("storage_path", "")),
        )
        if blob_status >= 400 or not isinstance(blob, (bytes, bytearray)):
            raise RuntimeError("Khong tai duoc file tu Supabase Storage.")

        file_name = str(claimed_row.get("file_name", ""))
        mime_type = str(claimed_row.get("mime_type", ""))
        text = _extract_text(file_name, mime_type, bytes(blob))
        text = _cleanup_text(text)
        if not text:
            raise RuntimeError("Khong trich xuat duoc noi dung file.")

        max_source_chars = int(getattr(settings, "SUMMARY_MAX_SOURCE_CHARS", 300000))
        if len(text) > max_source_chars:
            text = text[:max_source_chars]

        supabase_client.update_summary_job(job_id, {"progress": 20})

        max_chunk_chars = int(getattr(settings, "SUMMARY_CHUNK_CHARS", 6000))
        chunks = _chunk_text(text, max_chars=max_chunk_chars)
        if not chunks:
            raise RuntimeError("Khong tach duoc chunk.")

        client = _openai_client()
        part_summaries: List[str] = []

        total = len(chunks)
        for idx, chunk in enumerate(chunks, start=1):
            part = _chat(
                client=client,
                system_prompt=(
                    "Ban la tro ly hoc tap. Tom tat ngan gon, ro rang, "
                    "giu y chinh de sinh vien on tap."
                ),
                user_prompt=f"Tai lieu phan {idx}/{total}:\n\n{chunk}",
                max_tokens=900,
            )
            part_summaries.append(part)
            progress = min(85, 20 + int((idx / total) * 55))
            supabase_client.update_summary_job(job_id, {"progress": progress})

        merged = "\n\n".join(part_summaries)

        final_summary = _chat(
            client=client,
            system_prompt="Tong hop thanh ban tom tat cuoi cung de hoc nhanh, de doc.",
            user_prompt=merged,
            max_tokens=1200,
        )

        raw_points = _chat(
            client=client,
            system_prompt="Trich 5-8 y chinh, moi dong mot y, bat dau bang '- '.",
            user_prompt=final_summary,
            max_tokens=500,
        )
        key_points = _parse_key_points(raw_points)

        supabase_client.update_summary_job(
            job_id,
            {
                "status": "done",
                "progress": 100,
                "summary_text": final_summary,
                "key_points": key_points,
                "source_word_count": len(text.split()),
                "finished_at": now_iso(),
                "error_message": None,
            },
        )

    except Exception as exc:
        supabase_client.update_summary_job(
            job_id,
            {
                "status": "failed",
                "progress": 100,
                "finished_at": now_iso(),
                "error_message": str(exc)[:1000] if str(exc) else "Khong ro loi.",
            },
        )
