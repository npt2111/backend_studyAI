import gc
import html
import io
import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Dict, List

from django.conf import settings
from pypdf import PdfReader

logger = logging.getLogger(__name__)

_EASYOCR_READER = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()



def normalize_read_result(row: Dict) -> Dict:
    if not row:
        return {}
    extracted_text = row.get("extracted_text") or ""
    return {
        "id": row.get("id_read"),
        "id_read": row.get("id_read"),
        "user_id": row.get("id_user"),
        "file_name": row.get("file_name"),
        "storage_path": row.get("storage_path"),
        "mime_type": row.get("mime_type"),
        "status": row.get("status"),
        "extracted_text": extracted_text,
        "text_preview": extracted_text[:500],
        "source_word_count": int(row.get("source_word_count") or 0),
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
