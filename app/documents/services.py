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
from google import genai
from google.genai import types
from pypdf import PdfReader, PdfWriter

from config.services import supabase_client


CHUNK_SYSTEM_PROMPT = """
Báº¡n lÃ  trá»£ lÃ½ tÃ³m táº¯t há»c thuáº­t tiáº¿ng Viá»‡t. Nháº­n má»™t Ä‘oáº¡n vÄƒn báº£n (má»™t pháº§n cá»§a tÃ i liá»‡u dÃ i).

NHIá»†M Vá»¤: TÃ³m táº¯t TOÃ€N Bá»˜ ná»™i dung Ä‘oáº¡n nÃ y dÆ°á»›i dáº¡ng JSON há»£p lá»‡.

QUY Táº®C Báº®T BUá»˜C:
1. CHá»ˆ dÃ¹ng thÃ´ng tin cÃ³ trong Ä‘oáº¡n vÄƒn báº£n Ä‘áº§u vÃ o â€” khÃ´ng suy diá»…n, khÃ´ng thÃªm kiáº¿n thá»©c ngoÃ i.
2. Giá»¯ nguyÃªn tÃªn chÆ°Æ¡ng, má»¥c, sá»‘ thá»© tá»± náº¿u cÃ³ (vÃ­ dá»¥: "ChÆ°Æ¡ng 3", "Má»¥c 2.1").
3. Náº¿u Ä‘oáº¡n input thá»±c sá»± rá»—ng/khÃ´ng Ä‘á»c Ä‘Æ°á»£c â†’ tráº£ vá» JSON vá»›i chapter_summary: "[THIEU_DU_LIEU]".
4. KhÃ´ng viáº¿t thÃªm báº¥t ká»³ text nÃ o ngoÃ i JSON.
5. KhÃ´ng bá»c JSON trong markdown code block (khÃ´ng dÃ¹ng ```json).
6. Äá»c Ká»¸ toÃ n bá»™ Ä‘oáº¡n vÄƒn, khÃ´ng bá» qua báº£ng biá»ƒu, sá»‘ liá»‡u, Ä‘á»‹nh nghÄ©a quan trá»ng.

Cáº¤U TRÃšC JSON Äáº¦U RA (tuÃ¢n thá»§ chÃ­nh xÃ¡c):
{
  "chapters": [
    {
      "chapter_number": "1",
      "chapter_title": "TÃªn chÆ°Æ¡ng hoáº·c null náº¿u khÃ´ng cÃ³",
      "chapter_summary": "TÃ³m táº¯t toÃ n bá»™ ná»™i dung chÆ°Æ¡ng nÃ y trong 2-4 cÃ¢u, bÃ¡m sÃ¡t nguá»“n. Bao gá»“m sá»‘ liá»‡u, káº¿t luáº­n chÃ­nh náº¿u cÃ³.",
      "sections": [
        {
          "section_number": "1.1",
          "section_title": "TÃªn má»¥c",
          "section_summary": "TÃ³m táº¯t ná»™i dung má»¥c nÃ y trong 1-3 cÃ¢u, bÃ¡m sÃ¡t nguá»“n."
        }
      ]
    }
  ],
  "key_points": [
    "Ã chÃ­nh 1 â€” 1-2 cÃ¢u, bÃ¡m sÃ¡t nguá»“n.",
    "Ã chÃ­nh 2 â€” 1-2 cÃ¢u, bÃ¡m sÃ¡t nguá»“n."
  ],
  "unclear_parts": "Ghi rÃµ náº¿u cÃ³ Ä‘oáº¡n bá»‹ cáº¯t/thiáº¿u/lá»—i font, ngÆ°á»£c láº¡i Ä‘á»ƒ chuá»—i rá»—ng."
}

LÆ¯U Ã quan trá»ng:
- Náº¿u Ä‘oáº¡n input KHÃ”NG cÃ³ cáº¥u trÃºc chÆ°Æ¡ng/má»¥c rÃµ rÃ ng â†’ táº¡o 1 chapter vá»›i chapter_number: "0", chapter_title: null, sections: [].
- Máº£ng sections cÃ³ thá»ƒ rá»—ng [] náº¿u khÃ´ng cÃ³ má»¥c con.
- TrÃ­ch 3-8 key_points tá»« Ä‘oáº¡n nÃ y, Æ°u tiÃªn Ä‘á»‹nh nghÄ©a, sá»‘ liá»‡u, káº¿t luáº­n cá»‘t lÃµi.
- KhÃ´ng tráº£ vá» [THIEU_DU_LIEU] náº¿u Ä‘oáº¡n input cÃ³ ná»™i dung há»£p lá»‡ (dÃ¹ ngáº¯n).
""".strip()


FINAL_SYSTEM_PROMPT = """
Báº¡n lÃ  trá»£ lÃ½ tá»•ng há»£p tÃ³m táº¯t há»c thuáº­t tiáº¿ng Viá»‡t.
Báº¡n nháº­n má»™t máº£ng JSON â€” má»—i pháº§n tá»­ lÃ  káº¿t quáº£ tÃ³m táº¯t cá»§a má»™t Ä‘oáº¡n (chunk) trong cÃ¹ng má»™t tÃ i liá»‡u.

NHIá»†M Vá»¤: Há»£p nháº¥t táº¥t cáº£ chunks thÃ nh má»™t báº£n tÃ³m táº¯t HOÃ€N CHá»ˆNH, khÃ´ng bá» sÃ³t chÆ°Æ¡ng/má»¥c nÃ o.

QUY Táº®C Báº®T BUá»˜C:
1. CHá»ˆ tá»•ng há»£p tá»« ná»™i dung Ä‘Ã£ cho â€” khÃ´ng thÃªm kiáº¿n thá»©c ngoÃ i, khÃ´ng suy diá»…n.
2. Há»£p nháº¥t cÃ¡c chÆ°Æ¡ng/má»¥c trÃ¹ng sá»‘ thá»© tá»± tá»« cÃ¡c chunks khÃ¡c nhau cá»§a cÃ¹ng má»™t chÆ°Æ¡ng.
3. Giá»¯ nguyÃªn sá»‘ thá»© tá»± vÃ  tÃªn chÆ°Æ¡ng/má»¥c gá»‘c, sáº¯p xáº¿p theo thá»© tá»± tÄƒng dáº§n.
4. KhÃ´ng viáº¿t text nÃ o ngoÃ i JSON.
5. KhÃ´ng bá»c JSON trong markdown code block.
6. Bao phá»§ Äáº¦Y Äá»¦ táº¥t cáº£ chÆ°Æ¡ng/má»¥c xuáº¥t hiá»‡n trong báº¥t ká»³ chunk nÃ o.

Cáº¤U TRÃšC JSON Äáº¦U RA (tuÃ¢n thá»§ chÃ­nh xÃ¡c):
{
  "chapters": [
    {
      "chapter_number": "1",
      "chapter_title": "TÃªn chÆ°Æ¡ng hoáº·c null",
      "chapter_summary": "TÃ³m táº¯t Ä‘áº§y Ä‘á»§ chÆ°Æ¡ng nÃ y trong 3-5 cÃ¢u, bao quÃ¡t toÃ n bá»™ ná»™i dung, bao gá»“m sá»‘ liá»‡u vÃ  káº¿t luáº­n chÃ­nh.",
      "sections": [
        {
          "section_number": "1.1",
          "section_title": "TÃªn má»¥c",
          "section_summary": "TÃ³m táº¯t ná»™i dung má»¥c, 1-3 cÃ¢u, bÃ¡m sÃ¡t nguá»“n."
        }
      ]
    }
  ],
  "key_points": [
    "Ã chÃ­nh quan trá»ng nháº¥t â€” 12-24 Ä‘iá»ƒm, má»—i Ä‘iá»ƒm 1-2 cÃ¢u, bÃ¡m sÃ¡t nguá»“n."
  ],
  "keywords": [
    "Thuáº­t ngá»¯/khÃ¡i niá»‡m/tÃªn riÃªng quan trá»ng nháº¥t â€” 8-20 tá»« khoÃ¡ ngáº¯n"
  ],
  "unclear_sections": [
    "Liá»‡t kÃª cÃ¡c pháº§n bá»‹ thiáº¿u/lá»—i/cáº¯t ngáº¯n náº¿u cÃ³, Ä‘á»ƒ máº£ng rá»—ng [] náº¿u khÃ´ng cÃ³."
  ]
}

HÆ¯á»šNG DáºªN key_points:
- 12-24 Ä‘iá»ƒm, Æ°u tiÃªn Ã½ mang tÃ­nh káº¿t luáº­n, Ä‘á»‹nh nghÄ©a, sá»‘ liá»‡u, phÆ°Æ¡ng phÃ¡p cá»‘t lÃµi.
- Má»—i Ä‘iá»ƒm lÃ  má»™t cÃ¢u hoÃ n chá»‰nh, cÃ³ thá»ƒ Ä‘á»©ng Ä‘á»™c láº­p, khÃ´ng viáº¿t táº¯t.

HÆ¯á»šNG DáºªN keywords:
- Chá»‰ tÃªn riÃªng, thuáº­t ngá»¯ chuyÃªn ngÃ nh, khÃ¡i niá»‡m trá»ng tÃ¢m.
- KhÃ´ng dÃ¹ng tá»« phá»• thÃ´ng (nhÆ° "phÆ°Æ¡ng phÃ¡p", "káº¿t quáº£", "há»‡ thá»‘ng").
- Má»—i keyword lÃ  1-4 tá»«, viáº¿t hoa Ä‘Ãºng chuáº©n.

HÆ¯á»šNG DáºªN há»£p nháº¥t chapters:
- Náº¿u nhiá»u chunks Ä‘á»u cÃ³ "ChÆ°Æ¡ng 2" â†’ gá»™p táº¥t cáº£ sections vÃ  má»Ÿ rá»™ng chapter_summary.
- Loáº¡i bá» trÃ¹ng láº·p, giá»¯ thÃ´ng tin Ä‘áº§y Ä‘á»§ nháº¥t tá»« má»—i chunk.
""".strip()


KEYPOINTS_SYSTEM_PROMPT = """
TrÃ­ch xuáº¥t key_points vÃ  keywords tá»« JSON tÃ³m táº¯t Ä‘áº§u vÃ o.

QUY Táº®C:
- Chá»‰ dÃ¹ng thÃ´ng tin cÃ³ trong Ä‘áº§u vÃ o, khÃ´ng suy diá»…n.
- KhÃ´ng viáº¿t text nÃ o ngoÃ i JSON.
- KhÃ´ng bá»c JSON trong markdown code block.
- KhÃ´ng tráº£ vá» [THIEU_DU_LIEU] náº¿u Ä‘áº§u vÃ o cÃ³ ná»™i dung há»£p lá»‡.

JSON Äáº¦U RA (tuÃ¢n thá»§ chÃ­nh xÃ¡c):
{
  "key_points": [
    "Ã chÃ­nh 1 â€” cÃ¢u hoÃ n chá»‰nh, bÃ¡m sÃ¡t nguá»“n.",
    "Ã chÃ­nh 2 â€” cÃ¢u hoÃ n chá»‰nh, bÃ¡m sÃ¡t nguá»“n."
  ],
  "keywords": [
    "Thuáº­t ngá»¯ ngáº¯n 1",
    "Thuáº­t ngá»¯ ngáº¯n 2"
  ]
}

Tráº£ vá» 12-24 key_points vÃ  8-20 keywords.
""".strip()


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Helpers
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

SHORT_CHUNK_SYSTEM_PROMPT = """
Tom tat doan tai lieu thanh JSON thuáº§n.
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
    raise RuntimeError("Chá»‰ há»— trá»£ PDF vÃ  DOCX.")


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
        r"^(chuong|chÆ°Æ¡ng)\s+\d+[\.: -].*",
        r"^(muc|má»¥c)\s+\d+[\.: -].*",
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
        r"^((chuong|chÆ°Æ¡ng)\s+\d+[\.: -].*|(muc|má»¥c)\s+\d+[\.: -].*|\d+(\.\d+){0,3}\s+.+|[ivxlcdm]+\.\s+.+)$",
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
        raise RuntimeError("Ná»™i dung trÃ­ch xuáº¥t quÃ¡ ngáº¯n Ä‘á»ƒ tÃ³m táº¯t Ä‘áº§y Ä‘á»§.")
    alpha_count = sum(1 for ch in text if ch.isalpha())
    printable_count = sum(1 for ch in text if ch.isprintable())
    if printable_count == 0 or (alpha_count / max(printable_count, 1)) < 0.25:
        raise RuntimeError("Ná»™i dung trÃ­ch xuáº¥t cháº¥t lÆ°á»£ng tháº¥p (cÃ³ thá»ƒ lÃ  PDF scan/lá»—i font).")
    if text.count("\ufffd") > 10:
        raise RuntimeError("Ná»™i dung trÃ­ch xuáº¥t bá»‹ lá»—i kÃ½ tá»±, khÃ´ng thá»ƒ tÃ³m táº¯t chÃ­nh xÃ¡c.")


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# JSON parse / validate / repair helpers
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _safe_parse_json(raw: str) -> Dict:
    """Strip markdown fences náº¿u model váº«n tráº£ vá» ```json, rá»“i parse."""
    text = (raw or "").strip()
    # Bá» ```json ... ``` náº¿u cÃ³
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    # TÃ¬m JSON object Ä‘áº§u tiÃªn trong response (phÃ²ng khi model thÃªm prose trÆ°á»›c)
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise RuntimeError("KhÃ´ng tÃ¬m tháº¥y JSON há»£p lá»‡ trong response.")
    candidate = match.group(0).strip()
    try:
        return _json.loads(candidate)
    except _json.JSONDecodeError:
        repaired = re.sub(r",\s*([}\]])", r"\1", candidate)
        repaired = re.sub(r'(["\]\}0-9A-Za-z])\s*\n\s*(")', r"\1,\n\2", repaired)
        repaired = re.sub(r'(")\s+("[-A-Za-z0-9_]+\"\s*:)', r'\1, \2', repaired)
        return _json.loads(repaired)


def _validate_summary_json(data: Dict) -> None:
    """Kiá»ƒm tra cáº¥u trÃºc JSON tÃ³m táº¯t tá»•ng há»£p."""
    if not isinstance(data, dict):
        raise RuntimeError("Response khÃ´ng pháº£i dict JSON.")
    chapters = data.get("chapters")
    if not isinstance(chapters, list) or len(chapters) == 0:
        raise RuntimeError("JSON thiáº¿u trÆ°á»ng 'chapters' hoáº·c rá»—ng.")
    key_points = data.get("key_points")
    if not isinstance(key_points, list) or len(key_points) < 3:
        raise RuntimeError("JSON thiáº¿u 'key_points' hoáº·c quÃ¡ Ã­t Ä‘iá»ƒm.")
    # Kiá»ƒm tra THIEU_DU_LIEU lan rá»™ng
    raw_str = _json.dumps(data, ensure_ascii=False).lower()
    thieu_count = raw_str.count("thieu_du_lieu")
    if thieu_count > len(chapters) // 2:
        raise RuntimeError("TÃ³m táº¯t chÆ°a Ä‘áº§y Ä‘á»§ â€” quÃ¡ nhiá»u [THIEU_DU_LIEU].")


def _merge_chunk_jsons(chunk_raws: List[str]) -> List[Dict]:
    """
    Parse tá»«ng chunk raw string thÃ nh dict.
    Náº¿u parse lá»—i â†’ giá»¯ láº¡i dáº¡ng {"raw_text": ...} Ä‘á»ƒ FINAL prompt váº«n xá»­ lÃ½ Ä‘Æ°á»£c.
    """
    result = []
    for raw in chunk_raws:
        try:
            result.append(_safe_parse_json(raw))
        except Exception:
            result.append({"raw_text": (raw or "")[:3000]})
    return result


def _fallback_summary_json_from_chunks(chunk_dicts: List[Dict]) -> Dict:
    chapters: List[Dict] = []
    key_points: List[str] = []
    keywords: List[str] = []
    unclear_sections: List[str] = []

    chapter_map: Dict[str, Dict] = {}
    section_seen: Dict[str, set] = {}

    for item in chunk_dicts:
        for ch in item.get("chapters", []) if isinstance(item, dict) else []:
            chapter_number = str(ch.get("chapter_number") or "0").strip()
            chapter_title = ch.get("chapter_title")
            chapter_key = chapter_number or "0"
            if chapter_key not in chapter_map:
                chapter_map[chapter_key] = {
                    "chapter_number": chapter_number or "0",
                    "chapter_title": chapter_title,
                    "chapter_summary": str(ch.get("chapter_summary") or "").strip(),
                    "sections": [],
                }
                section_seen[chapter_key] = set()
            else:
                current_summary = chapter_map[chapter_key].get("chapter_summary", "")
                new_summary = str(ch.get("chapter_summary") or "").strip()
                if len(new_summary) > len(current_summary):
                    chapter_map[chapter_key]["chapter_summary"] = new_summary
                if not chapter_map[chapter_key].get("chapter_title") and chapter_title:
                    chapter_map[chapter_key]["chapter_title"] = chapter_title

            for sec in ch.get("sections", []) if isinstance(ch, dict) else []:
                sec_num = str(sec.get("section_number") or "").strip()
                sec_title = str(sec.get("section_title") or "").strip()
                sec_key = f"{sec_num}|{sec_title}".lower()
                if sec_key in section_seen[chapter_key]:
                    continue
                section_seen[chapter_key].add(sec_key)
                chapter_map[chapter_key]["sections"].append(
                    {
                        "section_number": sec_num,
                        "section_title": sec.get("section_title"),
                        "section_summary": str(sec.get("section_summary") or "").strip(),
                    }
                )

        for kp in item.get("key_points", []) if isinstance(item, dict) else []:
            text = str(kp).strip()
            if text and text not in key_points:
                key_points.append(text)

        for kw in item.get("keywords", []) if isinstance(item, dict) else []:
            text = str(kw).strip()
            if text and text not in keywords:
                keywords.append(text)

        for unclear in item.get("unclear_sections", []) if isinstance(item, dict) else []:
            text = str(unclear).strip()
            if text and text not in unclear_sections:
                unclear_sections.append(text)

        raw_text = str(item.get("raw_text") or "").strip() if isinstance(item, dict) else ""
        if raw_text and raw_text not in unclear_sections:
            unclear_sections.append("Mot chunk khong parse duoc JSON tong hop.")

    chapters = sorted(
        chapter_map.values(),
        key=lambda x: (str(x.get("chapter_number") or "9999")),
    )

    if not chapters:
        chapters = [
            {
                "chapter_number": "0",
                "chapter_title": None,
                "chapter_summary": "Khong tong hop duoc day du tu ket qua chunk.",
                "sections": [],
            }
        ]

    return {
        "chapters": chapters,
        "key_points": key_points[:12],
        "keywords": keywords[:15],
        "unclear_sections": unclear_sections[:20],
    }


def _repair_summary_json(client: genai.Client, raw: str) -> Dict:
    """Sá»­a JSON lá»—i cáº¥u trÃºc báº±ng cÃ¡ch gá»i láº¡i model."""
    if not bool(getattr(settings, "SUMMARY_ENABLE_MODEL_REPAIR", False)):
        raise RuntimeError("Model repair is disabled.")
    fixed_raw = _chat(
        client=client,
        system_prompt=(
            "Chuyá»ƒn Ä‘á»•i ná»™i dung sau thÃ nh JSON há»£p lá»‡ theo Ä‘Ãºng cáº¥u trÃºc yÃªu cáº§u. "
            "KHÃ”NG thay Ä‘á»•i ná»™i dung, KHÃ”NG thÃªm kiáº¿n thá»©c má»›i. "
            "Tráº£ vá» JSON thuáº§n, khÃ´ng cÃ³ markdown, khÃ´ng cÃ³ text thá»«a. "
            'Cáº¥u trÃºc báº¯t buá»™c: {"chapters": [...], "key_points": [...], '
            '"keywords": [...], "unclear_sections": []}'
        ),
        user_prompt=raw[:4000],
        max_tokens=int(getattr(settings, "SUMMARY_REPAIR_MAX_TOKENS", "900")),
    )
    return _safe_parse_json(fixed_raw)


def _parse_key_points_from_json(data: Dict) -> List[str]:
    """Láº¥y key_points tá»« JSON tÃ³m táº¯t Ä‘Ã£ parse."""
    return [str(p).strip() for p in data.get("key_points", []) if str(p).strip()]


def _parse_keywords_from_json(data: Dict) -> List[str]:
    """Láº¥y keywords tá»« JSON tÃ³m táº¯t Ä‘Ã£ parse."""
    return [str(k).strip() for k in data.get("keywords", []) if str(k).strip()]


def _summary_json_to_text(data: Dict) -> str:
    """
    Chuyá»ƒn JSON tÃ³m táº¯t thÃ nh plain text (tÆ°Æ¡ng thÃ­ch DB legacy / hiá»ƒn thá»‹ Ä‘Æ¡n giáº£n).
    """
    lines = []
    for ch in data.get("chapters", []):
        num = ch.get("chapter_number", "")
        title = ch.get("chapter_title") or ""
        header = f"ChÆ°Æ¡ng {num}" if num and str(num) != "0" else ""
        if title:
            header = f"{header}: {title}" if header else title
        if header:
            lines.append(f"## {header}")
        if ch.get("chapter_summary"):
            lines.append(ch["chapter_summary"])
        for sec in ch.get("sections", []):
            sec_num = sec.get("section_number", "")
            sec_title = sec.get("section_title") or ""
            sec_header = f"Má»¥c {sec_num}" if sec_num else ""
            if sec_title:
                sec_header = f"{sec_header}: {sec_title}" if sec_header else sec_title
            if sec_header:
                lines.append(f"### {sec_header}")
            if sec.get("section_summary"):
                lines.append(sec["section_summary"])
    if data.get("key_points"):
        lines.append("\n## CÃ¡c Ã½ chÃ­nh")
        lines.extend([f"- {p}" for p in data["key_points"]])
    if data.get("keywords"):
        lines.append("\n## Tá»« khoÃ¡")
        lines.append(", ".join(data["keywords"]))
    return "\n\n".join(lines).strip()


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Sanitize helpers
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
    """LÃ m sáº¡ch cÃ¡c trÆ°á»ng trong summary JSON."""
    cleaned = dict(data)
    # LÃ m sáº¡ch chapters
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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Coverage audit
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Storage helpers
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
        raise RuntimeError(f"KhÃ´ng lÆ°u Ä‘Æ°á»£c file JSON summary lÃªn Supabase Storage: {res}")
    return object_path


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Gemini client & chat helper
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _gemini_client() -> genai.Client:
    api_key = getattr(settings, "GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY chua duoc cau hinh.")
    return genai.Client(api_key=api_key)


def _extract_gemini_text(response) -> str:
    content = str(getattr(response, "text", "") or "").strip()
    if content:
        return content
    texts: List[str] = []
    for candidate in getattr(response, "candidates", []) or []:
        parts = getattr(getattr(candidate, "content", None), "parts", None) or []
        for part in parts:
            part_text = getattr(part, "text", None)
            if part_text:
                texts.append(str(part_text).strip())
    return "\n".join([t for t in texts if t]).strip()


def _chat(client: genai.Client, system_prompt: str, user_prompt: str, max_tokens: int) -> str:
    model = getattr(settings, "GEMINI_MODEL", "gemini-3.1-flash-lite")
    max_retries = int(getattr(settings, "GEMINI_RETRY_MAX", "3"))
    base_sleep = float(getattr(settings, "GEMINI_RETRY_BASE_SECONDS", "8"))

    last_exc = None
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.2,
                    max_output_tokens=max_tokens,
                ),
            )
            content = _extract_gemini_text(response)
            if not content:
                raise RuntimeError("Gemini tra ve noi dung rong.")
            return content
        except Exception as exc:
            last_exc = exc
            msg = str(exc).lower()
            if "rate_limit" in msg or "429" in msg or "too many" in msg or "resource_exhausted" in msg:
                if attempt < max_retries - 1:
                    time.sleep(base_sleep * (2 ** attempt))
                    continue
            raise

    if last_exc:
        raise last_exc
    raise RuntimeError("Gemini: khong co response sau retry.")


def _chat_with_document(
    client: genai.Client,
    system_prompt: str,
    user_prompt: str,
    file_bytes: bytes,
    mime_type: str,
    max_tokens: int,
) -> str:
    model = getattr(settings, "GEMINI_MODEL", "gemini-3.1-flash-lite")
    max_retries = int(getattr(settings, "GEMINI_RETRY_MAX", "3"))
    base_sleep = float(getattr(settings, "GEMINI_RETRY_BASE_SECONDS", "8"))

    last_exc = None
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model,
                contents=[
                    types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
                    user_prompt,
                ],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.2,
                    max_output_tokens=max_tokens,
                ),
            )
            content = _extract_gemini_text(response)
            if not content:
                raise RuntimeError("Gemini tra ve noi dung rong khi doc tai lieu.")
            return content
        except Exception as exc:
            last_exc = exc
            msg = str(exc).lower()
            if "rate_limit" in msg or "429" in msg or "too many" in msg or "resource_exhausted" in msg:
                if attempt < max_retries - 1:
                    time.sleep(base_sleep * (2 ** attempt))
                    continue
            raise

    if last_exc:
        raise last_exc
    raise RuntimeError("Gemini: khong co response sau retry khi doc tai lieu.")


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# PDF scan fallback â€” chia trang, extract text, tÃ³m táº¯t tá»«ng batch
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _summarize_pdf_pages_via_text(
    *,
    client: genai.Client,
    file_bytes: bytes,
    job_id: str,
    max_pages_per_chunk: int = 8,
) -> Dict:
    """
    Doc PDF bang Gemini native document input theo tung batch trang,
    sau do tong hop ve JSON cuoi cung.
    """
    reader = PdfReader(io.BytesIO(file_bytes))
    total_pages = len(reader.pages)
    if total_pages <= 0:
        raise RuntimeError("PDF khong co trang hop le.")

    page_groups: List[tuple] = []
    for start in range(0, total_pages, max_pages_per_chunk):
        end = min(start + max_pages_per_chunk, total_pages)
        page_groups.append((start, end))

    chunk_raws: List[str] = []
    total_groups = len(page_groups)

    for idx, (start, end) in enumerate(page_groups, start=1):
        writer = PdfWriter()
        for page_idx in range(start, end):
            writer.add_page(reader.pages[page_idx])

        buf = io.BytesIO()
        writer.write(buf)
        chunk_bytes = buf.getvalue()

        raw = _chat_with_document(
            client=client,
            system_prompt=CHUNK_SYSTEM_PROMPT,
            user_prompt=(
                f"[TRANG {start + 1}-{end}/{total_pages}] "
                "Doc day du cac trang PDF nay va tom tat thanh JSON theo schema. "
                "Khong bo sot bang bieu, so lieu, hinh ve, dinh nghia, heading."
            ),
            file_bytes=chunk_bytes,
            mime_type="application/pdf",
            max_tokens=int(getattr(settings, "SUMMARY_CHUNK_MAX_TOKENS", "650")),
        )
        chunk_raws.append(raw)

        progress = min(80, 20 + int((idx / total_groups) * 55))
        if idx == total_groups or idx % 2 == 0:
            supabase_client.update_summary_job(job_id, {"progress": progress})

    merged_chunks = _merge_chunk_jsons(chunk_raws)
    merged_input = _json.dumps(merged_chunks, ensure_ascii=False)

    final_raw = _chat(
        client=client,
        system_prompt=FINAL_SYSTEM_PROMPT,
        user_prompt=merged_input,
        max_tokens=int(getattr(settings, "SUMMARY_FINAL_MAX_TOKENS", "1200")),
    )
    try:
        summary_data = _safe_parse_json(final_raw)
    except Exception:
        summary_data = _fallback_summary_json_from_chunks(merged_chunks)

    try:
        _validate_summary_json(summary_data)
    except RuntimeError:
        if bool(getattr(settings, "SUMMARY_ENABLE_MODEL_REPAIR", False)):
            try:
                summary_data = _repair_summary_json(client, final_raw)
                _validate_summary_json(summary_data)
            except Exception:
                summary_data = _fallback_summary_json_from_chunks(merged_chunks)
        else:
            summary_data = _fallback_summary_json_from_chunks(merged_chunks)

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

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Main summarize pipeline â€” chunk by headings/paragraphs, retry náº¿u coverage tháº¥p
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _summarize_with_chunks_retry(
    *,
    client: genai.Client,
    text: str,
    job_id: str,
) -> Dict:
    max_chunk_chars    = int(getattr(settings, "SUMMARY_CHUNK_CHARS", 6000))
    coverage_threshold = float(getattr(settings, "SUMMARY_COVERAGE_THRESHOLD", "0.6"))

    attempt_plans = [
        {"max_chars": max_chunk_chars, "extra_prompt": ""},
        {
            "max_chars": max(3000, int(max_chunk_chars * 0.75)),
            "extra_prompt": "Táº­p trung bao phá»§ Ä‘áº§y Ä‘á»§ tá»«ng chÆ°Æ¡ng/má»¥c, khÃ´ng bá» sÃ³t.",
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
            raise RuntimeError("KhÃ´ng tÃ¡ch Ä‘Æ°á»£c chunk.")

        chunk_raws: List[str] = []
        total = len(chunks)

        for idx, chunk in enumerate(chunks, start=1):
            raw = _chat(
                client=client,
                system_prompt=CHUNK_SYSTEM_PROMPT,
                user_prompt=(
                    f"[PHáº¦N {idx}/{total}] {plan['extra_prompt']}\n\n{chunk}"
                ),
                max_tokens=int(getattr(settings, "SUMMARY_CHUNK_MAX_TOKENS", "650")),
            )
            chunk_raws.append(raw)
            progress = min(85, 20 + int((idx / total) * 55))
            if idx == total or idx % 2 == 0:
                supabase_client.update_summary_job(job_id, {"progress": progress})

        # Gá»™p cÃ¡c chunk JSON â†’ gá»i FINAL
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
            summary_data = _fallback_summary_json_from_chunks(merged_chunks)

        try:
            _validate_summary_json(summary_data)
        except RuntimeError:
            if bool(getattr(settings, "SUMMARY_ENABLE_MODEL_REPAIR", False)):
                try:
                    summary_data = _repair_summary_json(client, final_raw)
                    _validate_summary_json(summary_data)
                except Exception:
                    summary_data = _fallback_summary_json_from_chunks(merged_chunks)
            else:
                summary_data = _fallback_summary_json_from_chunks(merged_chunks)

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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Main entry point
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def process_summary_job(job_id: str) -> None:
    claimed_row, claimed_status = supabase_client.claim_summary_job(job_id)
    if claimed_status >= 400:
        raise RuntimeError("KhÃ´ng claim Ä‘Æ°á»£c job Ä‘á»ƒ xá»­ lÃ½.")
    if not claimed_row:
        return

    try:
        bucket = getattr(settings, "SUPABASE_STORAGE_BUCKET", "study-documents")

        # â”€â”€ 1. Táº£i file â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        blob, blob_status = supabase_client.download_storage_file(
            bucket=bucket,
            object_path=str(claimed_row.get("storage_path", "")),
        )
        if blob_status >= 400 or not isinstance(blob, (bytes, bytearray)):
            raise RuntimeError("KhÃ´ng táº£i Ä‘Æ°á»£c file tá»« Supabase Storage.")

        file_name  = str(claimed_row.get("file_name", ""))
        user_id    = str(claimed_row.get("id_user", ""))
        mime_type  = str(claimed_row.get("mime_type", ""))
        lower_name = file_name.lower()
        lower_mime = mime_type.lower()
        is_pdf     = lower_name.endswith(".pdf") or ("pdf" in lower_mime)

        text = ""
        max_source_chars = int(getattr(settings, "SUMMARY_MAX_SOURCE_CHARS", 120000))

        if not is_pdf:
            text = _extract_text(file_name, mime_type, bytes(blob))
            text = _cleanup_text(text)
            if not text:
                raise RuntimeError("Khong trich xuat duoc noi dung file.")
            if len(text) > max_source_chars:
                text = text[:max_source_chars]

        supabase_client.update_summary_job(job_id, {"progress": 20})

        client: genai.Client = _gemini_client()
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
            summarized = _summarize_pdf_pages_via_text(
                client=client,
                file_bytes=bytes(blob),
                job_id=job_id,
                max_pages_per_chunk=int(
                    getattr(settings, "SUMMARY_PDF_PAGES_PER_CHUNK", "12")
                ),
            )
            summary_data = summarized["summary_data"]
            final_summary_text = summarized["summary_text"]
            coverage = summarized["coverage"]
            text = summarized.get("source_text") or text
            if text and len(text) > max_source_chars:
                text = text[:max_source_chars]

        else:
            # DOCX
            _validate_source_text(text)
            summarized = _summarize_with_chunks_retry(
                client=client, text=text, job_id=job_id
            )
            summary_data       = summarized["summary_data"]
            final_summary_text = summarized["summary_text"]
            coverage           = summarized["coverage"]

        # â”€â”€ 4. Key points & keywords â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        supabase_client.update_summary_job(job_id, {"progress": 88})

        key_points: List[str] = _sanitize_key_points(
            _parse_key_points_from_json(summary_data)
        )
        keywords: List[str] = _parse_keywords_from_json(summary_data)

        # Fallback: náº¿u key_points rá»—ng â†’ gá»i KEYPOINTS_SYSTEM_PROMPT
        if not key_points and bool(getattr(settings, "SUMMARY_ENABLE_KEYPOINTS_FALLBACK", False)):
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
                # Fallback text parse náº¿u JSON lá»—i
                key_points = _sanitize_key_points(
                    [
                        re.sub(r"^[^\w\[]+\s*", "", ln.strip())
                        for ln in raw_kp.splitlines()
                        if ln.strip()
                    ]
                )

        if not key_points:
            raise RuntimeError("KhÃ´ng trÃ­ch Ä‘Æ°á»£c cÃ¡c Ã½ chÃ­nh Ä‘áº¡t yÃªu cáº§u.")

        final_summary_text = _sanitize_summary_text(final_summary_text)

        # â”€â”€ 5. LÆ°u DB â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

        # â”€â”€ 6. LÆ°u JSON file lÃªn Storage (non-blocking) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
            # KhÃ´ng fail cáº£ job náº¿u lÆ°u JSON lá»—i
            pass

    except Exception as exc:
        supabase_client.update_summary_job(
            job_id,
            {
                "status": "failed",
                "progress": 100,
                "finished_at": now_iso(),
                "error_message": str(exc)[:1000] if str(exc) else "KhÃ´ng rÃµ lá»—i.",
            },
        )



