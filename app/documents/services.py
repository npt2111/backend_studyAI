import gc
import html
import io
import json as _json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Dict, List
from uuid import uuid4

from django.conf import settings
from pypdf import PdfReader
import requests

from config.services import supabase_client

logger = logging.getLogger(__name__)

_EASYOCR_READER = None


CHUNK_SYSTEM_PROMPT = """
Ban la cong cu tom tat hoc thuat tieng Viet. Tra ve JSON thuan.
Nhiem vu: tom tat NHUNG Y CHINH cua doan tai lieu, dung noi dung nguon, khong bia, khong suy dien, khong lang man.
Bo qua nhieu: trang bia, loi cam on, muc luc, link, email, so trang, footer/header lap lai, dong loi OCR.
Van ban lich su/chinh tri/hoc thuat la noi dung trung lap de tom tat; khong tu choi.
Giu ten chuong/muc/so thu tu neu that su co trong bai. Khong viet gi ngoai JSON, khong markdown.
Neu input rong hoac khong doc duoc, cho chapter_summary="[THIEU_DU_LIEU]".
Schema:
{"chapters":[{"chapter_number":"1","chapter_title":"Ten chuong hoac null","chapter_summary":"2-4 cau ngan, dung y nguon","sections":[{"section_number":"1.1","section_title":"Ten muc","section_summary":"1-2 cau ngan, dung y nguon"}]}],"key_points":["tu khoa 2-5 tu"],"unclear_sections":[]}
key_points la tu khoa/mau chot, moi muc 2-5 tu, khong phai cau dai.
Neu khong co chuong/muc ro rang, tao 1 chapter voi chapter_number="0", chapter_title=null, sections=[].
""".strip()

FINAL_SYSTEM_PROMPT = """
Hop nhat mang JSON chunk thanh 1 JSON tong hop tieng Viet.
Chi dung du lieu da cho, khong bia, khong suy dien, khong lang man, khong tu choi.
Bo cac noi dung nhieu: trang bia, link, email, so trang, footer/header, dong loi OCR.
Gop chapter/section trung so thu tu, giu ten goc, sap xep tang dan. Khong viet gi ngoai JSON.
Schema:
{"chapters":[{"chapter_number":"1","chapter_title":"Ten chuong hoac null","chapter_summary":"3-5 cau ngan, dung y nguon","sections":[{"section_number":"1.1","section_title":"Ten muc","section_summary":"1-2 cau ngan, dung y nguon"}]}],"key_points":["tu khoa 2-5 tu"],"unclear_sections":[]}
key_points gom 8-15 tu khoa/mau chot, moi muc 2-5 tu, khong phai cau dai.
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


def _fold_text(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value or "")
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = folded.lower()
    folded = re.sub(r"[^a-z0-9\s]", " ", folded)
    return re.sub(r"\s+", " ", folded).strip()


def _noise_line_key(line: str) -> str:
    return _fold_text(line)


def _is_noise_line(line: str, repeated_keys: set = None) -> bool:
    text = (line or "").strip()
    if not text:
        return True
    folded = _fold_text(text)
    repeated_keys = repeated_keys or set()

    if folded in repeated_keys:
        return True
    if re.search(r"https?://|www\.|doi\.org|@\w+", text, flags=re.IGNORECASE):
        return True
    if re.fullmatch(r"[-–—_ .]*\d{1,4}[-–—_ .]*", text):
        return True
    if re.fullmatch(r"(page|trang)\s*\d{1,4}(\s*/\s*\d{1,4})?", folded):
        return True
    if len(text) <= 2:
        return True
    if len(text) <= 80 and sum(ch.isalpha() for ch in text) < 3:
        return True
    if re.fullmatch(r"[\W\d_]+", text):
        return True
    return False


def _filter_noise_lines(text: str, repeated_keys: set = None) -> str:
    lines: List[str] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if _is_noise_line(line, repeated_keys=repeated_keys):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _is_cover_or_meta_page(text: str, page_index: int) -> bool:
    if page_index > 2:
        return False
    folded = _fold_text(text)
    cover_markers = [
        "bo giao duc",
        "truong dai hoc",
        "hoc vien",
        "khoa ",
        "luan van",
        "do an",
        "khoa luan",
        "de tai",
        "giang vien huong dan",
        "sinh vien thuc hien",
        "ma sinh vien",
        "mssv",
        "lop ",
        "ha noi",
        "tp ho chi minh",
    ]
    marker_count = sum(1 for marker in cover_markers if marker in folded)
    sentence_count = len(re.findall(r"[.!?]", text or ""))
    word_count = len((text or "").split())
    return marker_count >= 3 and (sentence_count <= 4 or word_count <= 180)


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

    page_blocks: List[tuple] = []
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

            page_text = _filter_noise_lines(page_text)
            if _is_cover_or_meta_page(page_text, idx):
                logger.info("Skipped likely cover/meta PDF page %s.", idx)
                page_text = ""

            if page_text:
                text_pages += 1
                page_blocks.append((idx, source, page_text))

            if hasattr(page, "flush_cache"):
                page.flush_cache()
            gc.collect()

    line_counts: Dict[str, int] = {}
    for _, _, page_text in page_blocks:
        seen_in_page = set()
        for line in page_text.splitlines():
            key = _noise_line_key(line)
            if key and len(key) <= 80:
                seen_in_page.add(key)
        for key in seen_in_page:
            line_counts[key] = line_counts.get(key, 0) + 1

    repeated_keys = {
        key
        for key, count in line_counts.items()
        if count >= 3 and len(key.split()) <= 10
    }

    blocks: List[str] = []
    for idx, source, page_text in page_blocks:
        filtered_text = _filter_noise_lines(page_text, repeated_keys=repeated_keys)
        if filtered_text:
            blocks.append(f"## Page {idx} ({source})\n\n{filtered_text}")

    text = _cleanup_text("\n\n".join(blocks))
    if text:
        logger.info("PDF parsed: text_pages=%s, ocr_pages=%s", text_pages, ocr_pages)
    return text


def _html_to_plain_text(markup: str) -> str:
    text = markup or ""
    text = re.sub(r"(?i)</h[1-6]>", "\n\n", text)
    text = re.sub(r"(?i)<h[1-6][^>]*>", "\n\n", text)
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = re.sub(r"(?i)<p[^>]*>", "", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</li>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    text = re.sub(r"(?i)</tr>", "\n", text)
    text = re.sub(r"(?i)<tr[^>]*>", "", text)
    text = re.sub(r"(?i)</t[dh]>", " | ", text)
    text = re.sub(r"(?i)<t[dh][^>]*>", "", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]*\|[ \t]*\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return _cleanup_text(_filter_noise_lines(text))


def _extract_docx_markdown(file_bytes: bytes) -> str:
    try:
        import mammoth
    except ImportError as exc:
        raise RuntimeError("mammoth chua duoc cai dat.") from exc

    with io.BytesIO(file_bytes) as stream:
        result = mammoth.convert_to_html(stream)
    for message in getattr(result, "messages", []) or []:
        logger.info("Mammoth DOCX message: %s", message)

    text = _html_to_plain_text(str(getattr(result, "value", "") or ""))
    if text:
        return text

    with io.BytesIO(file_bytes) as stream:
        raw_result = mammoth.extract_raw_text(stream)
    return _cleanup_text(_filter_noise_lines(str(getattr(raw_result, "value", "") or "")))


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
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.replace("\u00ad", "").replace("\ufeff", "")
    text = re.sub(r"\[THIEU_DU_LIEU\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\berror\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"https?://\S+|www\.\S+|\S+@\S+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _is_refusal_text(text: str) -> bool:
    value = _sanitize_summary_text(text).lower()
    if not value:
        return False
    folded = unicodedata.normalize("NFKD", value)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    refusal_patterns = [
        "i can't",
        "i cannot",
        "can't provide",
        "cannot provide",
        "can't help",
        "cannot help",
        "can't comply",
        "khong the giup",
        "toi khong the",
        "khong the ho tro",
        "toi khong the ho tro",
        "khong the thuc hien",
        "khong the cung cap",
        "khong the tao",
        "khong phu hop",
        "unsourced article",
    ]
    return any(pattern in value or pattern in folded for pattern in refusal_patterns)


def _sanitize_key_points(points: List[str]) -> List[str]:
    cleaned: List[str] = []
    seen = set()
    for point in points:
        text = _sanitize_summary_text(str(point))
        text = re.sub(r"^\s*[-*#\d\.\)\(]+\s*", "", text).strip()
        text = re.sub(r"https?://\S+|www\.\S+|\S+@\S+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"[^\w\s/-]+", " ", text, flags=re.UNICODE)
        text = re.sub(r"\s+", " ", text).strip(" -_/")
        if not text or "thieu_du_lieu" in text.lower() or text.lower() == "error":
            continue
        if _is_refusal_text(text):
            continue
        words = text.split()
        if len(words) < 2:
            continue
        if len(words) > 5:
            text = " ".join(words[:5]).strip()
            words = text.split()
        if len(words) < 2 or len(words) > 5:
            continue
        if any(len(word) > 35 for word in words):
            continue
        key = _fold_text(text)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned[:15]


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
        if _is_refusal_text(clean_chapter["chapter_summary"]):
            clean_chapter["chapter_summary"] = ""
        for section in chapter.get("sections", []) if isinstance(chapter.get("sections"), list) else []:
            if not isinstance(section, dict):
                continue
            section_summary = _sanitize_summary_text(section.get("section_summary", ""))
            if _is_refusal_text(section_summary):
                continue
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
        if raw_text and not _is_refusal_text(raw_text):
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
            lines.append(header)
        if chapter.get("chapter_summary"):
            lines.append(chapter["chapter_summary"])
        for section in chapter.get("sections", []):
            sec_num = section.get("section_number", "")
            sec_title = section.get("section_title") or ""
            sec_header = f"Muc {sec_num}" if sec_num else ""
            if sec_title:
                sec_header = f"{sec_header}: {sec_title}" if sec_header else sec_title
            if sec_header:
                lines.append(sec_header)
            if section.get("section_summary"):
                lines.append(section["section_summary"])
    return _sanitize_summary_text("\n\n".join(lines))


def _validate_final_summary_payload(summary_data: Dict, summary_text: str, key_points: List[str]) -> None:
    if not isinstance(summary_data, dict):
        raise RuntimeError("Tom tat khong dung JSON object.")
    chapters = summary_data.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        raise RuntimeError("Tom tat thieu chapters.")
    if not _sanitize_summary_text(summary_text):
        raise RuntimeError("Tom tat thieu summary_text.")
    if not isinstance(key_points, list) or not key_points:
        raise RuntimeError("Tom tat thieu key_points.")
    for point in key_points:
        words = str(point).split()
        if len(words) < 2 or len(words) > 5:
            raise RuntimeError("key_points phai la tu khoa 2-5 tu.")
        if _is_refusal_text(str(point)) or _is_noise_line(str(point)):
            raise RuntimeError("key_points chua noi dung nhieu.")


def _derive_key_points_from_text(text: str) -> List[str]:
    cleaned = _filter_noise_lines(_sanitize_summary_text(text))
    stop_words = {
        "cua", "va", "la", "cac", "nhung", "mot", "trong", "cho", "voi", "duoc",
        "nay", "do", "khi", "tu", "den", "the", "ve", "co", "khong", "nguoi",
        "noi", "dung", "trang", "page", "chapter", "chuong", "muc",
    }
    candidates: List[str] = []

    for line in cleaned.splitlines():
        line = re.sub(r"^#+\s*", "", line).strip()
        if 2 <= len(line.split()) <= 5 and not _is_noise_line(line):
            candidates.append(line)

    folded = _fold_text(cleaned)
    words = [word for word in folded.split() if len(word) >= 3 and word not in stop_words and not word.isdigit()]
    phrase_counts: Dict[str, int] = {}
    for size in (2, 3, 4):
        for idx in range(0, max(0, len(words) - size + 1)):
            phrase = " ".join(words[idx:idx + size])
            if any(token in stop_words for token in phrase.split()[:1]):
                continue
            phrase_counts[phrase] = phrase_counts.get(phrase, 0) + 1

    ranked_phrases = sorted(
        phrase_counts.items(),
        key=lambda item: (item[1], len(item[0].split())),
        reverse=True,
    )
    candidates.extend(phrase for phrase, count in ranked_phrases if count >= 2)

    if len(candidates) < 8:
        for sentence in re.split(r"(?<=[.!?])\s+", cleaned):
            words_in_sentence = sentence.strip().split()
            if len(words_in_sentence) >= 4:
                candidates.append(" ".join(words_in_sentence[:5]))

    return _sanitize_key_points(candidates)


def _split_sentences(text: str) -> List[str]:
    cleaned = _filter_noise_lines(_cleanup_text(text))
    parts: List[str] = []
    for block in cleaned.split("\n\n"):
        block = re.sub(r"^## Page \d+ \([^)]+\)\s*", "", block.strip())
        if not block:
            continue
        if re.match(r"^(chuong|muc|phan|bai)\s+[\divx0-9]", _fold_text(block)):
            parts.append(block)
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", block):
            sentence = sentence.strip()
            if 8 <= len(sentence.split()) <= 80 and not _is_noise_line(sentence):
                parts.append(sentence)
    return parts


def _sentence_score(sentence: str) -> int:
    folded = _fold_text(sentence)
    words = folded.split()
    score = 0
    important_terms = [
        "khai niem", "dinh nghia", "vai tro", "dac diem", "nguyen nhan",
        "ket qua", "ket luan", "muc tieu", "phuong phap", "noi dung",
        "y nghia", "anh huong", "giai phap", "han che", "thuc trang",
        "so lieu", "phan tich", "danh gia", "nghien cuu", "qua trinh",
    ]
    score += sum(4 for term in important_terms if term in folded)
    if re.search(r"\d+([,.]\d+)?\s*(%|nam|nguoi|lan|trieu|ty|usd|vnd)?", folded):
        score += 3
    if re.match(r"^(chuong|muc|phan|bai)\s+[\divx0-9]", folded):
        score += 6
    score += min(len(words), 35) // 8
    if len(words) < 10:
        score -= 2
    if any(noise in folded for noise in ["http", "www", "email", "copyright", "all rights"]):
        score -= 10
    return score


def _condense_text_for_llm(text: str) -> str:
    max_chars = int(getattr(settings, "SUMMARY_LLM_INPUT_CHARS", "14000"))
    sentences = _split_sentences(text)
    if not sentences:
        return _cleanup_text(text)[:max_chars]

    indexed = list(enumerate(sentences))
    scored = [
        (idx, sentence, _sentence_score(sentence))
        for idx, sentence in indexed
    ]

    keep_count = min(
        len(scored),
        max(24, int(getattr(settings, "SUMMARY_PRESELECT_SENTENCES", "80"))),
    )
    selected_indexes = {
        idx
        for idx, _, score in sorted(scored, key=lambda item: item[2], reverse=True)[:keep_count]
        if score > -2
    }

    condensed_parts: List[str] = []
    current_len = 0
    for idx, sentence in indexed:
        if idx not in selected_indexes:
            continue
        addition = sentence.strip()
        if not addition:
            continue
        if current_len + len(addition) + 2 > max_chars:
            break
        condensed_parts.append(addition)
        current_len += len(addition) + 2

    condensed = _cleanup_text("\n\n".join(condensed_parts))
    return condensed if len(condensed.split()) >= 80 else _cleanup_text(text)[:max_chars]


def _chat_ollama(system_prompt: str, user_prompt: str, max_tokens: int) -> str:
    base_url = str(getattr(settings, "OLLAMA_BASE_URL", "http://localhost:11434") or "http://localhost:11434").rstrip("/")
    model = str(getattr(settings, "OLLAMA_MODEL", "llama3.2:1b") or "llama3.2:1b").strip()
    timeout = int(getattr(settings, "OLLAMA_TIMEOUT_SECONDS", "180"))
    keep_alive = str(getattr(settings, "OLLAMA_KEEP_ALIVE", "30m") or "30m")
    num_ctx = int(getattr(settings, "OLLAMA_NUM_CTX", "4096"))
    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "keep_alive": keep_alive,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "options": {
            "temperature": 0.1,
            "top_p": 0.8,
            "repeat_penalty": 1.1,
            "num_ctx": num_ctx,
            "num_predict": max_tokens,
        },
    }
    response = requests.post(f"{base_url}/api/chat", json=payload, timeout=timeout)
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
    chunk_max_tokens = int(getattr(settings, "SUMMARY_CHUNK_MAX_TOKENS", "450"))
    final_max_tokens = int(getattr(settings, "SUMMARY_FINAL_MAX_TOKENS", "1000"))
    llm_text = _condense_text_for_llm(text)
    chunks = _chunk_text(llm_text, max_chars=max_chunk_chars)
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
            chunk_data = _sanitize_summary_json(_safe_parse_json(raw))
            if chunk_data.get("chapters") or chunk_data.get("key_points"):
                chunk_dicts.append(chunk_data)
        except Exception:
            logger.warning("Ollama chunk summary JSON parse failed for chunk %s/%s: %s", idx, total, raw[:300])
        progress = min(85, 25 + int((idx / total) * 55))
        if idx == total or idx % 2 == 0:
            supabase_client.update_summary_job(job_id, {"progress": progress})

    if not chunk_dicts:
        raise RuntimeError("Model khong tao duoc tom tat JSON hop le.")

    if len(chunk_dicts) == 1:
        final_raw = ""
        summary_data = chunk_dicts[0]
    else:
        final_raw = _chat_ollama(
            system_prompt=FINAL_SYSTEM_PROMPT,
            user_prompt=_json.dumps(chunk_dicts, ensure_ascii=False),
            max_tokens=final_max_tokens,
        )
        try:
            summary_data = _sanitize_summary_json(_safe_parse_json(final_raw))
        except Exception:
            summary_data = _fallback_summary_json_from_chunks(chunk_dicts)
        if not summary_data.get("chapters") and not summary_data.get("key_points"):
            summary_data = _fallback_summary_json_from_chunks(chunk_dicts)

    summary_text = _summary_json_to_text(summary_data)
    if not summary_text and final_raw and not _is_refusal_text(final_raw):
        summary_text = _sanitize_summary_text(final_raw)
    if not summary_text or _is_refusal_text(summary_text):
        raise RuntimeError("Model tra ve noi dung tu choi hoac khong phai tom tat.")
    key_points = _sanitize_key_points(summary_data.get("key_points", []))
    if not key_points:
        key_points = _derive_key_points_from_text(summary_text)
    if not key_points and summary_text:
        key_points = _sanitize_key_points(["tom tat tai lieu"])
    if not summary_text:
        raise RuntimeError("Khong tao duoc tom tat tu noi dung file.")

    summary_data["key_points"] = key_points
    summary_data = _sanitize_summary_json(summary_data)
    key_points = _sanitize_key_points(summary_data.get("key_points", []))
    summary_data["key_points"] = key_points
    summary_text = _summary_json_to_text(summary_data) or summary_text
    _validate_final_summary_payload(summary_data, summary_text, key_points)
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
