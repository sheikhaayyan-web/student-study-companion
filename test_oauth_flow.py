import os
import tempfile
import unittest
from unittest.mock import patch

_TEST_DATA = tempfile.TemporaryDirectory()
os.environ["TALIB_DB_PATH"] = os.path.join(_TEST_DATA.name, "oauth.sqlite3")
os.environ["TALIB_GENERATED_DIR"] = os.path.join(_TEST_DATA.name, "exports")

from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient

from backend import app as app_module
from backend.app import app


class FakeGoogleClient:
    def __init__(self, profile):
        self.profile = profile

    async def authorize_redirect(self, request, redirect_uri):
        return RedirectResponse("/fake-provider", status_code=302)

    async def authorize_access_token(self, request):
        return {"userinfo": self.profile}


class FakeFacebookResponse:
    def __init__(self, profile):
        self.profile = profile

    def json(self):
        return self.profile


class FakeFacebookClient:
    def __init__(self, profile):
        self.profile = profile

    async def authorize_access_token(self, request):
        return {"access_token": "test-access-token"}

    async def get(self, path, token, params):
        self.asserted_request = (path, params)
        return FakeFacebookResponse(self.profile)


class OAuthFlowTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, follow_redirects=False)
        self.password = "Correct horse battery staple 42!"

    def test_google_sign_in_creates_and_reuses_one_account(self):
        profile = {
            "sub": "google-subject-123",
            "email": "oauth-student@example.test",
            "email_verified": True,
            "name": "OAuth Student",
        }
        with patch.dict(app_module.oauth_clients, {"google": FakeGoogleClient(profile)}):
            first = self.client.get("/api/auth/oauth/google/callback")
            self.assertEqual(first.status_code, 303)
            user = self.client.get("/api/auth/me").json()["user"]
            dashboard = self.client.get("/api/dashboard").json()
            self.assertEqual(user["email"], profile["email"])
            self.assertEqual(dashboard["profile"]["name"], profile["name"])
            self.assertEqual(dashboard["courses"], [])

            self.client.post("/api/auth/logout")
            second = self.client.get("/api/auth/oauth/google/callback")
            self.assertEqual(second.status_code, 303)
            self.assertEqual(self.client.get("/api/auth/me").json()["user"]["id"], user["id"])

    def test_existing_password_account_requires_explicit_same_email_link(self):
        signup = self.client.post("/api/auth/signup", json={
            "email": "linked@example.test",
            "password": self.password,
            "name": "Existing Student",
        })
        self.assertEqual(signup.status_code, 201, signup.text)
        user_id = signup.json()["user"]["id"]
        provider = FakeGoogleClient({
            "sub": "google-link-subject",
            "email": "linked@example.test",
            "email_verified": True,
            "name": "Existing Student",
        })

        with patch.dict(app_module.oauth_clients, {"google": provider}):
            collision = self.client.get("/api/auth/oauth/google/callback")
            self.assertEqual(collision.headers["location"], "/?oauth=link_required")

            started = self.client.get("/api/auth/link/google")
            self.assertEqual(started.status_code, 302)
            linked = self.client.get("/api/auth/oauth/google/callback")
            self.assertEqual(linked.headers["location"], "/?oauth=linked")
            self.assertEqual(self.client.get("/api/auth/me").json()["user"]["id"], user_id)

            self.client.post("/api/auth/logout")
            signed_in = self.client.get("/api/auth/oauth/google/callback")
            self.assertEqual(signed_in.status_code, 303)
            self.assertEqual(self.client.get("/api/auth/me").json()["user"]["id"], user_id)

    def test_unverified_provider_email_is_rejected(self):
        with patch.dict(app_module.oauth_clients, {"google": FakeGoogleClient({
            "sub": "unverified-subject",
            "email": "unverified@example.test",
            "email_verified": False,
            "name": "Unverified User",
        })}):
            response = self.client.get("/api/auth/oauth/google/callback")
        self.assertEqual(response.headers["location"], "/?oauth=email_unverified")
        self.assertIsNone(self.client.get("/api/auth/me").json()["user"])

    def test_facebook_sign_in_creates_an_account(self):
        provider = FakeFacebookClient({
            "id": "facebook-subject-456",
            "email": "facebook-student@example.test",
            "name": "Facebook Student",
        })
        with patch.dict(app_module.oauth_clients, {"facebook": provider}):
            response = self.client.get("/api/auth/oauth/facebook/callback")
            self.assertEqual(response.status_code, 303)
            user = self.client.get("/api/auth/me").json()["user"]
            self.assertEqual(user["email"], "facebook-student@example.test")
            self.assertEqual(provider.asserted_request, ("me", {"fields": "id,name,email"}))

    def test_unconfigured_provider_is_not_advertised_or_started(self):
        with patch.dict(app_module.oauth_clients, {}, clear=True):
            providers = self.client.get("/api/auth/providers")
            self.assertEqual(providers.json(), {"google": False, "facebook": False})
            unavailable = self.client.get("/api/auth/oauth/google")
            self.assertEqual(unavailable.status_code, 503)


if __name__ == "__main__":
    unittest.main()
