import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def create_summary_job(
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
        "status": "queued",
        "progress": 0,
        "updated_at": _now_iso(),
    }

    response_payload, response_status = _request(
        "POST",
        "/rest/v1/ai_summary_jobs",
        json=payload,
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else payload), response_status
    return response_payload, response_status


def get_summary_job(job_id: str) -> Tuple[Dict[str, Any], int]:
    encoded = quote(job_id, safe="")
    return _select_one(f"/rest/v1/ai_summary_jobs?select=*&id_job=eq.{encoded}&limit=1")


def list_summary_jobs(*, user_id: str, limit: int = 20) -> Tuple[List[Dict[str, Any]], int]:
    safe_limit = max(1, min(limit, 100))
    encoded_user = quote(user_id, safe="")
    payload, status_code = _request(
        "GET",
        f"/rest/v1/ai_summary_jobs?select=*&id_user=eq.{encoded_user}&order=created_at.desc&limit={safe_limit}",
    )
    if isinstance(payload, list):
        return payload, 200
    return [], status_code


def list_queued_summary_jobs(*, limit: int = 10) -> Tuple[List[Dict[str, Any]], int]:
    safe_limit = max(1, min(limit, 100))
    payload, status_code = _request(
        "GET",
        f"/rest/v1/ai_summary_jobs?select=*&status=eq.queued&order=created_at.asc&limit={safe_limit}",
    )
    if isinstance(payload, list):
        return payload, 200
    return [], status_code


def update_summary_job(job_id: str, fields: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    encoded = quote(job_id, safe="")
    payload = dict(fields)
    payload["updated_at"] = _now_iso()
    response_payload, response_status = _request(
        "PATCH",
        f"/rest/v1/ai_summary_jobs?id_job=eq.{encoded}",
        json=payload,
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else payload), response_status
    return response_payload, response_status


def claim_summary_job(job_id: str) -> Tuple[Dict[str, Any], int]:
    encoded = quote(job_id, safe="")
    payload = {
        "status": "processing",
        "progress": 5,
        "started_at": _now_iso(),
        "finished_at": None,
        "error_message": None,
        "updated_at": _now_iso(),
    }
    response_payload, response_status = _request(
        "PATCH",
        f"/rest/v1/ai_summary_jobs?id_job=eq.{encoded}&status=eq.queued",
        json=payload,
        extra_headers={"Prefer": "return=representation"},
    )
    if isinstance(response_payload, list):
        return (response_payload[0] if response_payload else {}), response_status
    return response_payload, response_status
