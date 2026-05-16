import io
import json as _json
import time
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

from django.conf import settings
from docx import Document
from groq import Groq
from pypdf import PdfReader, PdfWriter

from config.services import supabase_client


CHUNK_SYSTEM_PROMPT = """
Bạn là trợ lý tóm tắt học thuật tiếng Việt. Nhận một đoạn văn bản (một phần của tài liệu dài).

NHIỆM VỤ: Tóm tắt TOÀN BỘ nội dung đoạn này dưới dạng JSON hợp lệ.

QUY TẮC BẮT BUỘC:
1. CHỈ dùng thông tin có trong đoạn văn bản đầu vào — không suy diễn, không thêm kiến thức ngoài.
2. Giữ nguyên tên chương, mục, số thứ tự nếu có (ví dụ: "Chương 3", "Mục 2.1").
3. Nếu đoạn input thực sự rỗng/không đọc được → trả về JSON với chapter_summary: "[THIEU_DU_LIEU]".
4. Không viết thêm bất kỳ text nào ngoài JSON.
5. Không bọc JSON trong markdown code block (không dùng ```json).
6. Đọc KỸ toàn bộ đoạn văn, không bỏ qua bảng biểu, số liệu, định nghĩa quan trọng.

CẤU TRÚC JSON ĐẦU RA (tuân thủ chính xác):
{
  "chapters": [
    {
      "chapter_number": "1",
      "chapter_title": "Tên chương hoặc null nếu không có",
      "chapter_summary": "Tóm tắt toàn bộ nội dung chương này trong 2-4 câu, bám sát nguồn. Bao gồm số liệu, kết luận chính nếu có.",
      "sections": [
        {
          "section_number": "1.1",
          "section_title": "Tên mục",
          "section_summary": "Tóm tắt nội dung mục này trong 1-3 câu, bám sát nguồn."
        }
      ]
    }
  ],
  "key_points": [
    "Ý chính 1 — 1-2 câu, bám sát nguồn.",
    "Ý chính 2 — 1-2 câu, bám sát nguồn."
  ],
  "unclear_parts": "Ghi rõ nếu có đoạn bị cắt/thiếu/lỗi font, ngược lại để chuỗi rỗng."
}

LƯU Ý quan trọng:
- Nếu đoạn input KHÔNG có cấu trúc chương/mục rõ ràng → tạo 1 chapter với chapter_number: "0", chapter_title: null, sections: [].
- Mảng sections có thể rỗng [] nếu không có mục con.
- Trích 3-8 key_points từ đoạn này, ưu tiên định nghĩa, số liệu, kết luận cốt lõi.
- Không trả về [THIEU_DU_LIEU] nếu đoạn input có nội dung hợp lệ (dù ngắn).
""".strip()


FINAL_SYSTEM_PROMPT = """
Bạn là trợ lý tổng hợp tóm tắt học thuật tiếng Việt.
Bạn nhận một mảng JSON — mỗi phần tử là kết quả tóm tắt của một đoạn (chunk) trong cùng một tài liệu.

NHIỆM VỤ: Hợp nhất tất cả chunks thành một bản tóm tắt HOÀN CHỈNH, không bỏ sót chương/mục nào.

QUY TẮC BẮT BUỘC:
1. CHỈ tổng hợp từ nội dung đã cho — không thêm kiến thức ngoài, không suy diễn.
2. Hợp nhất các chương/mục trùng số thứ tự từ các chunks khác nhau của cùng một chương.
3. Giữ nguyên số thứ tự và tên chương/mục gốc, sắp xếp theo thứ tự tăng dần.
4. Không viết text nào ngoài JSON.
5. Không bọc JSON trong markdown code block.
6. Bao phủ ĐẦY ĐỦ tất cả chương/mục xuất hiện trong bất kỳ chunk nào.

CẤU TRÚC JSON ĐẦU RA (tuân thủ chính xác):
{
  "chapters": [
    {
      "chapter_number": "1",
      "chapter_title": "Tên chương hoặc null",
      "chapter_summary": "Tóm tắt đầy đủ chương này trong 3-5 câu, bao quát toàn bộ nội dung, bao gồm số liệu và kết luận chính.",
      "sections": [
        {
          "section_number": "1.1",
          "section_title": "Tên mục",
          "section_summary": "Tóm tắt nội dung mục, 1-3 câu, bám sát nguồn."
        }
      ]
    }
  ],
  "key_points": [
    "Ý chính quan trọng nhất — 12-24 điểm, mỗi điểm 1-2 câu, bám sát nguồn."
  ],
  "keywords": [
    "Thuật ngữ/khái niệm/tên riêng quan trọng nhất — 8-20 từ khoá ngắn"
  ],
  "unclear_sections": [
    "Liệt kê các phần bị thiếu/lỗi/cắt ngắn nếu có, để mảng rỗng [] nếu không có."
  ]
}

HƯỚNG DẪN key_points:
- 12-24 điểm, ưu tiên ý mang tính kết luận, định nghĩa, số liệu, phương pháp cốt lõi.
- Mỗi điểm là một câu hoàn chỉnh, có thể đứng độc lập, không viết tắt.

HƯỚNG DẪN keywords:
- Chỉ tên riêng, thuật ngữ chuyên ngành, khái niệm trọng tâm.
- Không dùng từ phổ thông (như "phương pháp", "kết quả", "hệ thống").
- Mỗi keyword là 1-4 từ, viết hoa đúng chuẩn.

HƯỚNG DẪN hợp nhất chapters:
- Nếu nhiều chunks đều có "Chương 2" → gộp tất cả sections và mở rộng chapter_summary.
- Loại bỏ trùng lặp, giữ thông tin đầy đủ nhất từ mỗi chunk.
""".strip()


KEYPOINTS_SYSTEM_PROMPT = """
Trích xuất key_points và keywords từ JSON tóm tắt đầu vào.

QUY TẮC:
- Chỉ dùng thông tin có trong đầu vào, không suy diễn.
- Không viết text nào ngoài JSON.
- Không bọc JSON trong markdown code block.
- Không trả về [THIEU_DU_LIEU] nếu đầu vào có nội dung hợp lệ.

JSON ĐẦU RA (tuân thủ chính xác):
{
  "key_points": [
    "Ý chính 1 — câu hoàn chỉnh, bám sát nguồn.",
    "Ý chính 2 — câu hoàn chỉnh, bám sát nguồn."
  ],
  "keywords": [
    "Thuật ngữ ngắn 1",
    "Thuật ngữ ngắn 2"
  ]
}

Trả về 12-24 key_points và 8-20 keywords.
""".strip()


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

SHORT_CHUNK_SYSTEM_PROMPT = """
Tom tat doan tai lieu thanh JSON thuần.
Chi dung thong tin trong input, khong suy dien, khong them kien thuc ngoai.
Giu ten chuong/muc/so thu tu neu co. Khong viet gi ngoai JSON, khong markdown.
Neu input rong hoac khong doc duoc, cho chapter_summary = "[THIEU_DU_LIEU]".
Schema:
{"chapters":[{"chapter_number":"1","chapter_title":"Ten chuong hoac null","chapter_summary":"2-4 cau","sections":[{"section_number":"1.1","section_title":"Ten muc","section_summary":"1-3 cau"}]}],"key_points":["3-8 y chinh"],"unclear_parts":"chuoi rong hoac mo ta loi"}
Neu khong co cau truc chuong/muc, tao 1 chapter voi chapter_number="0", chapter_title=null, sections=[].
""".strip()

SHORT_FINAL_SYSTEM_PROMPT = """
Hop nhat mang JSON cac chunk thanh 1 JSON tong hop day du, khong bo sot chuong/muc.
Chi dung du lieu da cho, khong suy dien, khong viet gi ngoai JSON, khong markdown.
Gop cac chapter/section trung so thu tu, giu ten goc, sap xep tang dan.
Schema:
{"chapters":[{"chapter_number":"1","chapter_title":"Ten chuong hoac null","chapter_summary":"3-5 cau","sections":[{"section_number":"1.1","section_title":"Ten muc","section_summary":"1-3 cau"}]}],"key_points":["8-12 y chinh"],"keywords":["8-15 tu khoa"],"unclear_sections":["cac phan mo ho neu co"]}
Key points la cau hoan chinh, bam sat nguon. Keywords la ten rieng/thuat ngu/khai niem trong tam.
""".strip()

SHORT_KEYPOINTS_SYSTEM_PROMPT = """
Trich xuat key_points va keywords tu JSON dau vao.
Chi dung thong tin co san, khong suy dien, khong viet gi ngoai JSON, khong markdown.
Schema:
{"key_points":["8-12 cau y chinh"],"keywords":["8-15 tu khoa ngan"]}
""".strip()

CHUNK_SYSTEM_PROMPT = SHORT_CHUNK_SYSTEM_PROMPT
FINAL_SYSTEM_PROMPT = SHORT_FINAL_SYSTEM_PROMPT
KEYPOINTS_SYSTEM_PROMPT = SHORT_KEYPOINTS_SYSTEM_PROMPT

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
        "keywords": row.get("keywords") or [],
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
    raise RuntimeError("Chỉ hỗ trợ PDF và DOCX.")


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
        raise RuntimeError("Nội dung trích xuất quá ngắn để tóm tắt đầy đủ.")
    alpha_count = sum(1 for ch in text if ch.isalpha())
    printable_count = sum(1 for ch in text if ch.isprintable())
    if printable_count == 0 or (alpha_count / max(printable_count, 1)) < 0.25:
        raise RuntimeError("Nội dung trích xuất chất lượng thấp (có thể là PDF scan/lỗi font).")
    if text.count("\ufffd") > 10:
        raise RuntimeError("Nội dung trích xuất bị lỗi ký tự, không thể tóm tắt chính xác.")


# ──────────────────────────────────────────────────────────────────────────────
# JSON parse / validate / repair helpers
# ──────────────────────────────────────────────────────────────────────────────

def _safe_parse_json(raw: str) -> Dict:
    """Strip markdown fences nếu model vẫn trả về ```json, rồi parse."""
    text = (raw or "").strip()
    # Bỏ ```json ... ``` nếu có
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    # Tìm JSON object đầu tiên trong response (phòng khi model thêm prose trước)
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise RuntimeError("Không tìm thấy JSON hợp lệ trong response.")
    candidate = match.group(0).strip()
    try:
        return _json.loads(candidate)
    except _json.JSONDecodeError:
        repaired = re.sub(r",\s*([}\]])", r"\1", candidate)
        repaired = re.sub(r'(["\]\}0-9A-Za-z])\s*\n\s*(")', r"\1,\n\2", repaired)
        repaired = re.sub(r'(")\s+("[-A-Za-z0-9_]+\"\s*:)', r'\1, \2', repaired)
        return _json.loads(repaired)


def _validate_summary_json(data: Dict) -> None:
    """Kiểm tra cấu trúc JSON tóm tắt tổng hợp."""
    if not isinstance(data, dict):
        raise RuntimeError("Response không phải dict JSON.")
    chapters = data.get("chapters")
    if not isinstance(chapters, list) or len(chapters) == 0:
        raise RuntimeError("JSON thiếu trường 'chapters' hoặc rỗng.")
    key_points = data.get("key_points")
    if not isinstance(key_points, list) or len(key_points) < 3:
        raise RuntimeError("JSON thiếu 'key_points' hoặc quá ít điểm.")
    # Kiểm tra THIEU_DU_LIEU lan rộng
    raw_str = _json.dumps(data, ensure_ascii=False).lower()
    thieu_count = raw_str.count("thieu_du_lieu")
    if thieu_count > len(chapters) // 2:
        raise RuntimeError("Tóm tắt chưa đầy đủ — quá nhiều [THIEU_DU_LIEU].")


def _merge_chunk_jsons(chunk_raws: List[str]) -> List[Dict]:
    """
    Parse từng chunk raw string thành dict.
    Nếu parse lỗi → giữ lại dạng {"raw_text": ...} để FINAL prompt vẫn xử lý được.
    """
    result = []
    for raw in chunk_raws:
        try:
            result.append(_safe_parse_json(raw))
        except Exception:
            result.append({"raw_text": (raw or "")[:3000]})
    return result


def _repair_summary_json(client: Groq, raw: str) -> Dict:
    """Sửa JSON lỗi cấu trúc bằng cách gọi lại model."""
    fixed_raw = _chat(
        client=client,
        system_prompt=(
            "Chuyển đổi nội dung sau thành JSON hợp lệ theo đúng cấu trúc yêu cầu. "
            "KHÔNG thay đổi nội dung, KHÔNG thêm kiến thức mới. "
            "Trả về JSON thuần, không có markdown, không có text thừa. "
            'Cấu trúc bắt buộc: {"chapters": [...], "key_points": [...], '
            '"keywords": [...], "unclear_sections": []}'
        ),
        user_prompt=raw[:4000],
        max_tokens=int(getattr(settings, "SUMMARY_REPAIR_MAX_TOKENS", "900")),
    )
    return _safe_parse_json(fixed_raw)


def _parse_key_points_from_json(data: Dict) -> List[str]:
    """Lấy key_points từ JSON tóm tắt đã parse."""
    return [str(p).strip() for p in data.get("key_points", []) if str(p).strip()]


def _parse_keywords_from_json(data: Dict) -> List[str]:
    """Lấy keywords từ JSON tóm tắt đã parse."""
    return [str(k).strip() for k in data.get("keywords", []) if str(k).strip()]


def _summary_json_to_text(data: Dict) -> str:
    """
    Chuyển JSON tóm tắt thành plain text (tương thích DB legacy / hiển thị đơn giản).
    """
    lines = []
    for ch in data.get("chapters", []):
        num = ch.get("chapter_number", "")
        title = ch.get("chapter_title") or ""
        header = f"Chương {num}" if num and str(num) != "0" else ""
        if title:
            header = f"{header}: {title}" if header else title
        if header:
            lines.append(f"## {header}")
        if ch.get("chapter_summary"):
            lines.append(ch["chapter_summary"])
        for sec in ch.get("sections", []):
            sec_num = sec.get("section_number", "")
            sec_title = sec.get("section_title") or ""
            sec_header = f"Mục {sec_num}" if sec_num else ""
            if sec_title:
                sec_header = f"{sec_header}: {sec_title}" if sec_header else sec_title
            if sec_header:
                lines.append(f"### {sec_header}")
            if sec.get("section_summary"):
                lines.append(sec["section_summary"])
    if data.get("key_points"):
        lines.append("\n## Các ý chính")
        lines.extend([f"- {p}" for p in data["key_points"]])
    if data.get("keywords"):
        lines.append("\n## Từ khoá")
        lines.append(", ".join(data["keywords"]))
    return "\n\n".join(lines).strip()


# ──────────────────────────────────────────────────────────────────────────────
# Sanitize helpers
# ──────────────────────────────────────────────────────────────────────────────

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
    return cleaned_points[:12]


def _sanitize_summary_json(data: Dict) -> Dict:
    """Làm sạch các trường trong summary JSON."""
    cleaned = dict(data)
    # Làm sạch chapters
    chapters = []
    for ch in cleaned.get("chapters", []):
        ch_clean = dict(ch)
        ch_clean["chapter_summary"] = _sanitize_summary_text(ch.get("chapter_summary", ""))
        sections = []
        for sec in ch.get("sections", []):
            sec_clean = dict(sec)
            sec_clean["section_summary"] = _sanitize_summary_text(sec.get("section_summary", ""))
            if sec_clean.get("section_summary"):
                sections.append(sec_clean)
        ch_clean["sections"] = sections
        if ch_clean.get("chapter_summary") or sections:
            chapters.append(ch_clean)
    cleaned["chapters"] = chapters
    cleaned["key_points"] = _sanitize_key_points(cleaned.get("key_points", []))
    cleaned["keywords"] = [str(k).strip() for k in cleaned.get("keywords", []) if str(k).strip()][:20]
    cleaned["unclear_sections"] = [str(s).strip() for s in cleaned.get("unclear_sections", []) if str(s).strip()]
    return cleaned


# ──────────────────────────────────────────────────────────────────────────────
# Coverage audit
# ──────────────────────────────────────────────────────────────────────────────

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


# ──────────────────────────────────────────────────────────────────────────────
# Storage helpers
# ──────────────────────────────────────────────────────────────────────────────

def _build_summary_json_payload(
    *,
    job_id: str,
    file_name: str,
    summary_text: str,
    summary_json: Dict,
    key_points: List[str],
    keywords: List[str],
    source_word_count: int,
    coverage: Dict,
) -> Dict:
    return {
        "job_id": job_id,
        "file_name": file_name,
        "summary_text": summary_text,
        "summary_json": summary_json,
        "key_points": key_points,
        "keywords": keywords,
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
    file_bytes = _json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    res, status_code = supabase_client.upload_storage_file(
        bucket=bucket,
        object_path=object_path,
        file_bytes=file_bytes,
        content_type="application/json; charset=utf-8",
    )
    if status_code >= 400:
        raise RuntimeError(f"Không lưu được file JSON summary lên Supabase Storage: {res}")
    return object_path


# ──────────────────────────────────────────────────────────────────────────────
# Groq client & chat helper
# ──────────────────────────────────────────────────────────────────────────────

def _groq_client() -> Groq:
    api_key = getattr(settings, "GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY chưa được cấu hình.")
    return Groq(api_key=api_key)


def _chat(client: Groq, system_prompt: str, user_prompt: str, max_tokens: int) -> str:
    """
    Gọi Groq API với retry khi gặp rate-limit (429).
    """
    model       = getattr(settings, "GROQ_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
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
                raise RuntimeError("Groq trả về nội dung rỗng.")
            return content

        except Exception as exc:
            last_exc = exc
            msg = str(exc).lower()
            if "rate_limit" in msg or "429" in msg or "too many" in msg:
                if attempt < max_retries - 1:
                    time.sleep(base_sleep * (2 ** attempt))
                    continue
            raise

    if last_exc:
        raise last_exc
    raise RuntimeError("Groq: không có response sau retry.")


# ──────────────────────────────────────────────────────────────────────────────
# PDF scan fallback — chia trang, extract text, tóm tắt từng batch
# ──────────────────────────────────────────────────────────────────────────────

def _summarize_pdf_pages_via_text(
    *,
    client: Groq,
    file_bytes: bytes,
    job_id: str,
    max_pages_per_chunk: int = 8,
) -> Dict:
    """
    Fallback cho PDF scan hoặc PDF không extract được text tốt:
    chia trang theo batch, extract text từng batch, tóm tắt bằng Groq.
    """
    reader = PdfReader(io.BytesIO(file_bytes))
    total_pages = len(reader.pages)
    if total_pages <= 0:
        raise RuntimeError("PDF không có trang hợp lệ.")

    page_groups: List[tuple] = []
    for start in range(0, total_pages, max_pages_per_chunk):
        end = min(start + max_pages_per_chunk, total_pages)
        page_groups.append((start, end))

    chunk_raws: List[str] = []
    total_groups = len(page_groups)

    for idx, (start, end) in enumerate(page_groups, start=1):
        batch_text = "\n\n".join(
            (reader.pages[p].extract_text() or "").strip()
            for p in range(start, end)
        )
        batch_text = _cleanup_text(batch_text)

        if len(batch_text.split()) < 20:
            # Tạo chunk JSON giả cho batch không có text
            chunk_raws.append(_json.dumps({
                "chapters": [{
                    "chapter_number": "0",
                    "chapter_title": None,
                    "chapter_summary": f"[Trang {start+1}-{end}: không trích được text]",
                    "sections": []
                }],
                "key_points": [],
                "unclear_parts": f"Trang {start+1}-{end} không trích được text (PDF scan hoặc lỗi font)."
            }, ensure_ascii=False))
        else:
            raw = _chat(
                client=client,
                system_prompt=CHUNK_SYSTEM_PROMPT,
                user_prompt=(
                    f"[TRANG {start+1}-{end}/{total_pages}] "
                    "Đọc TOÀN BỘ nội dung các trang này và tóm tắt đầy đủ. "
                    "Không bỏ sót bảng biểu, số liệu, định nghĩa.\n\n"
                    + batch_text[:6000]
                ),
                max_tokens=int(getattr(settings, "SUMMARY_CHUNK_MAX_TOKENS", "650")),
            )
            chunk_raws.append(raw)

        progress = min(80, 20 + int((idx / total_groups) * 55))
        if idx == total_groups or idx % 2 == 0:
            supabase_client.update_summary_job(job_id, {"progress": progress})

    # Gộp tất cả chunks → gọi FINAL
    merged_chunks = _merge_chunk_jsons(chunk_raws)
    merged_input  = _json.dumps(merged_chunks, ensure_ascii=False)

    final_raw = _chat(
        client=client,
        system_prompt=FINAL_SYSTEM_PROMPT,
        user_prompt=merged_input,
        max_tokens=int(getattr(settings, "SUMMARY_FINAL_MAX_TOKENS", "1200")),
    )
    try:
        summary_data = _safe_parse_json(final_raw)
    except Exception:
        summary_data = _repair_summary_json(client, final_raw)

    try:
        _validate_summary_json(summary_data)
    except RuntimeError:
        summary_data = _repair_summary_json(client, final_raw)
        _validate_summary_json(summary_data)

    summary_data = _sanitize_summary_json(summary_data)
    summary_text = _summary_json_to_text(summary_data)

    all_pages_text = _extract_pdf_pages(file_bytes)
    source_text = _cleanup_text("\n\n".join(all_pages_text))
    coverage = (
        _coverage_audit(source_text, summary_text)
        if source_text
        else {
            "coverage_ratio": 1.0,
            "source_headings": [],
            "matched_headings": [],
            "missing_headings": [],
        }
    )
    return {
        "summary_data": summary_data,
        "summary_text": summary_text,
        "coverage": coverage,
        "source_text": source_text,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Main summarize pipeline — chunk by headings/paragraphs, retry nếu coverage thấp
# ──────────────────────────────────────────────────────────────────────────────

def _summarize_with_chunks_retry(
    *,
    client: Groq,
    text: str,
    job_id: str,
) -> Dict:
    max_chunk_chars    = int(getattr(settings, "SUMMARY_CHUNK_CHARS", 6000))
    coverage_threshold = float(getattr(settings, "SUMMARY_COVERAGE_THRESHOLD", "0.6"))

    attempt_plans = [
        {"max_chars": max_chunk_chars, "extra_prompt": ""},
        {
            "max_chars": max(3000, int(max_chunk_chars * 0.75)),
            "extra_prompt": "Tập trung bao phủ đầy đủ từng chương/mục, không bỏ sót.",
        },
    ]
    max_attempts  = int(getattr(settings, "SUMMARY_RETRY_ATTEMPTS", "1"))
    attempt_plans = attempt_plans[: max(1, min(max_attempts, len(attempt_plans)))]

    best: Dict = {
        "summary_data": {},
        "summary_text": "",
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
            raise RuntimeError("Không tách được chunk.")

        chunk_raws: List[str] = []
        total = len(chunks)

        for idx, chunk in enumerate(chunks, start=1):
            raw = _chat(
                client=client,
                system_prompt=CHUNK_SYSTEM_PROMPT,
                user_prompt=(
                    f"[PHẦN {idx}/{total}] {plan['extra_prompt']}\n\n{chunk}"
                ),
                max_tokens=int(getattr(settings, "SUMMARY_CHUNK_MAX_TOKENS", "650")),
            )
            chunk_raws.append(raw)
            progress = min(85, 20 + int((idx / total) * 55))
            if idx == total or idx % 2 == 0:
                supabase_client.update_summary_job(job_id, {"progress": progress})

        # Gộp các chunk JSON → gọi FINAL
        merged_chunks = _merge_chunk_jsons(chunk_raws)
        merged_input  = _json.dumps(merged_chunks, ensure_ascii=False)

        final_raw = _chat(
            client=client,
            system_prompt=FINAL_SYSTEM_PROMPT,
            user_prompt=merged_input,
            max_tokens=int(getattr(settings, "SUMMARY_FINAL_MAX_TOKENS", "1200")),
        )
        try:
            summary_data = _safe_parse_json(final_raw)
        except Exception:
            summary_data = _repair_summary_json(client, final_raw)

        try:
            _validate_summary_json(summary_data)
        except RuntimeError:
            summary_data = _repair_summary_json(client, final_raw)
            _validate_summary_json(summary_data)

        summary_data = _sanitize_summary_json(summary_data)
        summary_text = _summary_json_to_text(summary_data)
        coverage     = _coverage_audit(text, summary_text)

        if coverage.get("coverage_ratio", 0.0) >= coverage_threshold:
            return {
                "summary_data": summary_data,
                "summary_text": summary_text,
                "coverage": coverage,
            }

        if coverage.get("coverage_ratio", 0.0) > best["coverage"]["coverage_ratio"]:
            best = {
                "summary_data": summary_data,
                "summary_text": summary_text,
                "coverage": coverage,
            }

        if attempt_idx < len(attempt_plans):
            supabase_client.update_summary_job(job_id, {"progress": 60})

    return best


# ──────────────────────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────────────────────

def process_summary_job(job_id: str) -> None:
    claimed_row, claimed_status = supabase_client.claim_summary_job(job_id)
    if claimed_status >= 400:
        raise RuntimeError("Không claim được job để xử lý.")
    if not claimed_row:
        return

    try:
        bucket = getattr(settings, "SUPABASE_STORAGE_BUCKET", "study-documents")

        # ── 1. Tải file ──────────────────────────────────────────────────────
        blob, blob_status = supabase_client.download_storage_file(
            bucket=bucket,
            object_path=str(claimed_row.get("storage_path", "")),
        )
        if blob_status >= 400 or not isinstance(blob, (bytes, bytearray)):
            raise RuntimeError("Không tải được file từ Supabase Storage.")

        file_name  = str(claimed_row.get("file_name", ""))
        user_id    = str(claimed_row.get("id_user", ""))
        mime_type  = str(claimed_row.get("mime_type", ""))
        lower_name = file_name.lower()
        lower_mime = mime_type.lower()
        is_pdf     = lower_name.endswith(".pdf") or ("pdf" in lower_mime)

        # ── 2. Extract text ──────────────────────────────────────────────────
        text = _extract_text(file_name, mime_type, bytes(blob))
        text = _cleanup_text(text)
        if not text:
            raise RuntimeError("Không trích xuất được nội dung file.")

        max_source_chars = int(getattr(settings, "SUMMARY_MAX_SOURCE_CHARS", 120000))
        if len(text) > max_source_chars:
            text = text[:max_source_chars]

        supabase_client.update_summary_job(job_id, {"progress": 20})

        # ── 3. Tóm tắt ──────────────────────────────────────────────────────
        client: Groq = _groq_client()
        coverage: Dict = {
            "coverage_ratio": 0.0,
            "source_headings": [],
            "matched_headings": [],
            "missing_headings": [],
        }
        summary_data: Dict = {}
        final_summary_text: str = ""

        if is_pdf:
            supabase_client.update_summary_job(job_id, {"progress": 15})
            all_pages   = _extract_pdf_pages(bytes(blob))
            page_text   = _cleanup_text("\n\n".join(all_pages))
            can_extract = _is_pdf_text_extractable(all_pages)

            if can_extract:
                _validate_source_text(page_text)
                summarized = _summarize_with_chunks_retry(
                    client=client, text=page_text, job_id=job_id
                )
                summary_data       = summarized["summary_data"]
                final_summary_text = summarized["summary_text"]
                coverage           = summarized["coverage"]
                text               = page_text
            else:
                # PDF scan fallback
                summarized = _summarize_pdf_pages_via_text(
                    client=client,
                    file_bytes=bytes(blob),
                    job_id=job_id,
                    max_pages_per_chunk=int(
                        getattr(settings, "SUMMARY_PDF_PAGES_PER_CHUNK", "12")
                    ),
                )
                summary_data       = summarized["summary_data"]
                final_summary_text = summarized["summary_text"]
                coverage           = summarized["coverage"]
                text               = summarized.get("source_text") or page_text or text

        else:
            # DOCX
            _validate_source_text(text)
            summarized = _summarize_with_chunks_retry(
                client=client, text=text, job_id=job_id
            )
            summary_data       = summarized["summary_data"]
            final_summary_text = summarized["summary_text"]
            coverage           = summarized["coverage"]

        # ── 4. Key points & keywords ─────────────────────────────────────────
        supabase_client.update_summary_job(job_id, {"progress": 88})

        key_points: List[str] = _sanitize_key_points(
            _parse_key_points_from_json(summary_data)
        )
        keywords: List[str] = _parse_keywords_from_json(summary_data)

        # Fallback: nếu key_points rỗng → gọi KEYPOINTS_SYSTEM_PROMPT
        if not key_points:
            raw_kp = _chat(
                client=client,
                system_prompt=KEYPOINTS_SYSTEM_PROMPT,
                user_prompt=_json.dumps(summary_data, ensure_ascii=False)[:4000],
                max_tokens=int(getattr(settings, "SUMMARY_KEYPOINTS_MAX_TOKENS", "450")),
            )
            try:
                kp_data    = _safe_parse_json(raw_kp)
                key_points = _sanitize_key_points(kp_data.get("key_points", []))
                if not keywords:
                    keywords = [str(k).strip() for k in kp_data.get("keywords", []) if str(k).strip()]
            except Exception:
                # Fallback text parse nếu JSON lỗi
                key_points = _sanitize_key_points(
                    [
                        re.sub(r"^[^\w\[]+\s*", "", ln.strip())
                        for ln in raw_kp.splitlines()
                        if ln.strip()
                    ]
                )

        if not key_points:
            raise RuntimeError("Không trích được các ý chính đạt yêu cầu.")

        final_summary_text = _sanitize_summary_text(final_summary_text)

        # ── 5. Lưu DB ────────────────────────────────────────────────────────
        supabase_client.update_summary_job(
            job_id,
            {
                "status": "done",
                "progress": 100,
                "summary_text": final_summary_text,
                "summary_json": summary_data,
                "key_points": key_points,
                "keywords": keywords,
                "source_word_count": len(text.split()),
                "finished_at": now_iso(),
                "error_message": None,
            },
        )

        # ── 6. Lưu JSON file lên Storage (non-blocking) ──────────────────────
        try:
            payload = _build_summary_json_payload(
                job_id=job_id,
                file_name=file_name,
                summary_text=final_summary_text,
                summary_json=summary_data,
                key_points=key_points,
                keywords=keywords,
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
                "error_message": str(exc)[:1000] if str(exc) else "Không rõ lỗi.",
            },
        )
