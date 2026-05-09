import io
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from django.conf import settings
from docx import Document
from google import genai
from google.genai import types
from pypdf import PdfReader

from config.services import supabase_client

CHUNK_SYSTEM_PROMPT = """
Ban la tro ly tom tat hoc thuat tieng Viet.

Muc tieu:
- Tom tat DAY DU y chinh cua tai lieu dai.
- TUYET DOI khong suy dien, khong them kien thuc ngoai van ban nguon.

Quy tac bat buoc:
1) Chi dung thong tin xuat hien trong van ban dau vao.
2) Khong phong doan phan bi thieu.
3) Neu doan nao khong du du lieu, ghi ro: [THIEU_DU_LIEU].
4) Giu nguyen thuat ngu quan trong, ten chuong/muc neu co.
5) Khong viet mo dau xa giao.

Dinh dang dau ra:
## TOM_TAT_THEO_MUC
- Muc/Chuong 1: ...
- Muc/Chuong 2: ...
- ...

## CAC_Y_CHINH_KHONG_BO_SOT
- 10-20 gach dau dong (tuy do dai tai lieu), moi y 1-2 cau.
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
2) Neu co noi dung mo ho/khuyet, ghi [THIEU_DU_LIEU] o muc NOI_DUNG_CHUA_RO.
3) Khong viet mo dau xa giao.

Dinh dang dau ra:
## TOM_TAT_THEO_MUC
- Muc/Chuong 1: ...
- Muc/Chuong 2: ...
- ...

## CAC_Y_CHINH_KHONG_BO_SOT
- 10-20 gach dau dong, moi y 1-2 cau, bam sat nguon.

## NOI_DUNG_CHUA_RO
- Liet ke cac phan bi thieu/ngan/quet loi, neu co.
""".strip()

KEYPOINTS_SYSTEM_PROMPT = """
Trich cac y chinh quan trong nhat tu tom tat dau vao.
Quy tac:
- Chi dung thong tin co trong dau vao.
- Khong suy dien, khong them thong tin moi.
- Moi dong bat dau bang '- '.
- Tra ve 10-20 dong.
Neu khong du du lieu thi tra ve: [THIEU_DU_LIEU]
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
        "key_points": key_points,
        "error": row.get("error_message"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _cleanup_text(raw_text: str) -> str:
    text = unicodedata.normalize("NFKC", raw_text or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00ad", "")
    text = text.replace("\ufeff", "")
    text = re.sub(r"[^\S\n]+", " ", text)
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


def _gemini_client() -> genai.Client:
    api_key = getattr(settings, "GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY chua duoc cau hinh.")
    return genai.Client(api_key=api_key)


def _chat(client: genai.Client, system_prompt: str, user_prompt: str, max_tokens: int) -> str:
    model = getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash")
    response = client.models.generate_content(
        model=model,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.2,
            max_output_tokens=max_tokens,
        ),
    )

    content = str(getattr(response, "text", "") or "").strip()
    if not content:
        texts: List[str] = []
        for candidate in getattr(response, "candidates", []) or []:
            parts = getattr(getattr(candidate, "content", None), "parts", None) or []
            for part in parts:
                part_text = getattr(part, "text", None)
                if part_text:
                    texts.append(str(part_text).strip())
        content = "\n".join([t for t in texts if t]).strip()

    if not content:
        raise RuntimeError("Gemini tra ve noi dung rong.")
    return content


def _chat_with_binary_document(
    client: genai.Client,
    system_prompt: str,
    user_prompt: str,
    file_bytes: bytes,
    mime_type: str,
    max_tokens: int,
) -> str:
    model = getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash")
    # Dung payload don gian de tuong thich nhieu phien ban google-genai.
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

    content = str(getattr(response, "text", "") or "").strip()
    if not content:
        texts: List[str] = []
        for candidate in getattr(response, "candidates", []) or []:
            parts = getattr(getattr(candidate, "content", None), "parts", None) or []
            for part in parts:
                part_text = getattr(part, "text", None)
                if part_text:
                    texts.append(str(part_text).strip())
        content = "\n".join([t for t in texts if t]).strip()

    if not content:
        raise RuntimeError("Gemini tra ve noi dung rong khi doc truc tiep tai lieu.")
    return content


def _validate_summary_output(output: str) -> None:
    lowered = output.lower()
    banned_phrases = [
        "tuyet voi",
        "ban da co mot khoi dau rat tot",
        "phan noi dung chinh cua tom tat van chua duoc cung cap",
    ]
    if any(phrase in lowered for phrase in banned_phrases):
        raise RuntimeError("Tom tat khong dat chat luong (phan hoi chung chung).")
    if "## tom_tat_theo_muc" not in lowered or "## cac_y_chinh_khong_bo_sot" not in lowered:
        raise RuntimeError("Tom tat khong dung dinh dang bat buoc.")


def _parse_key_points(raw: str) -> List[str]:
    lines = []
    for line in raw.splitlines():
        cleaned = re.sub(r"^[^\w\[]+\s*", "", line.strip())
        if cleaned:
            lines.append(cleaned)
    return lines[:20]


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

        max_chunk_chars = int(getattr(settings, "SUMMARY_CHUNK_CHARS", 6000))
        chunks = _chunk_text(text, max_chars=max_chunk_chars)
        if not chunks:
            raise RuntimeError("Khong tach duoc chunk.")

        client = _gemini_client()

        # PDF thuong loi text extraction (scan/font), uu tien doc truc tiep bang Gemini.
        if is_pdf:
            supabase_client.update_summary_job(job_id, {"progress": 45})
            try:
                final_summary = _chat_with_binary_document(
                    client=client,
                    system_prompt=FINAL_SYSTEM_PROMPT,
                    user_prompt=(
                        "Doc TOAN BO file PDF dinh kem va tom tat day du theo dung dinh dang yeu cau. "
                        "Khong suy dien, khong bo sot y chinh."
                    ),
                    file_bytes=bytes(blob),
                    mime_type="application/pdf",
                    max_tokens=1800,
                )
            except Exception:
                # Fallback ve luong text extraction neu server/model khong ho tro doc binary PDF.
                _validate_source_text(text)
                part_summaries: List[str] = []
                total = len(chunks)
                for idx, chunk in enumerate(chunks, start=1):
                    part = _chat(
                        client=client,
                        system_prompt=CHUNK_SYSTEM_PROMPT,
                        user_prompt=f"[PHAN {idx}/{total}]\n\n{chunk}",
                        max_tokens=900,
                    )
                    part_summaries.append(part)
                    progress = min(85, 20 + int((idx / total) * 55))
                    supabase_client.update_summary_job(job_id, {"progress": progress})
                merged = "\n\n".join(part_summaries)
                final_summary = _chat(
                    client=client,
                    system_prompt=FINAL_SYSTEM_PROMPT,
                    user_prompt=merged,
                    max_tokens=1200,
                )
            _validate_summary_output(final_summary)

            supabase_client.update_summary_job(job_id, {"progress": 80})
            raw_points = _chat(
                client=client,
                system_prompt=KEYPOINTS_SYSTEM_PROMPT,
                user_prompt=final_summary,
                max_tokens=700,
            )
            key_points = _parse_key_points(raw_points)
            if not key_points:
                raise RuntimeError("Khong trich duoc cac y chinh dat yeu cau.")

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
            return

        _validate_source_text(text)
        part_summaries: List[str] = []

        total = len(chunks)
        for idx, chunk in enumerate(chunks, start=1):
            part = _chat(
                client=client,
                system_prompt=CHUNK_SYSTEM_PROMPT,
                user_prompt=f"[PHAN {idx}/{total}]\n\n{chunk}",
                max_tokens=900,
            )
            part_summaries.append(part)
            progress = min(85, 20 + int((idx / total) * 55))
            supabase_client.update_summary_job(job_id, {"progress": progress})

        merged = "\n\n".join(part_summaries)

        final_summary = _chat(
            client=client,
            system_prompt=FINAL_SYSTEM_PROMPT,
            user_prompt=merged,
            max_tokens=1200,
        )
        _validate_summary_output(final_summary)

        raw_points = _chat(
            client=client,
            system_prompt=KEYPOINTS_SYSTEM_PROMPT,
            user_prompt=final_summary,
            max_tokens=700,
        )
        key_points = _parse_key_points(raw_points)
        if not key_points:
            raise RuntimeError("Khong trich duoc cac y chinh dat yeu cau.")

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


