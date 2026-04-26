import os
from typing import Any, Dict, Optional, Tuple
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
    return _select_one(f"/rest/v1/user?select=*&email_user=eq.{encoded}&limit=1")


def get_user_by_id(user_id: str) -> Tuple[Dict[str, Any], int]:
    encoded = quote(user_id, safe="")
    return _select_one(f"/rest/v1/user?select=*&id_user=eq.{encoded}&limit=1")


def create_user(
    *,
    full_name: str,
    email: str,
    password_hash: str,
    phone: str = "",
    address: str = "",
    birthday: str = "",
) -> Tuple[Dict[str, Any], int]:
    payload: Dict[str, Any] = {
        "full_name_user": full_name,
        "email_user": email.strip().lower(),
        "password_user": password_hash,
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
