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
    access_token: Optional[str] = None,
    use_service_key: bool = False,
    extra_headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], int]:
    base_url, api_key = _settings()
    token = api_key if use_service_key else access_token

    headers = {
        "apikey": api_key,
        "Content-Type": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
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


def signup(email: str, password: str, full_name: str = "") -> Tuple[Dict[str, Any], int]:
    payload: Dict[str, Any] = {"email": email, "password": password}
    if full_name:
        payload["data"] = {"full_name": full_name}
    return _request("POST", "/auth/v1/signup", json=payload, use_service_key=True)


def login(email: str, password: str) -> Tuple[Dict[str, Any], int]:
    payload = {"email": email, "password": password}
    return _request(
        "POST",
        "/auth/v1/token?grant_type=password",
        json=payload,
        use_service_key=True,
    )


def refresh_session(refresh_token: str) -> Tuple[Dict[str, Any], int]:
    payload = {"refresh_token": refresh_token}
    return _request(
        "POST",
        "/auth/v1/token?grant_type=refresh_token",
        json=payload,
        use_service_key=True,
    )


def get_user(access_token: str) -> Tuple[Dict[str, Any], int]:
    return _request("GET", "/auth/v1/user", access_token=access_token)


def _rest_select(path_query: str) -> Tuple[Dict[str, Any], int]:
    payload, status_code = _request("GET", path_query, use_service_key=True)
    if isinstance(payload, list):
        if not payload:
            return {}, 200
        return payload[0], 200
    return payload, status_code


def get_profile_by_auth_id(user_id: str) -> Tuple[Dict[str, Any], int]:
    encoded = quote(user_id, safe="")

    # Thu truong hop pho bien: id la FK toi auth.users.id
    payload, status_code = _rest_select(
        f"/rest/v1/user?select=*&id=eq.{encoded}&limit=1"
    )
    if status_code < 400 and payload:
        return payload, status_code

    # Backup: user_id column
    payload2, status_code2 = _rest_select(
        f"/rest/v1/user?select=*&user_id=eq.{encoded}&limit=1"
    )
    if status_code2 < 400 and payload2:
        return payload2, status_code2

    return payload2 if payload2 else payload, status_code2 if status_code2 else status_code


def get_profile_by_email(email: str) -> Tuple[Dict[str, Any], int]:
    encoded = quote(email, safe="")
    return _rest_select(f"/rest/v1/user?select=*&email=eq.{encoded}&limit=1")


def upsert_profile(user_id: str, email: str, full_name: str = "") -> Tuple[Dict[str, Any], int]:
    # Linh hoat cho cac schema dat ten cot khac nhau.
    candidates = [
        ({"id": user_id, "email": email, "full_name": full_name}, "id"),
        ({"id": user_id, "email": email, "name": full_name}, "id"),
        ({"user_id": user_id, "email": email, "full_name": full_name}, "user_id"),
        ({"user_id": user_id, "email": email, "name": full_name}, "user_id"),
        ({"id": user_id, "email": email}, "id"),
        ({"user_id": user_id, "email": email}, "user_id"),
    ]

    headers = {
        "Prefer": "resolution=merge-duplicates,return=representation",
    }
    last_payload: Dict[str, Any] = {}
    last_status = 500

    for body, conflict_key in candidates:
        response_payload, response_status = _request(
            "POST",
            f"/rest/v1/user?on_conflict={conflict_key}",
            json=body,
            use_service_key=True,
            extra_headers=headers,
        )
        if response_status < 400:
            if isinstance(response_payload, list):
                return (response_payload[0] if response_payload else body), response_status
            return response_payload, response_status

        last_payload = response_payload
        last_status = response_status

    return last_payload, last_status
