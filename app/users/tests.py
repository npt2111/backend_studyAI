from unittest.mock import patch

from rest_framework import status
from rest_framework.test import APITestCase


class UsersAuthApiTests(APITestCase):
    def test_register_success(self):
        mocked_signup = {
            "user": {"id": "uid-1", "email": "student@example.com", "user_metadata": {"full_name": "Student One"}},
            "access_token": "access-token",
            "refresh_token": "refresh-token",
        }
        mocked_profile = {
            "id": "uid-1",
            "email": "student@example.com",
            "full_name": "Student One",
        }
        payload = {
            "email": "student@example.com",
            "password": "mypassword123",
            "full_name": "Student One",
        }

        with patch("app.users.views.supabase_client.signup", return_value=(mocked_signup, 200)), patch(
            "app.users.views.supabase_client.upsert_profile", return_value=(mocked_profile, 201)
        ):
            response = self.client.post("/api/users/register/", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("tokens", response.data)
        self.assertEqual(response.data["tokens"]["access"], "access-token")
        self.assertEqual(response.data["user"]["full_name"], "Student One")

    def test_login_success(self):
        mocked_login = {
            "user": {"id": "uid-2", "email": "student@example.com"},
            "access_token": "access-token",
            "refresh_token": "refresh-token",
        }
        mocked_profile = {
            "id": "uid-2",
            "email": "student@example.com",
            "full_name": "Student One",
        }

        with patch("app.users.views.supabase_client.login", return_value=(mocked_login, 200)), patch(
            "app.users.views.supabase_client.get_profile_by_auth_id",
            return_value=(mocked_profile, 200),
        ):
            response = self.client.post(
                "/api/users/login/",
                {"email": "student@example.com", "password": "mypassword123"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("tokens", response.data)
        self.assertEqual(response.data["tokens"]["access"], "access-token")
        self.assertEqual(response.data["user"]["full_name"], "Student One")

    def test_me_requires_authentication(self):
        response = self.client.get("/api/users/me/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_success(self):
        mocked_user = {
            "id": "uid-3",
            "email": "student@example.com",
            "user_metadata": {"full_name": "Student One"},
        }
        mocked_profile = {
            "id": "uid-3",
            "email": "student@example.com",
            "full_name": "Student One",
        }
        with patch("app.users.views.supabase_client.get_user", return_value=(mocked_user, 200)), patch(
            "app.users.views.supabase_client.get_profile_by_auth_id",
            return_value=(mocked_profile, 200),
        ):
            response = self.client.get(
                "/api/users/me/",
                HTTP_AUTHORIZATION="Bearer access-token",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], "student@example.com")
