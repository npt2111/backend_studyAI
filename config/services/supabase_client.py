import os
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import quote

import requests


class SupabaseConfigError(Exception):
    pass


def _settings() -> Tuple[str, str]:
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_KEY", "").strip()
    if not url or not key:
        raise SupabaseConfigError("SUPABASE_URL hoac SUPABASE_KEY chua duoc cau hinh.")
    return url, key


def _request(
    method: str,
    path: str,
    json: Optional[Dict[str, Any]] = None,
    extra_headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], int]:
    base_url, api_key = _settings()
    headers = {
        "apikey": api_key,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)

    try:
        response = requests.request(
            method=method,
            url=f"{base_url}{path}",
            json=json,
            headers=headers,
            timeout=20,
        )
    except requests.RequestException as exc:
        return {"message": "Khong the ket noi Supabase.", "detail": str(exc)}, 503

    try:
        payload = response.json()
    except ValueError:
        payload = {"detail": response.text}
    return payload, response.status_code


def _request_raw(
    method: str,
    path: str,
    json: Optional[Dict[str, Any]] = None,
    extra_headers: Optional[Dict[str, str]] = None,
) -> Tuple[Union[Dict[str, Any], List[Any]], int, Dict[str, str]]:
    base_url, api_key = _settings()
    headers = {
        "apikey": api_key,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)

    try:
        response = requests.request(
            method=method,
            url=f"{base_url}{path}",
            json=json,
            headers=headers,
            timeout=20,
        )
    except requests.RequestException as exc:
        return {"message": "Khong the ket noi Supabase.", "detail": str(exc)}, 503, {}

    try:
        payload = response.json()
    except ValueError:
        payload = {"detail": response.text}
    return payload, response.status_code, dict(response.headers)


def _select_one(path_query: str) -> Tuple[Dict[str, Any], int]:
    payload, status_code = _request("GET", path_query)
    if isinstance(payload, list):
        if not payload:
            return {}, 200
        return payload[0], 200
    return payload, status_code


def get_user_by_email(email: str) -> Tuple[Dict[str, Any], int]:
    encoded = quote(email.strip().lower(), safe="")
    return _select_one(
        f"/rest/v1/user?select=*&email_user=eq.{encoded}&order=created_at.desc&limit=1"
    )


def get_user_by_id(user_id: str) -> Tuple[Dict[str, Any], int]:
    encoded = quote(user_id, safe="")
    return _select_one(f"/rest/v1/user?select=*&id_user=eq.{encoded}&limit=1")


def create_user(
    *,
    full_name: str,
    email: str,
    password_value: str,
    phone: str = "",
    address: str = "",
    birthday: str = "",
) -> Tuple[Dict[str, Any], int]:
    payload: Dict[str, Any] = {
        "full_name_user": full_name,
        "email_user": email.strip().lower(),
        "password_user": password_value,
    }

    if phone:
        payload["phone_user"] = phone
    if address:
        payload["address_user"] = address
    if birthday:
        payload["birthday_user"] = birthday

    response_payload, response_status = _request(
        "POST",
        "/rest/v1/user",
        json=payload,
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else payload), response_status
    return response_payload, response_status


def update_user_profile(user_id: str, fields: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    encoded = quote(user_id, safe="")
    payload = dict(fields)

    response_payload, response_status = _request(
        "PATCH",
        f"/rest/v1/user?id_user=eq.{encoded}",
        json=payload,
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else payload), response_status
    return response_payload, response_status


def create_plan_task(
    *,
    user_id: str,
    task_name: str,
    subject: str,
    task_date: str,
    start_time: str,
    end_time: str,
    priority: str,
    status: str = "pending",
) -> Tuple[Dict[str, Any], int]:
    payload: Dict[str, Any] = {
        "id_user": user_id,
        "task_name": task_name,
        "subject": subject,
        "task_date": task_date,
        "start_time": start_time,
        "end_time": end_time,
        "priority": priority,
        "status": status,
    }

    response_payload, response_status = _request(
        "POST",
        "/rest/v1/plan_tasks",
        json=payload,
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else payload), response_status
    return response_payload, response_status


def list_plan_tasks(
    *,
    user_id: str,
    task_date: str = "",
) -> Tuple[List[Dict[str, Any]], int]:
    encoded_user = quote(user_id, safe="")
    path = f"/rest/v1/plan_tasks?select=*&id_user=eq.{encoded_user}"
    if task_date:
        encoded_date = quote(task_date, safe="")
        path += f"&task_date=eq.{encoded_date}"
    path += "&order=start_time.asc"

    response_payload, response_status = _request("GET", path)
    if isinstance(response_payload, list):
        return response_payload, response_status
    return [], response_status


def update_plan_task_status(task_id: str, status_value: str) -> Tuple[Dict[str, Any], int]:
    encoded = quote(task_id, safe="")
    response_payload, response_status = _request(
        "PATCH",
        f"/rest/v1/plan_tasks?id_task=eq.{encoded}",
        json={"status": status_value},
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else {}), response_status
    return response_payload, response_status


def update_plan_task(task_id: str, fields: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    encoded = quote(task_id, safe="")
    response_payload, response_status = _request(
        "PATCH",
        f"/rest/v1/plan_tasks?id_task=eq.{encoded}",
        json=dict(fields),
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else {}), response_status
    return response_payload, response_status


def delete_plan_task(task_id: str) -> Tuple[Dict[str, Any], int]:
    encoded = quote(task_id, safe="")
    response_payload, response_status = _request(
        "DELETE",
        f"/rest/v1/plan_tasks?id_task=eq.{encoded}",
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else {}), response_status
    return response_payload, response_status


def upsert_fcm_token(
    *,
    user_id: str,
    token: str,
    device_type: str = "android",
) -> Tuple[Dict[str, Any], int]:
    payload = {
        "id_user": user_id,
        "token": token,
        "device_type": device_type,
        "is_active": True,
        "updated_at": _now_iso(),
    }
    response_payload, response_status = _request(
        "POST",
        "/rest/v1/user_fcm_tokens?on_conflict=token",
        json=payload,
        extra_headers={"Prefer": "resolution=merge-duplicates,return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else payload), response_status
    return response_payload, response_status


def list_active_fcm_tokens(user_id: str) -> Tuple[List[Dict[str, Any]], int]:
    encoded_user = quote(user_id, safe="")
    payload, status_code = _request(
        "GET",
        f"/rest/v1/user_fcm_tokens?select=*&id_user=eq.{encoded_user}&is_active=eq.true",
    )
    if isinstance(payload, list):
        return payload, status_code
    return [], status_code


def deactivate_fcm_token(token: str) -> Tuple[Dict[str, Any], int]:
    encoded = quote(token, safe="")
    response_payload, response_status = _request(
        "PATCH",
        f"/rest/v1/user_fcm_tokens?token=eq.{encoded}",
        json={"is_active": False, "updated_at": _now_iso()},
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else {}), response_status
    return response_payload, response_status


def list_due_plan_tasks(*, minutes_window: int = 2) -> Tuple[List[Dict[str, Any]], int]:
    now_local = datetime.now(timezone(timedelta(hours=7)))
    today = now_local.date().isoformat()
    lower_time = (now_local - timedelta(minutes=minutes_window)).time().replace(microsecond=0).isoformat()
    upper_time = now_local.time().replace(microsecond=0).isoformat()
    path = (
        "/rest/v1/plan_tasks?select=*"
        f"&task_date=eq.{quote(today, safe='')}"
        "&status=eq.pending"
        "&reminder_sent_at=is.null"
        f"&start_time=gte.{quote(lower_time, safe='')}"
        f"&start_time=lte.{quote(upper_time, safe='')}"
        "&order=start_time.asc"
    )
    payload, status_code = _request("GET", path)
    if isinstance(payload, list):
        return payload, status_code
    return [], status_code


def mark_plan_task_reminder_sent(task_id: str) -> Tuple[Dict[str, Any], int]:
    encoded = quote(task_id, safe="")
    response_payload, response_status = _request(
        "PATCH",
        f"/rest/v1/plan_tasks?id_task=eq.{encoded}",
        json={"reminder_sent_at": _now_iso()},
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else {}), response_status
    return response_payload, response_status


def public_storage_url(*, bucket: str, object_path: str) -> str:
    base_url, _ = _settings()
    encoded_path = quote(object_path.lstrip("/"), safe="/")
    return f"{base_url}/storage/v1/object/public/{bucket}/{encoded_path}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _local_date_iso() -> str:
    return datetime.now(timezone(timedelta(hours=7))).date().isoformat()


def upload_storage_file(
    *,
    bucket: str,
    object_path: str,
    file_bytes: bytes,
    content_type: str = "application/octet-stream",
) -> Tuple[Dict[str, Any], int]:
    base_url, api_key = _settings()
    encoded_path = quote(object_path.lstrip("/"), safe="/")
    url = f"{base_url}/storage/v1/object/{bucket}/{encoded_path}"
    headers = {
        "apikey": api_key,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": content_type or "application/octet-stream",
        "x-upsert": "false",
    }

    try:
        response = requests.post(url=url, data=file_bytes, headers=headers, timeout=60)
    except requests.RequestException as exc:
        return {"message": "Khong the upload file len Supabase Storage.", "detail": str(exc)}, 503

    try:
        payload = response.json()
        if isinstance(payload, list):
            payload = {"data": payload}
    except ValueError:
        payload = {"detail": response.text}

    return payload, response.status_code


def download_storage_file(*, bucket: str, object_path: str) -> Tuple[Any, int]:
    base_url, api_key = _settings()
    encoded_path = quote(object_path.lstrip("/"), safe="/")
    url = f"{base_url}/storage/v1/object/{bucket}/{encoded_path}"
    headers = {
        "apikey": api_key,
        "Authorization": f"Bearer {api_key}",
    }

    try:
        response = requests.get(url=url, headers=headers, timeout=60)
    except requests.RequestException as exc:
        return {"message": "Khong the tai file tu Supabase Storage.", "detail": str(exc)}, 503

    if response.status_code >= 400:
        try:
            payload = response.json()
            if isinstance(payload, list):
                payload = {"data": payload}
        except ValueError:
            payload = {"detail": response.text}
        return payload, response.status_code

    return response.content, response.status_code


def create_document_read_result(
    *,
    user_id: str,
    file_name: str,
    storage_path: str,
    mime_type: str,
) -> Tuple[Dict[str, Any], int]:
    payload: Dict[str, Any] = {
        "id_user": user_id,
        "file_name": file_name,
        "storage_path": storage_path,
        "mime_type": mime_type,
        "status": "processing",
        "source_word_count": 0,
        "updated_at": _now_iso(),
    }

    response_payload, response_status = _request(
        "POST",
        "/rest/v1/document_read_results",
        json=payload,
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else payload), response_status
    return response_payload, response_status


def get_document_read_result(read_id: str) -> Tuple[Dict[str, Any], int]:
    encoded = quote(read_id, safe="")
    return _select_one(f"/rest/v1/document_read_results?select=*&id_read=eq.{encoded}&limit=1")


def get_document_read_result_by_storage_path(storage_path: str, user_id: str = "") -> Tuple[Dict[str, Any], int]:
    encoded_path = quote(storage_path, safe="")
    path = f"/rest/v1/document_read_results?select=*&storage_path=eq.{encoded_path}"
    if user_id:
        encoded_user = quote(user_id, safe="")
        path += f"&id_user=eq.{encoded_user}"
    path += "&order=created_at.desc&limit=1"
    return _select_one(path)


def list_document_read_results(*, user_id: str, limit: int = 20) -> Tuple[List[Dict[str, Any]], int]:
    safe_limit = max(1, min(limit, 100))
    encoded_user = quote(user_id, safe="")
    payload, status_code = _request(
        "GET",
        f"/rest/v1/document_read_results?select=*&id_user=eq.{encoded_user}&order=created_at.desc&limit={safe_limit}",
    )
    if isinstance(payload, list):
        return payload, 200
    return [], status_code


def update_document_read_result(read_id: str, fields: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    encoded = quote(read_id, safe="")
    payload = dict(fields)
    payload["updated_at"] = _now_iso()
    response_payload, response_status = _request(
        "PATCH",
        f"/rest/v1/document_read_results?id_read=eq.{encoded}",
        json=payload,
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else payload), response_status
    return response_payload, response_status


def delete_document_read_result(read_id: str) -> Tuple[Dict[str, Any], int]:
    encoded = quote(read_id, safe="")
    response_payload, response_status = _request(
        "DELETE",
        f"/rest/v1/document_read_results?id_read=eq.{encoded}",
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else {}), response_status
    return response_payload, response_status


def delete_document_chunks_by_read(read_id: str) -> Tuple[Dict[str, Any], int]:
    encoded = quote(read_id, safe="")
    response_payload, response_status = _request(
        "DELETE",
        f"/rest/v1/document_chunks?id_read=eq.{encoded}",
        extra_headers={"Prefer": "return=minimal"},
    )
    if isinstance(response_payload, list):
        return {"deleted": len(response_payload)}, response_status
    return response_payload, response_status


def create_document_chunk(
    *,
    user_id: str,
    read_id: str,
    chunk_index: int,
    content: str,
    embedding: List[float],
    token_count: int,
) -> Tuple[Dict[str, Any], int]:
    embedding_text = "[" + ",".join(str(float(value)) for value in embedding) + "]"
    payload: Dict[str, Any] = {
        "id_user": user_id,
        "id_read": read_id,
        "chunk_index": int(chunk_index),
        "content": content,
        "embedding": embedding_text,
        "token_count": max(0, int(token_count or 0)),
    }
    response_payload, response_status = _request(
        "POST",
        "/rest/v1/document_chunks",
        json=payload,
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else payload), response_status
    return response_payload, response_status


def count_document_chunks_by_read(*, user_id: str, read_id: str) -> Tuple[int, int]:
    encoded_user = quote(user_id, safe="")
    encoded_read = quote(read_id, safe="")
    payload, status_code, headers = _request_raw(
        "GET",
        "/rest/v1/document_chunks?select=id_chunk"
        f"&id_user=eq.{encoded_user}"
        f"&id_read=eq.{encoded_read}"
        "&limit=1",
        extra_headers={"Prefer": "count=exact"},
    )
    if status_code >= 400:
        return 0, status_code

    content_range = headers.get("Content-Range") or headers.get("content-range") or ""
    total_text = content_range.rsplit("/", 1)[-1].strip()
    if total_text.isdigit():
        return int(total_text), 200
    if isinstance(payload, list):
        return len(payload), 200
    return 0, status_code


def match_document_chunks(
    *,
    user_id: str,
    read_id: str,
    query_embedding: List[float],
    match_count: int = 5,
    match_threshold: float = 0.2,
) -> Tuple[List[Dict[str, Any]], int]:
    embedding_text = "[" + ",".join(str(float(value)) for value in query_embedding) + "]"
    payload: Dict[str, Any] = {
        "p_user_id": user_id,
        "p_read_id": read_id,
        "query_embedding": embedding_text,
        "match_count": max(1, min(int(match_count or 5), 20)),
        "match_threshold": float(match_threshold),
    }
    response_payload, response_status = _request(
        "POST",
        "/rest/v1/rpc/match_document_chunks",
        json=payload,
    )
    if isinstance(response_payload, list):
        return response_payload, response_status
    return [], response_status


def create_quiz_generation(
    *,
    user_id: str,
    read_id: str,
    file_name: str,
    quiz_type: str,
    difficulty: str,
    question_count: int,
) -> Tuple[Dict[str, Any], int]:
    payload: Dict[str, Any] = {
        "id_user": user_id,
        "id_read": read_id,
        "file_name": file_name,
        "quiz_type": quiz_type,
        "difficulty": difficulty,
        "question_count": question_count,
        "status": "processing",
        "questions": [],
        "updated_at": _now_iso(),
    }
    response_payload, response_status = _request(
        "POST",
        "/rest/v1/quiz_generations",
        json=payload,
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else payload), response_status
    return response_payload, response_status


def update_quiz_generation(quiz_id: str, fields: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    encoded = quote(quiz_id, safe="")
    payload = dict(fields)
    payload["updated_at"] = _now_iso()
    response_payload, response_status = _request(
        "PATCH",
        f"/rest/v1/quiz_generations?id_quiz=eq.{encoded}",
        json=payload,
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else payload), response_status
    return response_payload, response_status


def get_quiz_generation(quiz_id: str) -> Tuple[Dict[str, Any], int]:
    encoded = quote(quiz_id, safe="")
    return _select_one(f"/rest/v1/quiz_generations?select=*&id_quiz=eq.{encoded}&limit=1")


def list_quiz_generations(*, user_id: str, limit: int = 20) -> Tuple[List[Dict[str, Any]], int]:
    safe_limit = max(1, min(limit, 100))
    encoded_user = quote(user_id, safe="")
    payload, status_code = _request(
        "GET",
        f"/rest/v1/quiz_generations?select=*&id_user=eq.{encoded_user}&order=created_at.desc&limit={safe_limit}",
    )
    own_rows = payload if isinstance(payload, list) else []
    saved_rows, saved_status = list_saved_quizzes(user_id=user_id, limit=safe_limit)
    if status_code >= 400:
        return [], status_code
    if saved_status >= 400:
        saved_rows = []
    rows: List[Dict[str, Any]] = []
    seen = set()
    for row in own_rows + saved_rows:
        quiz_id = str(row.get("id_quiz") or "")
        if not quiz_id or quiz_id in seen:
            continue
        seen.add(quiz_id)
        latest_attempt, attempt_status = get_latest_quiz_attempt(user_id=user_id, quiz_id=quiz_id)
        if attempt_status < 400 and latest_attempt:
            row["latest_attempt"] = latest_attempt
        rows.append(row)
    rows.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return rows[:safe_limit], 200


def get_latest_quiz_attempt(*, user_id: str, quiz_id: str) -> Tuple[Dict[str, Any], int]:
    encoded_user = quote(user_id, safe="")
    encoded_quiz = quote(quiz_id, safe="")
    return _select_one(
        "/rest/v1/quiz_attempts?select=*"
        f"&id_user=eq.{encoded_user}"
        f"&id_quiz=eq.{encoded_quiz}"
        "&order=updated_at.desc"
        "&limit=1"
    )


def create_quiz_attempt(
    *,
    user_id: str,
    quiz_id: str,
    read_id: str,
    total_questions: int,
) -> Tuple[Dict[str, Any], int]:
    payload: Dict[str, Any] = {
        "id_user": user_id,
        "id_quiz": quiz_id,
        "id_read": read_id or None,
        "status": "in_progress",
        "answers": [],
        "correct_count": 0,
        "wrong_count": 0,
        "total_questions": total_questions,
        "completion_percent": 0,
        "elapsed_seconds": 0,
        "updated_at": _now_iso(),
    }
    response_payload, response_status = _request(
        "POST",
        "/rest/v1/quiz_attempts",
        json=payload,
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else payload), response_status
    return response_payload, response_status


def get_quiz_attempt(attempt_id: str) -> Tuple[Dict[str, Any], int]:
    encoded = quote(attempt_id, safe="")
    return _select_one(f"/rest/v1/quiz_attempts?select=*&id_attempt=eq.{encoded}&limit=1")


def update_quiz_attempt(attempt_id: str, fields: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    encoded = quote(attempt_id, safe="")
    payload = dict(fields)
    payload["updated_at"] = _now_iso()
    response_payload, response_status = _request(
        "PATCH",
        f"/rest/v1/quiz_attempts?id_attempt=eq.{encoded}",
        json=payload,
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else payload), response_status
    return response_payload, response_status


def delete_quiz_attempt(attempt_id: str) -> Tuple[Dict[str, Any], int]:
    encoded = quote(attempt_id, safe="")
    response_payload, response_status = _request(
        "DELETE",
        f"/rest/v1/quiz_attempts?id_attempt=eq.{encoded}",
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else {}), response_status
    return response_payload, response_status


def delete_quiz_attempts_by_quiz(*, user_id: str, quiz_id: str) -> Tuple[List[Dict[str, Any]], int]:
    encoded_user = quote(user_id, safe="")
    encoded_quiz = quote(quiz_id, safe="")
    response_payload, response_status = _request(
        "DELETE",
        f"/rest/v1/quiz_attempts?id_user=eq.{encoded_user}&id_quiz=eq.{encoded_quiz}",
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return response_payload, response_status
    return [], response_status


def delete_quiz_generation(quiz_id: str) -> Tuple[Dict[str, Any], int]:
    encoded = quote(quiz_id, safe="")
    response_payload, response_status = _request(
        "DELETE",
        f"/rest/v1/quiz_generations?id_quiz=eq.{encoded}",
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else {}), response_status
    return response_payload, response_status


def _random_share_code(length: int = 9, prefix: str = "") -> str:
    alphabet = string.ascii_lowercase + string.digits
    body_length = max(1, length - len(prefix))
    return f"{prefix}{''.join(secrets.choice(alphabet) for _ in range(body_length))}"


def get_quiz_share_by_quiz(quiz_id: str) -> Tuple[Dict[str, Any], int]:
    encoded = quote(quiz_id, safe="")
    return _select_one(f"/rest/v1/quiz_shares?select=*&id_quiz=eq.{encoded}&limit=1")


def get_quiz_share_by_code(share_code: str) -> Tuple[Dict[str, Any], int]:
    encoded = quote(share_code.strip().lower(), safe="")
    return _select_one(f"/rest/v1/quiz_shares?select=*&share_code=eq.{encoded}&limit=1")


def create_quiz_share(*, quiz_id: str, user_id: str) -> Tuple[Dict[str, Any], int]:
    existing, existing_status = get_quiz_share_by_quiz(quiz_id)
    if existing_status < 400 and existing:
        return existing, 200

    for _ in range(6):
        share_code = _random_share_code(prefix="q")
        flashcard_share, flashcard_status = get_flashcard_share_by_code(share_code)
        if flashcard_status < 400 and flashcard_share:
            continue
        payload = {
            "id_quiz": quiz_id,
            "id_user": user_id,
            "share_code": share_code,
        }
        response_payload, response_status = _request(
            "POST",
            "/rest/v1/quiz_shares",
            json=payload,
            extra_headers={"Prefer": "return=representation"},
        )
        if isinstance(response_payload, list):
            return (response_payload[0] if response_payload else payload), response_status
        if response_status != 409:
            return response_payload, response_status
    return {"message": "Khong tao duoc share_code duy nhat."}, 409


def is_quiz_saved(*, user_id: str, quiz_id: str) -> bool:
    encoded_user = quote(user_id, safe="")
    encoded_quiz = quote(quiz_id, safe="")
    row, status_code = _select_one(
        f"/rest/v1/quiz_saved?select=*&id_user=eq.{encoded_user}&id_quiz=eq.{encoded_quiz}&limit=1"
    )
    return status_code < 400 and bool(row)


def save_shared_quiz(*, user_id: str, quiz_id: str, share_code: str) -> Tuple[Dict[str, Any], int]:
    existing_user = quote(user_id, safe="")
    existing_quiz = quote(quiz_id, safe="")
    existing, existing_status = _select_one(
        f"/rest/v1/quiz_saved?select=*&id_user=eq.{existing_user}&id_quiz=eq.{existing_quiz}&limit=1"
    )
    if existing_status < 400 and existing:
        return existing, 200
    payload = {
        "id_user": user_id,
        "id_quiz": quiz_id,
        "share_code": share_code,
    }
    response_payload, response_status = _request(
        "POST",
        "/rest/v1/quiz_saved",
        json=payload,
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else payload), response_status
    return response_payload, response_status


def list_saved_quizzes(*, user_id: str, limit: int = 20) -> Tuple[List[Dict[str, Any]], int]:
    safe_limit = max(1, min(limit, 100))
    encoded_user = quote(user_id, safe="")
    saved_payload, saved_status = _request(
        "GET",
        f"/rest/v1/quiz_saved?select=*&id_user=eq.{encoded_user}&order=created_at.desc&limit={safe_limit}",
    )
    if not isinstance(saved_payload, list):
        return [], saved_status
    rows: List[Dict[str, Any]] = []
    for saved in saved_payload:
        quiz_id = str(saved.get("id_quiz") or "")
        if not quiz_id:
            continue
        quiz_row, quiz_status = get_quiz_generation(quiz_id)
        if quiz_status < 400 and quiz_row:
            rows.append(quiz_row)
    return rows, 200


def delete_quiz_saved_by_quiz(quiz_id: str) -> Tuple[List[Dict[str, Any]], int]:
    encoded = quote(quiz_id, safe="")
    response_payload, response_status = _request(
        "DELETE",
        f"/rest/v1/quiz_saved?id_quiz=eq.{encoded}",
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return response_payload, response_status
    return [], response_status


def delete_quiz_share_by_quiz(quiz_id: str) -> Tuple[List[Dict[str, Any]], int]:
    encoded = quote(quiz_id, safe="")
    response_payload, response_status = _request(
        "DELETE",
        f"/rest/v1/quiz_shares?id_quiz=eq.{encoded}",
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return response_payload, response_status
    return [], response_status


def create_flashcard_generation(
    *,
    user_id: str,
    read_id: str,
    file_name: str,
    difficulty: str,
    card_count: int,
) -> Tuple[Dict[str, Any], int]:
    payload: Dict[str, Any] = {
        "id_user": user_id,
        "id_read": read_id,
        "file_name": file_name,
        "difficulty": difficulty,
        "card_count": card_count,
        "status": "processing",
        "cards": [],
        "updated_at": _now_iso(),
    }
    response_payload, response_status = _request(
        "POST",
        "/rest/v1/flashcard_generations",
        json=payload,
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else payload), response_status
    return response_payload, response_status


def update_flashcard_generation(flashcard_id: str, fields: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    encoded = quote(flashcard_id, safe="")
    payload = dict(fields)
    payload["updated_at"] = _now_iso()
    response_payload, response_status = _request(
        "PATCH",
        f"/rest/v1/flashcard_generations?id_flashcard=eq.{encoded}",
        json=payload,
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else payload), response_status
    return response_payload, response_status


def get_flashcard_generation(flashcard_id: str) -> Tuple[Dict[str, Any], int]:
    encoded = quote(flashcard_id, safe="")
    return _select_one(f"/rest/v1/flashcard_generations?select=*&id_flashcard=eq.{encoded}&limit=1")


def list_flashcard_generations(*, user_id: str, limit: int = 20) -> Tuple[List[Dict[str, Any]], int]:
    safe_limit = max(1, min(limit, 100))
    encoded_user = quote(user_id, safe="")
    payload, status_code = _request(
        "GET",
        f"/rest/v1/flashcard_generations?select=*&id_user=eq.{encoded_user}&order=created_at.desc&limit={safe_limit}",
    )
    own_rows = payload if isinstance(payload, list) else []
    saved_rows, saved_status = list_saved_flashcards(user_id=user_id, limit=safe_limit)
    if status_code >= 400:
        return [], status_code
    if saved_status >= 400:
        saved_rows = []
    rows: List[Dict[str, Any]] = []
    seen = set()
    for row in own_rows + saved_rows:
        flashcard_id = str(row.get("id_flashcard") or "")
        if not flashcard_id or flashcard_id in seen:
            continue
        seen.add(flashcard_id)
        latest_attempt, attempt_status = get_latest_flashcard_attempt(user_id=user_id, flashcard_id=flashcard_id)
        if attempt_status < 400 and latest_attempt:
            row["latest_attempt"] = latest_attempt
        rows.append(row)
    rows.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return rows[:safe_limit], 200


def get_latest_flashcard_attempt(*, user_id: str, flashcard_id: str) -> Tuple[Dict[str, Any], int]:
    encoded_user = quote(user_id, safe="")
    encoded_flashcard = quote(flashcard_id, safe="")
    return _select_one(
        "/rest/v1/flashcard_attempts?select=*"
        f"&id_user=eq.{encoded_user}"
        f"&id_flashcard=eq.{encoded_flashcard}"
        "&order=updated_at.desc"
        "&limit=1"
    )


def delete_flashcard_attempts_by_flashcard(*, user_id: str, flashcard_id: str) -> Tuple[List[Dict[str, Any]], int]:
    encoded_user = quote(user_id, safe="")
    encoded_flashcard = quote(flashcard_id, safe="")
    response_payload, response_status = _request(
        "DELETE",
        f"/rest/v1/flashcard_attempts?id_user=eq.{encoded_user}&id_flashcard=eq.{encoded_flashcard}",
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return response_payload, response_status
    return [], response_status


def delete_flashcard_generation(flashcard_id: str) -> Tuple[Dict[str, Any], int]:
    encoded = quote(flashcard_id, safe="")
    response_payload, response_status = _request(
        "DELETE",
        f"/rest/v1/flashcard_generations?id_flashcard=eq.{encoded}",
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else {}), response_status
    return response_payload, response_status


def get_flashcard_share_by_flashcard(flashcard_id: str) -> Tuple[Dict[str, Any], int]:
    encoded = quote(flashcard_id, safe="")
    return _select_one(f"/rest/v1/flashcard_shares?select=*&id_flashcard=eq.{encoded}&limit=1")


def get_flashcard_share_by_code(share_code: str) -> Tuple[Dict[str, Any], int]:
    encoded = quote(share_code.strip().lower(), safe="")
    return _select_one(f"/rest/v1/flashcard_shares?select=*&share_code=eq.{encoded}&limit=1")


def create_flashcard_share(*, flashcard_id: str, user_id: str) -> Tuple[Dict[str, Any], int]:
    existing, existing_status = get_flashcard_share_by_flashcard(flashcard_id)
    if existing_status < 400 and existing:
        return existing, 200

    for _ in range(6):
        share_code = _random_share_code(prefix="f")
        quiz_share, quiz_status = get_quiz_share_by_code(share_code)
        if quiz_status < 400 and quiz_share:
            continue
        payload = {
            "id_flashcard": flashcard_id,
            "id_user": user_id,
            "share_code": share_code,
        }
        response_payload, response_status = _request(
            "POST",
            "/rest/v1/flashcard_shares",
            json=payload,
            extra_headers={"Prefer": "return=representation"},
        )
        if isinstance(response_payload, list):
            return (response_payload[0] if response_payload else payload), response_status
        if response_status != 409:
            return response_payload, response_status
    return {"message": "Khong tao duoc share_code duy nhat."}, 409


def is_flashcard_saved(*, user_id: str, flashcard_id: str) -> bool:
    encoded_user = quote(user_id, safe="")
    encoded_flashcard = quote(flashcard_id, safe="")
    row, status_code = _select_one(
        f"/rest/v1/flashcard_saved?select=*&id_user=eq.{encoded_user}&id_flashcard=eq.{encoded_flashcard}&limit=1"
    )
    return status_code < 400 and bool(row)


def save_shared_flashcard(*, user_id: str, flashcard_id: str, share_code: str) -> Tuple[Dict[str, Any], int]:
    encoded_user = quote(user_id, safe="")
    encoded_flashcard = quote(flashcard_id, safe="")
    existing, existing_status = _select_one(
        f"/rest/v1/flashcard_saved?select=*&id_user=eq.{encoded_user}&id_flashcard=eq.{encoded_flashcard}&limit=1"
    )
    if existing_status < 400 and existing:
        return existing, 200
    payload = {
        "id_user": user_id,
        "id_flashcard": flashcard_id,
        "share_code": share_code,
    }
    response_payload, response_status = _request(
        "POST",
        "/rest/v1/flashcard_saved",
        json=payload,
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else payload), response_status
    return response_payload, response_status


def list_saved_flashcards(*, user_id: str, limit: int = 20) -> Tuple[List[Dict[str, Any]], int]:
    safe_limit = max(1, min(limit, 100))
    encoded_user = quote(user_id, safe="")
    saved_payload, saved_status = _request(
        "GET",
        f"/rest/v1/flashcard_saved?select=*&id_user=eq.{encoded_user}&order=created_at.desc&limit={safe_limit}",
    )
    if not isinstance(saved_payload, list):
        return [], saved_status
    rows: List[Dict[str, Any]] = []
    for saved in saved_payload:
        flashcard_id = str(saved.get("id_flashcard") or "")
        if not flashcard_id:
            continue
        flashcard_row, flashcard_status = get_flashcard_generation(flashcard_id)
        if flashcard_status < 400 and flashcard_row:
            rows.append(flashcard_row)
    return rows, 200


def delete_flashcard_share_by_flashcard(flashcard_id: str) -> Tuple[List[Dict[str, Any]], int]:
    encoded = quote(flashcard_id, safe="")
    response_payload, response_status = _request(
        "DELETE",
        f"/rest/v1/flashcard_shares?id_flashcard=eq.{encoded}",
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return response_payload, response_status
    return [], response_status


def delete_flashcard_saved_by_flashcard(flashcard_id: str) -> Tuple[List[Dict[str, Any]], int]:
    encoded = quote(flashcard_id, safe="")
    response_payload, response_status = _request(
        "DELETE",
        f"/rest/v1/flashcard_saved?id_flashcard=eq.{encoded}",
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return response_payload, response_status
    return [], response_status


def create_flashcard_attempt(
    *,
    user_id: str,
    flashcard_id: str,
    read_id: str,
    total_cards: int,
) -> Tuple[Dict[str, Any], int]:
    payload: Dict[str, Any] = {
        "id_user": user_id,
        "id_flashcard": flashcard_id,
        "id_read": read_id or None,
        "status": "in_progress",
        "viewed_count": 1 if total_cards > 0 else 0,
        "total_cards": total_cards,
        "current_index": 0,
        "completion_percent": round((1 / max(total_cards, 1)) * 100, 2) if total_cards > 0 else 0,
        "elapsed_seconds": 0,
        "updated_at": _now_iso(),
    }
    response_payload, response_status = _request(
        "POST",
        "/rest/v1/flashcard_attempts",
        json=payload,
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else payload), response_status
    return response_payload, response_status


def get_flashcard_attempt(attempt_id: str) -> Tuple[Dict[str, Any], int]:
    encoded = quote(attempt_id, safe="")
    return _select_one(f"/rest/v1/flashcard_attempts?select=*&id_attempt=eq.{encoded}&limit=1")


def update_flashcard_attempt(attempt_id: str, fields: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    encoded = quote(attempt_id, safe="")
    payload = dict(fields)
    payload["updated_at"] = _now_iso()
    response_payload, response_status = _request(
        "PATCH",
        f"/rest/v1/flashcard_attempts?id_attempt=eq.{encoded}",
        json=payload,
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else payload), response_status
    return response_payload, response_status


def get_mindmap_by_read_id(read_id: str) -> Tuple[Dict[str, Any], int]:
    encoded = quote(read_id, safe="")
    return _select_one(f"/rest/v1/mindmaps?select=*&id_read=eq.{encoded}&limit=1")


def create_mindmap(
    *,
    user_id: str,
    read_id: str,
    file_name: str,
) -> Tuple[Dict[str, Any], int]:
    payload: Dict[str, Any] = {
        "id_user": user_id,
        "id_read": read_id,
        "file_name": file_name,
        "status": "processing",
        "mindmap_json": {},
        "markdown": None,
        "updated_at": _now_iso(),
    }
    response_payload, response_status = _request(
        "POST",
        "/rest/v1/mindmaps",
        json=payload,
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else payload), response_status
    return response_payload, response_status


def update_mindmap(mindmap_id: str, fields: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    encoded = quote(mindmap_id, safe="")
    payload = dict(fields)
    payload["updated_at"] = _now_iso()
    response_payload, response_status = _request(
        "PATCH",
        f"/rest/v1/mindmaps?id_mindmap=eq.{encoded}",
        json=payload,
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else payload), response_status
    return response_payload, response_status


def get_document_chat_session_by_read(*, user_id: str, read_id: str) -> Tuple[Dict[str, Any], int]:
    encoded_user = quote(user_id, safe="")
    encoded_read = quote(read_id, safe="")
    return _select_one(
        f"/rest/v1/document_chat_sessions?select=*&id_user=eq.{encoded_user}&id_read=eq.{encoded_read}&order=updated_at.desc&limit=1"
    )


def get_document_chat_session(session_id: str) -> Tuple[Dict[str, Any], int]:
    encoded = quote(session_id, safe="")
    return _select_one(f"/rest/v1/document_chat_sessions?select=*&id_chat_session=eq.{encoded}&limit=1")


def create_document_chat_session(
    *,
    user_id: str,
    read_id: str,
    file_name: str,
) -> Tuple[Dict[str, Any], int]:
    payload: Dict[str, Any] = {
        "id_user": user_id,
        "id_read": read_id,
        "file_name": file_name,
        "updated_at": _now_iso(),
    }
    response_payload, response_status = _request(
        "POST",
        "/rest/v1/document_chat_sessions",
        json=payload,
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else payload), response_status
    return response_payload, response_status


def touch_document_chat_session(session_id: str) -> Tuple[Dict[str, Any], int]:
    encoded = quote(session_id, safe="")
    response_payload, response_status = _request(
        "PATCH",
        f"/rest/v1/document_chat_sessions?id_chat_session=eq.{encoded}",
        json={"updated_at": _now_iso()},
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else {}), response_status
    return response_payload, response_status


def list_document_chat_messages(*, session_id: str, limit: int = 100) -> Tuple[List[Dict[str, Any]], int]:
    safe_limit = max(1, min(limit, 200))
    encoded = quote(session_id, safe="")
    payload, status_code = _request(
        "GET",
        f"/rest/v1/document_chat_messages?select=*&id_chat_session=eq.{encoded}&order=created_at.asc&limit={safe_limit}",
    )
    if isinstance(payload, list):
        return payload, 200
    return [], status_code


def create_document_chat_message(
    *,
    session_id: str,
    user_id: str,
    read_id: str,
    role: str,
    content: str,
) -> Tuple[Dict[str, Any], int]:
    payload: Dict[str, Any] = {
        "id_chat_session": session_id,
        "id_user": user_id,
        "id_read": read_id,
        "role": role,
        "content": content,
    }
    response_payload, response_status = _request(
        "POST",
        "/rest/v1/document_chat_messages",
        json=payload,
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else payload), response_status
    return response_payload, response_status


def create_study_activity(
    *,
    user_id: str,
    activity_type: str,
    title: str,
    description: str = "",
    duration_seconds: int = 0,
    read_id: str = "",
    source_id: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    activity_date: str = "",
) -> Tuple[Dict[str, Any], int]:
    payload: Dict[str, Any] = {
        "id_user": user_id,
        "activity_type": activity_type,
        "title": title,
        "description": description,
        "duration_seconds": max(0, int(duration_seconds or 0)),
        "metadata": metadata or {},
    }
    if read_id:
        payload["id_read"] = read_id
    if source_id:
        payload["source_id"] = source_id
    if activity_date:
        payload["activity_date"] = activity_date
    else:
        payload["activity_date"] = _local_date_iso()

    response_payload, response_status = _request(
        "POST",
        "/rest/v1/study_activities",
        json=payload,
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else payload), response_status
    return response_payload, response_status


def list_study_activities(
    *,
    user_id: str,
    start_date: str = "",
    end_date: str = "",
    limit: int = 100,
) -> Tuple[List[Dict[str, Any]], int]:
    safe_limit = max(1, min(limit, 500))
    encoded_user = quote(user_id, safe="")
    path = f"/rest/v1/study_activities?select=*&id_user=eq.{encoded_user}"
    if start_date:
        path += f"&activity_date=gte.{quote(start_date, safe='')}"
    if end_date:
        path += f"&activity_date=lte.{quote(end_date, safe='')}"
    path += f"&order=created_at.desc&limit={safe_limit}"
    payload, status_code = _request("GET", path)
    if isinstance(payload, list):
        return payload, 200
    return [], status_code


def count_document_read_results(*, user_id: str) -> Tuple[int, int]:
    encoded_user = quote(user_id, safe="")
    payload, status_code, headers = _request_raw(
        "GET",
        f"/rest/v1/document_read_results?select=id_read&id_user=eq.{encoded_user}&limit=1",
        extra_headers={"Prefer": "count=exact"},
    )
    if status_code >= 400:
        return 0, status_code

    content_range = headers.get("Content-Range") or headers.get("content-range") or ""
    total_text = content_range.rsplit("/", 1)[-1].strip()
    if total_text.isdigit():
        return int(total_text), 200
    if isinstance(payload, list):
        return len(payload), 200
    return 0, status_code


def get_weekly_goal(*, user_id: str, week_start_date: str) -> Tuple[Dict[str, Any], int]:
    encoded_user = quote(user_id, safe="")
    encoded_week = quote(week_start_date, safe="")
    return _select_one(
        f"/rest/v1/weekly_goals?select=*&id_user=eq.{encoded_user}&week_start_date=eq.{encoded_week}&limit=1"
    )


def create_weekly_goal(
    *,
    user_id: str,
    week_start_date: str,
    goal_hours: float = 20,
) -> Tuple[Dict[str, Any], int]:
    payload: Dict[str, Any] = {
        "id_user": user_id,
        "week_start_date": week_start_date,
        "goal_hours": goal_hours,
        "updated_at": _now_iso(),
    }
    response_payload, response_status = _request(
        "POST",
        "/rest/v1/weekly_goals",
        json=payload,
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else payload), response_status
    return response_payload, response_status


def get_daily_checkin(*, user_id: str, checkin_date: str) -> Tuple[Dict[str, Any], int]:
    encoded_user = quote(user_id, safe="")
    encoded_date = quote(checkin_date, safe="")
    return _select_one(
        f"/rest/v1/daily_checkins?select=*&id_user=eq.{encoded_user}&checkin_date=eq.{encoded_date}&limit=1"
    )


def create_daily_checkin(*, user_id: str, checkin_date: str) -> Tuple[Dict[str, Any], int]:
    payload = {"id_user": user_id, "checkin_date": checkin_date}
    response_payload, response_status = _request(
        "POST",
        "/rest/v1/daily_checkins",
        json=payload,
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else payload), response_status
    return response_payload, response_status


def list_daily_checkins(
    *,
    user_id: str,
    start_date: str = "",
    end_date: str = "",
    limit: int = 370,
) -> Tuple[List[Dict[str, Any]], int]:
    safe_limit = max(1, min(limit, 1000))
    encoded_user = quote(user_id, safe="")
    path = f"/rest/v1/daily_checkins?select=*&id_user=eq.{encoded_user}"
    if start_date:
        path += f"&checkin_date=gte.{quote(start_date, safe='')}"
    if end_date:
        path += f"&checkin_date=lte.{quote(end_date, safe='')}"
    path += f"&order=checkin_date.desc&limit={safe_limit}"
    payload, status_code = _request("GET", path)
    if isinstance(payload, list):
        return payload, 200
    return [], status_code
