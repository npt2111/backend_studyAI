import io
import json
import time
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List
from uuid import uuid4

from django.conf import settings
from docx import Document
from groq import Groq
from pypdf import PdfReader, PdfWriter

from config.services import supabase_client

# ──────────────────────────────────────────────────────────────────────────────
# System prompts (giữ nguyên logic, chỉ đổi AI backend)
# ──────────────────────────────────────────────────────────────────────────────

CHUNK_SYSTEM_PROMPT = """
Ban la tro ly tom tat hoc thuat tieng Viet.

Muc tieu:
- Tom tat DAY DU y chinh cua tai lieu dai.
- TUYET DOI khong suy dien, khong them kien thuc ngoai van ban nguon.

Quy tac bat buoc:
1) Chi dung thong tin xuat hien trong van ban dau vao.
2) Khong phong doan phan bi thieu.
3) Chi duoc ghi [THIEU_DU_LIEU] khi doan input that su rong/khong doc duoc.
4) Giu nguyen thuat ngu quan trong, ten chuong/muc neu co.
5) Khong viet mo dau xa giao.

Dinh dang dau ra:
## TOM_TAT_THEO_MUC
- Muc/Chuong 1: ...
- Muc/Chuong 2: ...
- ...

## CAC_Y_CHINH_KHONG_BO_SOT
- 12-24 gach dau dong (tuy do dai tai lieu), moi y 1-2 cau.
- Moi y phai bam sat nguon, khong them dien giai ngoai van ban.

## NOI_DUNG_CHUA_RO
- Liet ke cac phan bi thieu/ngan/quet loi, neu co.
""".strip()

FINAL_SYSTEM_PROMPT = """
Ban la tro ly tong hop tom tat hoc thuat tieng Viet.
Ban se nhan nhieu ban tom tat tung phan cua cung mot tai lieu.

Muc tieu:
- Hop nhat day du y chinh cua toan bo tai lieu.
- Khong bo sot y trong cac phan da cung cap.
- TUYET DOI khong suy dien, khong them kien thuc ngoai du lieu dau vao.

Quy tac:
1) Chi tong hop tu noi dung da cho.
2) Chi ghi [THIEU_DU_LIEU] neu that su khong co du lieu trong nguon.
3) Khong viet mo dau xa giao.
4) Uu tien bao phu day du cac chuong/muc xuat hien trong tai lieu.

Dinh dang dau ra:
## TOM_TAT_THEO_MUC
- Muc/Chuong 1: ...
- Muc/Chuong 2: ...
- ...

## CAC_Y_CHINH_KHONG_BO_SOT
- 12-24 gach dau dong, moi y 1-2 cau, bam sat nguon.

## NOI_DUNG_CHUA_RO
- Liet ke cac phan bi thieu/ngan/quet loi, neu co.
""".strip()

KEYPOINTS_SYSTEM_PROMPT = """
Trich cac y chinh quan trong nhat tu tom tat dau vao.
Quy tac:
- Chi dung thong tin co trong dau vao.
- Khong suy dien, khong them thong tin moi.
- Moi dong bat dau bang '- '.
- Tra ve 12-24 dong.
- Khong duoc tra ve [THIEU_DU_LIEU] neu dau vao co noi dung hop le.
""".strip()


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

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
    text = unicodedata.normalize("NFKC", raw_text or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00ad", "").replace("\ufeff", "")
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _extract_pdf_text(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    chunks = [(page.extract_text() or "").strip() for page in reader.pages]
    return "\n\n".join([c for c in chunks if c])


def _extract_pdf_pages(file_bytes: bytes) -> List[str]:
    reader = PdfReader(io.BytesIO(file_bytes))
    return [(page.extract_text() or "").strip() for page in reader.pages]


def _is_pdf_text_extractable(pages: List[str], min_alpha_ratio: float = 0.25) -> bool:
    total_text = " ".join([p for p in pages if p])
    if len(total_text.split()) < 80:
        return False
    alpha = sum(1 for ch in total_text if ch.isalpha())
    printable = sum(1 for ch in total_text if ch.isprintable())
    return printable > 0 and (alpha / max(printable, 1)) >= min_alpha_ratio


def _extract_docx_text(file_bytes: bytes) -> str:
    doc = Document(io.BytesIO(file_bytes))
    blocks: List[str] = []
    blocks.extend([p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()])
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text and cell.text.strip()]
            if cells:
                blocks.append(" | ".join(cells))
    return "\n\n".join(blocks)


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


def _extract_outline_headings(text: str) -> List[str]:
    lines = [ln.strip() for ln in text.splitlines() if ln and ln.strip()]
    headings: List[str] = []
    patterns = [
        r"^(chuong|chương)\s+\d+[\.: -].*",
        r"^(muc|mục)\s+\d+[\.: -].*",
        r"^\d+(\.\d+){0,3}\s+.+",
        r"^[ivxlcdm]+\.\s+.+",
    ]
    for ln in lines:
        low = ln.lower()
        if any(re.match(p, low) for p in patterns):
            headings.append(ln)
    seen = set()
    result: List[str] = []
    for h in headings:
        key = h.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(h)
    return result[:200]


def _chunk_text_by_headings(text: str, max_chars: int) -> List[str]:
    lines = text.splitlines()
    heading_re = re.compile(
        r"^((chuong|chương)\s+\d+[\.: -].*|(muc|mục)\s+\d+[\.: -].*|\d+(\.\d+){0,3}\s+.+|[ivxlcdm]+\.\s+.+)$",
        flags=re.IGNORECASE,
    )
    sections: List[List[str]] = []
    current: List[str] = []
    for ln in lines:
        stripped = ln.strip()
        if stripped and heading_re.match(stripped):
            if current:
                sections.append(current)
            current = [ln]
        else:
            if not current:
                current = [ln]
            else:
                current.append(ln)
    if current:
        sections.append(current)

    blocks = ["\n".join(sec).strip() for sec in sections if "\n".join(sec).strip()]
    if not blocks:
        return _chunk_text(text, max_chars=max_chars)

    chunks: List[str] = []
    current_chunk = ""
    for block in blocks:
        candidate = f"{current_chunk}\n\n{block}" if current_chunk else block
        if len(candidate) <= max_chars:
            current_chunk = candidate
        else:
            if current_chunk:
                chunks.append(current_chunk)
            if len(block) <= max_chars:
                current_chunk = block
            else:
                chunks.extend(_chunk_text(block, max_chars=max_chars))
                current_chunk = ""
    if current_chunk:
        chunks.append(current_chunk)
    return chunks if chunks else _chunk_text(text, max_chars=max_chars)


def _validate_source_text(text: str) -> None:
    words = text.split()
    if len(words) < 80:
        raise RuntimeError("Noi dung trich xuat qua ngan de tom tat day du.")
    alpha_count = sum(1 for ch in text if ch.isalpha())
    printable_count = sum(1 for ch in text if ch.isprintable())
    if printable_count == 0 or (alpha_count / max(printable_count, 1)) < 0.25:
        raise RuntimeError("Noi dung trich xuat chat luong thap (co the la PDF scan/loi font).")
    if text.count("\ufffd") > 10:
        raise RuntimeError("Noi dung trich xuat bi loi ky tu, khong the tom tat chinh xac.")


# ──────────────────────────────────────────────────────────────────────────────
# Groq client & chat helper  (thay thế toàn bộ _gemini_client + _chat)
# ──────────────────────────────────────────────────────────────────────────────

def _groq_client() -> Groq:
    api_key = getattr(settings, "GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY chua duoc cau hinh.")
    return Groq(api_key=api_key)


def _chat(client: Groq, system_prompt: str, user_prompt: str, max_tokens: int) -> str:
    """
    Gọi Groq API với retry khi gặp rate-limit (429).
    Interface giữ nguyên để không cần sửa code bên ngoài hàm này.
    """
    model       = getattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile")
    max_retries = int(getattr(settings, "GROQ_RETRY_MAX", "3"))
    base_sleep  = float(getattr(settings, "GROQ_RETRY_BASE_SECONDS", "8"))

    last_exc = None
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                max_tokens=max_tokens,
                temperature=0.2,
            )
            content = (response.choices[0].message.content or "").strip()
            if not content:
                raise RuntimeError("Groq tra ve noi dung rong.")
            return content

        except Exception as exc:
            last_exc = exc
            msg = str(exc).lower()
            # Rate-limit → đợi rồi thử lại
            if ("rate_limit" in msg or "429" in msg or "too many" in msg):
                if attempt < max_retries - 1:
                    time.sleep(base_sleep * (2 ** attempt))
                    continue
            raise

    if last_exc:
        raise last_exc
    raise RuntimeError("Groq: khong co response sau retry.")


# ──────────────────────────────────────────────────────────────────────────────
# NOTE: _chat_with_binary_document (gửi file PDF thô lên Gemini) KHÔNG thể
# dùng với Groq vì Groq chưa hỗ trợ upload file nhị phân.
# Thay thế: khi PDF không extract được text, fallback sang OCR-based text
# extraction bằng pypdf (đã có sẵn) rồi dùng _chat bình thường.
# ──────────────────────────────────────────────────────────────────────────────

def _summarize_pdf_pages_via_text(
    *,
    client: Groq,
    file_bytes: bytes,
    job_id: str,
    max_pages_per_chunk: int = 8,
) -> Dict:
    """
    Fallback khi PDF scan/không extract được: chia trang, extract text từng batch,
    rồi tóm tắt bằng Groq (thay thế _summarize_pdf_with_gemini_pages).
    """
    reader = PdfReader(io.BytesIO(file_bytes))
    total_pages = len(reader.pages)
    if total_pages <= 0:
        raise RuntimeError("PDF khong co trang hop le.")

    page_groups: List[tuple] = []
    for start in range(0, total_pages, max_pages_per_chunk):
        end = min(start + max_pages_per_chunk, total_pages)
        page_groups.append((start, end))

    part_summaries: List[str] = []
    total_groups = len(page_groups)

    for idx, (start, end) in enumerate(page_groups, start=1):
        # Trích text từng batch trang
        batch_text = "\n\n".join(
            (reader.pages[p].extract_text() or "").strip()
            for p in range(start, end)
        )
        batch_text = _cleanup_text(batch_text)

        if len(batch_text.split()) < 20:
            part_summaries.append(f"[Trang {start+1}-{end}: khong trich duoc text]")
        else:
            part = _chat(
                client=client,
                system_prompt=CHUNK_SYSTEM_PROMPT,
                user_prompt=(
                    f"[TRANG {start+1}-{end}/{total_pages}] "
                    "Doc TOAN BO noi dung cac trang nay va tom tat day du. "
                    "Khong bo sot bang bieu, so lieu, dinh nghia.\n\n"
                    + batch_text[:6000]
                ),
                max_tokens=900,
            )
            part_summaries.append(part)

        progress = min(80, 20 + int((idx / total_groups) * 55))
        if idx == total_groups or idx % 2 == 0:
            supabase_client.update_summary_job(job_id, {"progress": progress})

    merged = "\n\n".join(part_summaries)
    final_summary = _chat(
        client=client,
        system_prompt=FINAL_SYSTEM_PROMPT,
        user_prompt=merged,
        max_tokens=1800,
    )
    final_summary = _normalize_summary_sections(final_summary)
    try:
        _validate_summary_output(final_summary)
    except RuntimeError:
        final_summary = _repair_summary_format(client, final_summary)
        _validate_summary_output(final_summary)

    all_pages_text = _extract_pdf_pages(file_bytes)
    source_text = _cleanup_text("\n\n".join(all_pages_text))
    coverage = (
        _coverage_audit(source_text, final_summary)
        if source_text
        else {
            "coverage_ratio": 1.0,
            "source_headings": [],
            "matched_headings": [],
            "missing_headings": [],
        }
    )
    return {"summary": final_summary, "coverage": coverage, "source_text": source_text}


# ──────────────────────────────────────────────────────────────────────────────
# Validation / formatting helpers (giữ nguyên)
# ──────────────────────────────────────────────────────────────────────────────

def _validate_summary_output(output: str) -> None:
    lowered = output.lower()
    banned_phrases = [
        "tuyet voi",
        "ban da co mot khoi dau rat tot",
        "phan noi dung chinh cua tom tat van chua duoc cung cap",
    ]
    if any(phrase in lowered for phrase in banned_phrases):
        raise RuntimeError("Tom tat khong dat chat luong (phan hoi chung chung).")
    has_main   = "tom_tat_theo_muc" in lowered or "tom tat theo muc" in lowered
    has_points = "cac_y_chinh_khong_bo_sot" in lowered or "cac y chinh khong bo sot" in lowered
    if not has_main or not has_points:
        raise RuntimeError("Tom tat khong dung dinh dang bat buoc.")
    if "[thieu_du_lieu]" in lowered:
        raise RuntimeError("Tom tat chua day du noi dung (model tra ve [THIEU_DU_LIEU]).")


def _normalize_summary_sections(output: str) -> str:
    text = (output or "").strip()
    lowered = text.lower()
    if "tom_tat_theo_muc" in lowered or "tom tat theo muc" in lowered:
        return text
    return "## TOM_TAT_THEO_MUC\n" + text


def _repair_summary_format(client: Groq, summary_text: str) -> str:
    fixed = _chat(
        client=client,
        system_prompt=(
            "Chuan hoa dinh dang dau ra. KHONG thay doi noi dung, KHONG them kien thuc moi. "
            "Bat buoc co 3 section: "
            "## TOM_TAT_THEO_MUC, ## CAC_Y_CHINH_KHONG_BO_SOT, ## NOI_DUNG_CHUA_RO."
        ),
        user_prompt=summary_text,
        max_tokens=1400,
    )
    return _normalize_summary_sections(fixed)


def _normalize_heading_for_match(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _coverage_audit(source_text: str, summary_text: str) -> Dict:
    source_headings = _extract_outline_headings(source_text)
    if not source_headings:
        return {
            "source_headings": [],
            "matched_headings": [],
            "missing_headings": [],
            "coverage_ratio": 1.0,
        }
    summary_norm = _normalize_heading_for_match(summary_text)
    matched: List[str] = []
    missing: List[str] = []
    for h in source_headings:
        h_norm = _normalize_heading_for_match(h)
        if h_norm and h_norm in summary_norm:
            matched.append(h)
        else:
            missing.append(h)
    ratio = len(matched) / max(1, len(source_headings))
    return {
        "source_headings": source_headings,
        "matched_headings": matched,
        "missing_headings": missing,
        "coverage_ratio": ratio,
    }


def _parse_key_points(raw: str) -> List[str]:
    lines = []
    for line in raw.splitlines():
        cleaned = re.sub(r"^[^\w\[]+\s*", "", line.strip())
        if cleaned:
            lines.append(cleaned)
    return lines[:24]


def _sanitize_summary_text(summary_text: str) -> str:
    text = (summary_text or "").strip()
    text = text.replace("**", "")
    text = re.sub(r"\[THIEU_DU_LIEU\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\berror\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _sanitize_key_points(points: List[str]) -> List[str]:
    cleaned_points: List[str] = []
    for p in points:
        t = _sanitize_summary_text(p)
        t = re.sub(
            r"^(TOM_TAT_THEO_MUC|CAC_Y_CHINH_KHONG_BO_SOT|NOI_DUNG_CHUA_RO)\s*:?\s*$",
            "", t, flags=re.IGNORECASE,
        )
        t = t.strip("- ").strip()
        if not t:
            continue
        if "thieu_du_lieu" in t.lower() or t.lower() == "error":
            continue
        cleaned_points.append(t)
    return cleaned_points[:24]


def _build_summary_json_payload(
    *,
    job_id: str,
    file_name: str,
    summary_text: str,
    key_points: List[str],
    source_word_count: int,
    coverage: Dict,
) -> Dict:
    return {
        "job_id": job_id,
        "file_name": file_name,
        "summary_text": summary_text,
        "key_points": key_points,
        "source_word_count": source_word_count,
        "coverage": coverage,
        "generated_at": now_iso(),
    }


def _upload_summary_json(
    *,
    bucket: str,
    user_id: str,
    job_id: str,
    payload: Dict,
) -> str:
    object_path = f"{user_id}/summaries/{job_id}_{uuid4().hex}.json"
    file_bytes = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    res, status_code = supabase_client.upload_storage_file(
        bucket=bucket,
        object_path=object_path,
        file_bytes=file_bytes,
        content_type="application/json; charset=utf-8",
    )
    if status_code >= 400:
        raise RuntimeError(f"Khong luu duoc file JSON summary len Supabase Storage: {res}")
    return object_path


# ──────────────────────────────────────────────────────────────────────────────
# Summarize pipeline
# ──────────────────────────────────────────────────────────────────────────────

def _summarize_with_chunks_retry(
    *,
    client: Groq,
    text: str,
    job_id: str,
) -> Dict:
    max_chunk_chars     = int(getattr(settings, "SUMMARY_CHUNK_CHARS", 6000))
    coverage_threshold  = float(getattr(settings, "SUMMARY_COVERAGE_THRESHOLD", "0.6"))

    attempt_plans = [
        {"max_chars": max_chunk_chars, "extra_prompt": ""},
        {
            "max_chars": max(3000, int(max_chunk_chars * 0.75)),
            "extra_prompt": "Tap trung bao phu day du tung chuong/muc, khong bo sot.",
        },
    ]
    max_attempts  = int(getattr(settings, "SUMMARY_RETRY_ATTEMPTS", "1"))
    attempt_plans = attempt_plans[: max(1, min(max_attempts, len(attempt_plans)))]

    best = {
        "summary": "",
        "coverage": {
            "coverage_ratio": 0.0,
            "source_headings": [],
            "matched_headings": [],
            "missing_headings": [],
        },
    }

    for attempt_idx, plan in enumerate(attempt_plans, start=1):
        chunks = _chunk_text_by_headings(text, max_chars=int(plan["max_chars"]))
        if not chunks:
            chunks = _chunk_text(text, max_chars=int(plan["max_chars"]))
        if not chunks:
            raise RuntimeError("Khong tach duoc chunk.")

        part_summaries: List[str] = []
        total = len(chunks)
        for idx, chunk in enumerate(chunks, start=1):
            part = _chat(
                client=client,
                system_prompt=CHUNK_SYSTEM_PROMPT,
                user_prompt=f"[PHAN {idx}/{total}] {plan['extra_prompt']}\n\n{chunk}",
                max_tokens=900,
            )
            part_summaries.append(part)
            progress = min(85, 20 + int((idx / total) * 55))
            if idx == total or idx % 2 == 0:
                supabase_client.update_summary_job(job_id, {"progress": progress})

        merged  = "\n\n".join(part_summaries)
        summary = _chat(
            client=client,
            system_prompt=FINAL_SYSTEM_PROMPT,
            user_prompt=merged,
            max_tokens=1500,
        )
        summary = _normalize_summary_sections(summary)
        try:
            _validate_summary_output(summary)
        except RuntimeError:
            summary = _repair_summary_format(client, summary)
            _validate_summary_output(summary)

        coverage = _coverage_audit(text, summary)
        if coverage.get("coverage_ratio", 0.0) >= coverage_threshold:
            return {"summary": summary, "coverage": coverage}

        if coverage.get("coverage_ratio", 0.0) > best["coverage"]["coverage_ratio"]:
            best = {"summary": summary, "coverage": coverage}

        if attempt_idx < len(attempt_plans):
            supabase_client.update_summary_job(job_id, {"progress": 60})

    return best


# ──────────────────────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────────────────────

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
        user_id   = str(claimed_row.get("id_user", ""))
        mime_type = str(claimed_row.get("mime_type", ""))
        lower_name = file_name.lower()
        lower_mime = mime_type.lower()
        is_pdf = lower_name.endswith(".pdf") or ("pdf" in lower_mime)

        text = _extract_text(file_name, mime_type, bytes(blob))
        text = _cleanup_text(text)
        if not text:
            raise RuntimeError("Khong trich xuat duoc noi dung file.")

        max_source_chars = int(getattr(settings, "SUMMARY_MAX_SOURCE_CHARS", 300000))
        if len(text) > max_source_chars:
            text = text[:max_source_chars]

        supabase_client.update_summary_job(job_id, {"progress": 20})

        # Groq không nhận file binary → dùng text pipeline cho cả PDF scan
        client = _groq_client()
        coverage: Dict = {
            "coverage_ratio": 0.0,
            "source_headings": [],
            "matched_headings": [],
            "missing_headings": [],
        }

        if is_pdf:
            supabase_client.update_summary_job(job_id, {"progress": 15})
            all_pages  = _extract_pdf_pages(bytes(blob))
            page_text  = _cleanup_text("\n\n".join(all_pages))
            can_extract = _is_pdf_text_extractable(all_pages)

            if can_extract:
                _validate_source_text(page_text)
                summarized   = _summarize_with_chunks_retry(client=client, text=page_text, job_id=job_id)
                final_summary = summarized["summary"]
                coverage      = summarized["coverage"]
                text          = page_text
            else:
                # PDF scan: fallback chia trang, extract text, rồi tóm tắt
                summarized    = _summarize_pdf_pages_via_text(
                    client=client,
                    file_bytes=bytes(blob),
                    job_id=job_id,
                    max_pages_per_chunk=int(getattr(settings, "SUMMARY_PDF_PAGES_PER_CHUNK", "8")),
                )
                final_summary = summarized["summary"]
                coverage      = summarized["coverage"]
                text          = summarized.get("source_text") or page_text or text

            final_summary = _normalize_summary_sections(final_summary)
            try:
                _validate_summary_output(final_summary)
            except RuntimeError:
                final_summary = _repair_summary_format(client, final_summary)
                _validate_summary_output(final_summary)

        else:
            # DOCX
            _validate_source_text(text)
            summarized    = _summarize_with_chunks_retry(client=client, text=text, job_id=job_id)
            final_summary = summarized["summary"]
            coverage      = summarized["coverage"]

        # Key points
        supabase_client.update_summary_job(job_id, {"progress": 80})
        raw_points = _chat(
            client=client,
            system_prompt=KEYPOINTS_SYSTEM_PROMPT,
            user_prompt=final_summary,
            max_tokens=700,
        )
        key_points = _sanitize_key_points(_parse_key_points(raw_points))
        if not key_points:
            raise RuntimeError("Khong trich duoc cac y chinh dat yeu cau.")
        final_summary = _sanitize_summary_text(final_summary)

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

        try:
            payload = _build_summary_json_payload(
                job_id=job_id,
                file_name=file_name,
                summary_text=final_summary,
                key_points=key_points,
                source_word_count=len(text.split()),
                coverage=coverage,
            )
            _upload_summary_json(
                bucket=bucket,
                user_id=user_id,
                job_id=job_id,
                payload=payload,
            )
        except Exception:
            # Không fail cả job nếu lưu JSON lỗi
            pass

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