import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app, auth0


class AuthRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def test_public_route_does_not_require_authentication(self):
        response = self.client.get("/api/public")

        self.assertEqual(response.status_code, 200)

    def test_private_route_requires_authentication(self):
        response = self.client.get("/api/private")

        self.assertEqual(response.status_code, 401)

    def test_private_route_returns_authenticated_user(self):
        with patch.object(
            auth0.api_client,
            "verify_request",
            new=AsyncMock(return_value={"sub": "test-user"}),
        ):
            response = self.client.get(
                "/api/private",
                headers={"Authorization": "Bearer test-token"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user_id"], "test-user")

    def test_scoped_route_rejects_missing_permission(self):
        with patch.object(
            auth0.api_client,
            "verify_request",
            new=AsyncMock(return_value={"sub": "test-user"}),
        ):
            response = self.client.get(
                "/api/private-scoped",
                headers={"Authorization": "Bearer test-token"},
            )

        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
