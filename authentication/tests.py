from django.test import TestCase
from rest_framework.test import APITestCase
from django.urls import reverse


class AuthenticationTests(APITestCase):
    def test_signup(self):
        url = reverse("signup")
        response = self.client.post(
            url, {"password": "testpassword123", "email": "testuser@example.com"}
        )
        self.assertEqual(response.status_code, 201)
        self.assertIn("success", response.data)
        self.assertTrue(response.data["success"])
        self.assertIn("message", response.data)
        self.assertEqual(response.data["message"], "User registered successfully")
        self.assertIn("access_token", response.cookies)
        self.assertIn("refresh_token", response.cookies)

    def test_login(self):
        self.test_signup()
        url = reverse("login")
        email = "testuser@example.com"
        response = self.client.post(
            url, {"username": email.split("@", -1)[0], "password": "testpassword123"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access_token", response.cookies)
        self.assertIn("refresh_token", response.cookies)
        self.assertTrue(response.data["success"])
