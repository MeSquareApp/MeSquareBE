import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.api.routes.physician import view_patient_data


class ProtectedPatientRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def test_patient_biomarkers_require_authentication(self):
        response = self.client.get("/patients/me/biomarkers")

        self.assertEqual(response.status_code, 401)

    def test_old_caller_selected_patient_route_is_removed(self):
        response = self.client.get(
            "/patients/550e8400-e29b-41d4-a716-446655440000/biomarkers"
        )

        self.assertEqual(response.status_code, 404)

    async def test_physician_without_active_link_cannot_view_patient_data(self):
        physician = SimpleNamespace(user_id=uuid4())
        db = SimpleNamespace(
            execute=AsyncMock(
                return_value=SimpleNamespace(scalar_one_or_none=lambda: None)
            )
        )

        with self.assertRaises(HTTPException) as raised:
            await view_patient_data(uuid4(), physician, db)

        self.assertEqual(raised.exception.status_code, 403)
        db.execute.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
