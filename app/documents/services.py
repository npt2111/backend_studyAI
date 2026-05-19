import gc
import io
import json as _json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Dict, List
from uuid import uuid4

from django.conf import settings
from docx import Document
from pypdf import PdfReader
import requests

from config.services import supabase_client

logger = logging.getLogger(__name__)

_EASYOCR_READER = None


CHUNK_SYSTEM_PROMPT = """
Tom tat doan tai lieu thanh JSON thuan.
Chi dung thong tin trong input, khong suy dien, khong them kien thuc ngoai.
Giu ten chuong, muc, so thu tu neu co. Khong viet gi ngoai JSON, khong markdown.
Neu input rong hoac khong doc duoc, cho chapter_summary = "[THIEU_DU_LIEU]".
Schema:
{"chapters":[{"chapter_number":"1","chapter_title":"Ten chuong hoac null","chapter_summary":"2-4 cau","sections":[{"section_number":"1.1","section_title":"Ten muc","section_summary":"1-3 cau"}]}],"key_points":["3-8 y chinh"],"unclear_sections":[]}
Neu khong co cau truc chuong muc, tao 1 chapter voi chapter_number="0", chapter_title=null, sections=[].
""".strip()

FINAL_SYSTEM_PROMPT = """
Hop nhat mang JSON cac chunk thanh 1 JSON tong hop day du, khong bo sot chuong muc.
Chi dung du lieu da cho, khong suy dien, khong viet gi ngoai JSON, khong markdown.
Gop cac chapter/section trung so thu tu, giu ten goc, sap xep tang dan.
Schema:
{"chapters":[{"chapter_number":"1","chapter_title":"Ten chuong hoac null","chapter_summary":"3-5 cau","sections":[{"section_number":"1.1","section_title":"Ten muc","section_summary":"1-3 cau"}]}],"key_points":["8-12 y chinh"],"unclear_sections":[]}
Key points la cau hoan chinh, bam sat nguon.
""".strip()


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
        "summary_json": row.get("summary_json"),
        "key_points": key_points,
        "error": row.get("error_message"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _cleanup_text(raw_text: str) -> str:
    text = unicodedata.normalize("NFKC", raw_text or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00ad", "").replace("\ufeff", "")
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _validate_readable_text(text: str, *, min_words: int = 80) -> None:
    cleaned = _cleanup_text(text)
    if len(cleaned.split()) < min_words:
        raise RuntimeError("Khong doc duoc noi dung file.")
    alpha_count = sum(1 for ch in cleaned if ch.isalpha())
    printable_count = sum(1 for ch in cleaned if ch.isprintable())
    if printable_count == 0 or (alpha_count / max(printable_count, 1)) < 0.20:
        raise RuntimeError("Khong doc duoc noi dung file.")
    if cleaned.count("\ufffd") > 10:
        raise RuntimeError("Khong doc duoc noi dung file.")


def _is_page_text_good(text: str) -> bool:
    min_words = int(getattr(settings, "PDFPLUMBER_TEXT_MIN_WORDS_PER_PAGE", "20"))
    cleaned = _cleanup_text(text)
    if len(cleaned.split()) < min_words:
        return False
    alpha_count = sum(1 for ch in cleaned if ch.isalpha())
    printable_count = sum(1 for ch in cleaned if ch.isprintable())
    return printable_count > 0 and (alpha_count / max(printable_count, 1)) >= 0.20


def _easyocr_reader():
    global _EASYOCR_READER
    if _EASYOCR_READER is not None:
        return _EASYOCR_READER
    try:
        import easyocr
    except ImportError as exc:
        raise RuntimeError("EasyOCR chua duoc cai dat.") from exc

    langs = [
        item.strip()
        for item in str(getattr(settings, "EASYOCR_LANGS", "vi,en") or "vi,en").split(",")
        if item.strip()
    ] or ["vi", "en"]
    _EASYOCR_READER = easyocr.Reader(langs, gpu=bool(getattr(settings, "EASYOCR_GPU", False)))
    return _EASYOCR_READER


def _resize_image_for_ocr(image):
    max_side = int(getattr(settings, "EASYOCR_MAX_IMAGE_SIDE", "1800"))
    if max_side <= 0:
        return image
    width, height = image.size
    longest = max(width, height)
    if longest <= max_side:
        return image
    scale = max_side / float(longest)
    return image.resize((max(1, int(width * scale)), max(1, int(height * scale))))


def _ocr_pdf_page(page) -> str:
    if not bool(getattr(settings, "EASYOCR_ENABLED", True)):
        return ""
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("numpy chua duoc cai dat cho EasyOCR.") from exc

    dpi = int(getattr(settings, "EASYOCR_DPI", "130"))
    page_image = page.to_image(resolution=dpi)
    image = _resize_image_for_ocr(page_image.original.convert("RGB"))
    image_array = np.array(image)

    results = _easyocr_reader().readtext(
        image_array,
        detail=0,
        paragraph=bool(getattr(settings, "EASYOCR_PARAGRAPH", False)),
        batch_size=1,
    )
    del image_array, image, page_image
    gc.collect()
    return _cleanup_text("\n".join(str(item).strip() for item in results if str(item).strip()))


def _extract_pdf_markdown(file_bytes: bytes) -> str:
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("pdfplumber chua duoc cai dat.") from exc

    blocks: List[str] = []
    ocr_pages: List[int] = []
    text_pages = 0
    max_pages = int(getattr(settings, "PDF_OCR_MAX_PAGES", "0"))

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        total_pages = len(pdf.pages)
        for idx, page in enumerate(pdf.pages, start=1):
            if max_pages > 0 and idx > max_pages:
                logger.warning("PDF parsing stopped at configured page limit %s/%s.", max_pages, total_pages)
                break

            page_text = _cleanup_text(page.extract_text() or "")
            source = "pdfplumber"
            if not _is_page_text_good(page_text):
                try:
                    ocr_text = _ocr_pdf_page(page)
                    if ocr_text:
                        page_text = ocr_text
                        source = "easyocr"
                        ocr_pages.append(idx)
                except Exception as exc:
                    logger.warning("EasyOCR failed for PDF page %s: %s", idx, exc)

            if page_text:
                text_pages += 1
                blocks.append(f"## Page {idx} ({source})\n\n{page_text}")

            if hasattr(page, "flush_cache"):
                page.flush_cache()
            gc.collect()

    text = _cleanup_text("\n\n".join(blocks))
    if text:
        logger.info("PDF parsed: text_pages=%s, ocr_pages=%s", text_pages, ocr_pages)
    return text


def _extract_docx_markdown(file_bytes: bytes) -> str:
    doc = Document(io.BytesIO(file_bytes))
    blocks: List[str] = []
    blocks.extend(p.text.strip() for p in doc.paragraphs if p.text and p.text.strip())
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text and cell.text.strip()]
            if cells:
                blocks.append(" | ".join(cells))
    return _cleanup_text("\n\n".join(blocks))


def _validate_document_file(file_name: str, mime_type: str, file_bytes: bytes) -> None:
    lower_name = (file_name or "").lower()
    lower_mime = (mime_type or "").lower()
    if lower_name.endswith(".pdf") or "pdf" in lower_mime:
        try:
            reader = PdfReader(io.BytesIO(file_bytes))
            if len(reader.pages) <= 0:
                raise RuntimeError("PDF khong co trang hop le.")
        except Exception as exc:
            raise RuntimeError("PDF khong hop le hoac bi hong.") from exc
        return
    if lower_name.endswith(".docx") or "wordprocessingml" in lower_mime:
        if not _extract_docx_markdown(file_bytes):
            raise RuntimeError("Khong trich xuat duoc noi dung file DOCX.")
        return
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
            continue
        if current:
            chunks.append(current)
        if len(para) <= max_chars:
            current = para
        else:
            for start in range(0, len(para), max_chars):
                chunks.append(para[start:start + max_chars])
            current = ""
    if current:
        chunks.append(current)
    return chunks


def _safe_parse_json(raw: str) -> Dict:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise RuntimeError("Khong tim thay JSON hop le trong response.")
    candidate = match.group(0).strip()
    try:
        return _json.loads(candidate)
    except _json.JSONDecodeError:
        repaired = re.sub(r",\s*([}\]])", r"\1", candidate)
        return _json.loads(repaired)


def _sanitize_summary_text(summary_text: str) -> str:
    text = (summary_text or "").strip().replace("**", "")
    text = re.sub(r"\[THIEU_DU_LIEU\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\berror\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _sanitize_key_points(points: List[str]) -> List[str]:
    cleaned: List[str] = []
    seen = set()
    for point in points:
        text = _sanitize_summary_text(str(point))
        text = re.sub(r"^\s*[-*#\d\.\)\(]+\s*", "", text).strip()
        if not text or "thieu_du_lieu" in text.lower() or text.lower() == "error":
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned[:12]


def _sanitize_summary_json(data: Dict) -> Dict:
    if not isinstance(data, dict):
        data = {}
    chapters = []
    for chapter in data.get("chapters", []) if isinstance(data.get("chapters"), list) else []:
        if not isinstance(chapter, dict):
            continue
        clean_chapter = {
            "chapter_number": str(chapter.get("chapter_number") or "0"),
            "chapter_title": chapter.get("chapter_title"),
            "chapter_summary": _sanitize_summary_text(chapter.get("chapter_summary", "")),
            "sections": [],
        }
        for section in chapter.get("sections", []) if isinstance(chapter.get("sections"), list) else []:
            if not isinstance(section, dict):
                continue
            section_summary = _sanitize_summary_text(section.get("section_summary", ""))
            if section_summary:
                clean_chapter["sections"].append({
                    "section_number": str(section.get("section_number") or ""),
                    "section_title": section.get("section_title"),
                    "section_summary": section_summary,
                })
        if clean_chapter["chapter_summary"] or clean_chapter["sections"]:
            chapters.append(clean_chapter)
    return {
        "chapters": chapters,
        "key_points": _sanitize_key_points(data.get("key_points", [])),
        "unclear_sections": [str(s).strip() for s in data.get("unclear_sections", []) if str(s).strip()],
    }


def _fallback_summary_json_from_chunks(chunk_dicts: List[Dict]) -> Dict:
    chapters: List[Dict] = []
    key_points: List[str] = []
    unclear_sections: List[str] = []
    for item in chunk_dicts:
        if not isinstance(item, dict):
            continue
        chapters.extend(item.get("chapters", []) if isinstance(item.get("chapters"), list) else [])
        key_points.extend(item.get("key_points", []) if isinstance(item.get("key_points"), list) else [])
        unclear_sections.extend(item.get("unclear_sections", []) if isinstance(item.get("unclear_sections"), list) else [])
        raw_text = str(item.get("raw_text") or "").strip()
        if raw_text:
            chapters.append({
                "chapter_number": "0",
                "chapter_title": None,
                "chapter_summary": raw_text[:1200],
                "sections": [],
            })
    return _sanitize_summary_json({
        "chapters": chapters,
        "key_points": key_points,
        "unclear_sections": unclear_sections,
    })


def _summary_json_to_text(data: Dict) -> str:
    lines: List[str] = []
    for chapter in data.get("chapters", []):
        num = chapter.get("chapter_number", "")
        title = chapter.get("chapter_title") or ""
        header = f"Chuong {num}" if num and str(num) != "0" else ""
        if title:
            header = f"{header}: {title}" if header else title
        if header:
            lines.append(f"## {header}")
        if chapter.get("chapter_summary"):
            lines.append(chapter["chapter_summary"])
        for section in chapter.get("sections", []):
            sec_num = section.get("section_number", "")
            sec_title = section.get("section_title") or ""
            sec_header = f"Muc {sec_num}" if sec_num else ""
            if sec_title:
                sec_header = f"{sec_header}: {sec_title}" if sec_header else sec_title
            if sec_header:
                lines.append(f"### {sec_header}")
            if section.get("section_summary"):
                lines.append(section["section_summary"])
    if data.get("key_points"):
        lines.append("\n## Cac y chinh")
        lines.extend(f"- {point}" for point in data["key_points"])
    return _sanitize_summary_text("\n\n".join(lines))


def _derive_key_points_from_text(text: str) -> List[str]:
    candidates = []
    for line in _sanitize_summary_text(text).splitlines():
        cleaned = re.sub(r"^\s*[-*#\d\.\)\(]+\s*", "", line).strip()
        if len(cleaned.split()) >= 6:
            candidates.append(cleaned)
    if not candidates:
        candidates = [
            part.strip()
            for part in re.split(r"(?<=[.!?])\s+", _sanitize_summary_text(text))
            if len(part.strip().split()) >= 6
        ]
    return _sanitize_key_points(candidates[:12])


def _chat_ollama(system_prompt: str, user_prompt: str, max_tokens: int) -> str:
    base_url = str(getattr(settings, "OLLAMA_BASE_URL", "http://localhost:11434") or "http://localhost:11434").rstrip("/")
    model = str(getattr(settings, "OLLAMA_MODEL", "llama3.2:1b") or "llama3.2:1b").strip()
    timeout = int(getattr(settings, "OLLAMA_TIMEOUT_SECONDS", "180"))
    response = requests.post(
        f"{base_url}/api/chat",
        json={
            "model": model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "options": {"temperature": 0.2, "num_predict": max_tokens},
        },
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Ollama loi {response.status_code}: {response.text[:500]}")
    data = response.json()
    message = data.get("message") if isinstance(data, dict) else None
    content = str((message or {}).get("content") or "").strip()
    if not content:
        content = str(data.get("response") or "").strip() if isinstance(data, dict) else ""
    if not content:
        raise RuntimeError("Ollama tra ve noi dung rong.")
    return content


def _summarize_chunks(text: str, job_id: str) -> Dict:
    max_chunk_chars = int(getattr(settings, "SUMMARY_CHUNK_CHARS", "2500"))
    chunk_max_tokens = int(getattr(settings, "SUMMARY_CHUNK_MAX_TOKENS", "300"))
    final_max_tokens = int(getattr(settings, "SUMMARY_FINAL_MAX_TOKENS", "700"))
    chunks = _chunk_text(text, max_chars=max_chunk_chars)
    if not chunks:
        raise RuntimeError("Khong tach duoc chunk.")

    chunk_dicts: List[Dict] = []
    total = len(chunks)
    for idx, chunk in enumerate(chunks, start=1):
        raw = _chat_ollama(
            system_prompt=CHUNK_SYSTEM_PROMPT,
            user_prompt=f"[PHAN {idx}/{total}]\n\n{chunk}",
            max_tokens=chunk_max_tokens,
        )
        try:
            chunk_dicts.append(_sanitize_summary_json(_safe_parse_json(raw)))
        except Exception:
            chunk_dicts.append({"raw_text": raw[:3000]})
        progress = min(85, 25 + int((idx / total) * 55))
        if idx == total or idx % 2 == 0:
            supabase_client.update_summary_job(job_id, {"progress": progress})

    final_raw = _chat_ollama(
        system_prompt=FINAL_SYSTEM_PROMPT,
        user_prompt=_json.dumps(chunk_dicts, ensure_ascii=False),
        max_tokens=final_max_tokens,
    )
    try:
        summary_data = _sanitize_summary_json(_safe_parse_json(final_raw))
    except Exception:
        summary_data = _fallback_summary_json_from_chunks(chunk_dicts)

    summary_text = _summary_json_to_text(summary_data)
    if not summary_text:
        summary_text = _sanitize_summary_text(final_raw)
    key_points = _sanitize_key_points(summary_data.get("key_points", []))
    if not key_points:
        key_points = _derive_key_points_from_text(summary_text)
    if not key_points and summary_text:
        key_points = ["Tom tat da duoc tao, nhung model khong tra ve danh sach y chinh rieng."]
    if not summary_text:
        raise RuntimeError("Khong tao duoc tom tat tu noi dung file.")

    summary_data["key_points"] = key_points
    summary_data = _sanitize_summary_json(summary_data)
    summary_text = _summary_json_to_text(summary_data) or summary_text
    return {
        "summary_data": summary_data,
        "summary_text": summary_text,
        "key_points": key_points,
    }


def _build_summary_json_payload(
    *,
    job_id: str,
    file_name: str,
    summary_text: str,
    summary_json: Dict,
    key_points: List[str],
    source_word_count: int,
) -> Dict:
    return {
        "job_id": job_id,
        "file_name": file_name,
        "summary_text": summary_text,
        "summary_json": summary_json,
        "key_points": key_points,
        "source_word_count": source_word_count,
        "generated_at": now_iso(),
    }


def _upload_summary_json(*, bucket: str, user_id: str, job_id: str, payload: Dict) -> str:
    object_path = f"{user_id}/summaries/{job_id}_{uuid4().hex}.json"
    file_bytes = _json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    res, status_code = supabase_client.upload_storage_file(
        bucket=bucket,
        object_path=object_path,
        file_bytes=file_bytes,
        content_type="application/json; charset=utf-8",
    )
    if status_code >= 400:
        raise RuntimeError(f"Khong luu duoc file JSON summary len Supabase Storage: {res}")
    return object_path


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
        user_id = str(claimed_row.get("id_user", ""))
        mime_type = str(claimed_row.get("mime_type", ""))
        lower_name = file_name.lower()
        lower_mime = mime_type.lower()
        is_pdf = lower_name.endswith(".pdf") or "pdf" in lower_mime
        is_docx = lower_name.endswith(".docx") or "wordprocessingml" in lower_mime

        supabase_client.update_summary_job(job_id, {"progress": 20})
        if is_pdf:
            text = _extract_pdf_markdown(bytes(blob))
        elif is_docx:
            text = _extract_docx_markdown(bytes(blob))
        else:
            raise RuntimeError("Chi ho tro PDF va DOCX.")

        _validate_readable_text(text)
        supabase_client.update_summary_job(job_id, {"progress": 30})

        result = _summarize_chunks(text=text, job_id=job_id)
        summary_data = result["summary_data"]
        final_summary_text = result["summary_text"]
        key_points = result["key_points"]

        payload = _build_summary_json_payload(
            job_id=job_id,
            file_name=file_name,
            summary_text=final_summary_text,
            summary_json=summary_data,
            key_points=key_points,
            source_word_count=len(text.split()),
        )
        _upload_summary_json(bucket=bucket, user_id=user_id, job_id=job_id, payload=payload)

        saved_row, saved_status = supabase_client.update_summary_job(
            job_id,
            {
                "status": "done",
                "progress": 100,
                "summary_text": final_summary_text,
                "summary_json": summary_data,
                "key_points": key_points,
                "source_word_count": len(text.split()),
                "finished_at": now_iso(),
                "error_message": None,
            },
        )
        if saved_status >= 400:
            raise RuntimeError(f"Khong luu duoc tom tat vao Supabase DB: {saved_row}")

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
        raise
