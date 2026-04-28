from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
from django.conf import settings
from rest_framework import status
from rest_framework.test import APITestCase


class UsersAuthApiTests(APITestCase):
    def _make_access_token(self, user_id: str, email: str) -> str:
        payload = {
            "sub": user_id,
            "email": email,
            "type": "access",
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int((datetime.now(timezone.utc) + timedelta(minutes=60)).timestamp()),
        }
        return jwt.encode(
            payload,
            getattr(settings, "JWT_SECRET", settings.SECRET_KEY),
            algorithm=getattr(settings, "JWT_ALGORITHM", "HS256"),
        )

    def test_register_success(self):
        created_row = {
            "id_user": "uid-1",
            "email_user": "student@example.com",
            "full_name_user": "Student One",
            "password_user": "hashed",
        }
        payload = {
            "email": "student@example.com",
            "password": "mypassword123",
            "full_name": "Student One",
        }

        with patch("app.users.views.supabase_client.get_user_by_email", return_value=({}, 200)), patch(
            "app.users.views.supabase_client.create_user", return_value=(created_row, 201)
        ):
            response = self.client.post("/api/users/register/", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("tokens", response.data)
        self.assertTrue(response.data["tokens"]["access"])
        self.assertEqual(response.data["user"]["full_name"], "Student One")

    def test_login_success(self):
        user_row = {
            "id_user": "uid-2",
            "email_user": "student@example.com",
            "full_name_user": "Student One",
            "password_user": "mypassword123",
        }

        with patch("app.users.views.supabase_client.get_user_by_email", return_value=(user_row, 200)):
            response = self.client.post(
                "/api/users/login/",
                {"email": "student@example.com", "password": "mypassword123"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("tokens", response.data)
        self.assertTrue(response.data["tokens"]["access"])
        self.assertEqual(response.data["user"]["full_name"], "Student One")

    def test_me_requires_authentication(self):
        response = self.client.get("/api/users/me/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_success(self):
        token = self._make_access_token("uid-3", "student@example.com")
        user_row = {
            "id_user": "uid-3",
            "email_user": "student@example.com",
            "full_name_user": "Student One",
        }
        with patch("app.users.views.supabase_client.get_user_by_id", return_value=(user_row, 200)):
            response = self.client.get(
                "/api/users/me/",
                HTTP_AUTHORIZATION=f"Bearer {token}",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], "student@example.com")
