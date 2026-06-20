from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.files.uploadedfile import SimpleUploadedFile
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
        ) as create_user:
            response = self.client.post("/api/users/register/", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("tokens", response.data)
        self.assertTrue(response.data["tokens"]["access"])
        self.assertEqual(response.data["user"]["full_name"], "Student One")
        saved_password = create_user.call_args.kwargs["password_value"]
        self.assertNotEqual(saved_password, "mypassword123")
        self.assertTrue(check_password("mypassword123", saved_password))

    def test_login_success(self):
        user_row = {
            "id_user": "uid-2",
            "email_user": "student@example.com",
            "full_name_user": "Student One",
            "password_user": make_password("mypassword123"),
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

    def test_login_plain_password_migrates_to_hash(self):
        user_row = {
            "id_user": "uid-legacy",
            "email_user": "legacy@example.com",
            "full_name_user": "Legacy User",
            "password_user": "oldpassword123",
        }

        with patch("app.users.views.supabase_client.get_user_by_email", return_value=(user_row, 200)), patch(
            "app.users.views.supabase_client.update_user_profile", return_value=(user_row, 200)
        ) as update_user:
            response = self.client.post(
                "/api/users/login/",
                {"email": "legacy@example.com", "password": "oldpassword123"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        saved_password = update_user.call_args.args[1]["password_user"]
        self.assertNotEqual(saved_password, "oldpassword123")
        self.assertTrue(check_password("oldpassword123", saved_password))

    def test_google_login_existing_user_success(self):
        user_row = {
            "id_user": "uid-google",
            "email_user": "google@example.com",
            "full_name_user": "Google User",
        }

        with patch("app.users.views._firebase_app"), patch(
            "app.users.views.firebase_auth.verify_id_token",
            return_value={"email": "google@example.com", "name": "Google User"},
        ), patch("app.users.views.supabase_client.get_user_by_email", return_value=(user_row, 200)):
            response = self.client.post(
                "/api/users/google-login/",
                {"id_token": "firebase-token"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("tokens", response.data)
        self.assertEqual(response.data["user"]["id"], "uid-google")
        self.assertFalse(response.data["is_new_user"])

    def test_google_login_creates_user_when_missing(self):
        created_row = {
            "id_user": "uid-new-google",
            "email_user": "newgoogle@example.com",
            "full_name_user": "New Google",
        }

        with patch("app.users.views._firebase_app"), patch(
            "app.users.views.firebase_auth.verify_id_token",
            return_value={"email": "newgoogle@example.com", "name": "New Google"},
        ), patch(
            "app.users.views.supabase_client.get_user_by_email",
            return_value=({}, 200),
        ), patch(
            "app.users.views.supabase_client.create_user",
            return_value=(created_row, 201),
        ) as create_user:
            response = self.client.post(
                "/api/users/google-login/",
                {"id_token": "firebase-token"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["user"]["email"], "newgoogle@example.com")
        self.assertTrue(response.data["is_new_user"])
        self.assertEqual(create_user.call_args.kwargs["full_name"], "New Google")

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

    def test_profile_update_refetches_when_patch_response_has_no_user_id(self):
        user_id = "00000000-0000-0000-0000-000000000001"
        refetched_row = {
            "id_user": user_id,
            "email_user": "student@example.com",
            "full_name_user": "Student Updated",
            "avatar_url": "https://example.com/avatar.jpg",
        }

        with patch(
            "app.users.views.supabase_client.update_user_profile",
            return_value=({"full_name_user": "Student Updated"}, 200),
        ), patch(
            "app.users.views.supabase_client.get_user_by_id",
            return_value=(refetched_row, 200),
        ) as get_user:
            response = self.client.patch(
                f"/api/users/{user_id}/",
                {"full_name": "Student Updated", "email": "student@example.com"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], user_id)
        self.assertEqual(response.data["avatar_url"], "https://example.com/avatar.jpg")
        get_user.assert_called_once_with(user_id)

    def test_avatar_upload_refetches_when_patch_response_has_no_user_id(self):
        user_id = "00000000-0000-0000-0000-000000000002"
        avatar_url = "https://example.com/avatar-new.jpg"
        refetched_row = {
            "id_user": user_id,
            "email_user": "student@example.com",
            "full_name_user": "Student One",
            "avatar_url": avatar_url,
        }
        upload = SimpleUploadedFile(
            "avatar.jpg",
            b"fake-image-bytes",
            content_type="image/jpeg",
        )

        with patch(
            "app.users.views.supabase_client.upload_storage_file",
            return_value=({"ok": True}, 200),
        ), patch(
            "app.users.views.supabase_client.public_storage_url",
            return_value=avatar_url,
        ), patch(
            "app.users.views.supabase_client.update_user_profile",
            return_value=({"avatar_url": avatar_url}, 200),
        ), patch(
            "app.users.views.supabase_client.get_user_by_id",
            return_value=(refetched_row, 200),
        ) as get_user:
            response = self.client.post(
                f"/api/users/{user_id}/avatar/",
                {"file": upload},
                format="multipart",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["user"]["id"], user_id)
        self.assertEqual(response.data["user"]["avatar_url"], avatar_url)
        get_user.assert_called_once_with(user_id)

    def test_forgot_password_sends_reset_email_for_existing_user(self):
        user_row = {
            "id_user": "00000000-0000-0000-0000-000000000003",
            "email_user": "reset@example.com",
            "full_name_user": "Reset User",
        }

        with patch("app.users.views.supabase_client.get_user_by_email", return_value=(user_row, 200)), patch(
            "app.users.views.send_mail", return_value=1
        ) as send_mail:
            response = self.client.post(
                "/api/users/password-reset/request/",
                {"email": "reset@example.com"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("lien ket dat lai mat khau", response.data["message"])
        self.assertEqual(send_mail.call_args.kwargs["recipient_list"], ["reset@example.com"])
        self.assertIn("/api/users/password-reset/confirm/?token=", send_mail.call_args.kwargs["message"])

    def test_forgot_password_can_send_email_with_resend_api(self):
        user_row = {
            "id_user": "00000000-0000-0000-0000-000000000005",
            "email_user": "reset-api@example.com",
            "full_name_user": "Reset Api",
        }

        class FakeResponse:
            status_code = 200
            text = "{}"

        with self.settings(RESEND_API_KEY="resend-key", RESEND_FROM_EMAIL="Lumio Study <reset@example.com>"), patch(
            "app.users.views.supabase_client.get_user_by_email", return_value=(user_row, 200)
        ), patch("app.users.views.requests.post", return_value=FakeResponse()) as post:
            response = self.client.post(
                "/api/users/password-reset/request/",
                {"email": "reset-api@example.com"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["to"], ["reset-api@example.com"])
        self.assertIn("/api/users/password-reset/confirm/?token=", payload["text"])

    def test_reset_password_confirm_updates_hashed_password(self):
        from app.users.views import _make_password_reset_token

        user_row = {
            "id_user": "00000000-0000-0000-0000-000000000004",
            "email_user": "reset-confirm@example.com",
            "password_user": make_password("oldpassword123"),
        }
        token = _make_password_reset_token(user_row)

        with patch("app.users.views.supabase_client.get_user_by_id", return_value=(user_row, 200)), patch(
            "app.users.views.supabase_client.update_user_profile", return_value=({"id_user": user_row["id_user"]}, 200)
        ) as update_user:
            response = self.client.post(
                "/api/users/password-reset/confirm/",
                {
                    "token": token,
                    "new_password": "newpassword123",
                    "confirm_password": "newpassword123",
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        saved_password = update_user.call_args.args[1]["password_user"]
        self.assertNotEqual(saved_password, "newpassword123")
        self.assertTrue(check_password("newpassword123", saved_password))
