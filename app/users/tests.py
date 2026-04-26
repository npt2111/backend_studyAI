from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

User = get_user_model()


class UsersAuthApiTests(APITestCase):
    def test_register_success(self):
        payload = {
            "email": "student@example.com",
            "password": "mypassword123",
            "full_name": "Student One",
        }

        response = self.client.post("/api/users/register/", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("tokens", response.data)
        self.assertIn("access", response.data["tokens"])
        self.assertTrue(User.objects.filter(email="student@example.com").exists())

    def test_login_success(self):
        User.objects.create_user(
            username="student@example.com",
            email="student@example.com",
            password="mypassword123",
        )

        response = self.client.post(
            "/api/users/login/",
            {"email": "student@example.com", "password": "mypassword123"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("tokens", response.data)
        self.assertIn("access", response.data["tokens"])

    def test_me_requires_authentication(self):
        response = self.client.get("/api/users/me/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
