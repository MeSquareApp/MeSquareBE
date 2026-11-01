import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException

from app.api.deps import get_current_patient, get_current_physician
from app.models.users import RoleEnum


class CurrentRoleDependencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolves_patient_from_internal_user_id(self):
        patient = SimpleNamespace(user_id="me-square-user-id")
        db = SimpleNamespace(
            execute=AsyncMock(
                return_value=SimpleNamespace(
                    scalar_one_or_none=lambda: patient,
                )
            )
        )
        user = SimpleNamespace(id="me-square-user-id", role=RoleEnum.patient)

        result = await get_current_patient(user, db)

        self.assertIs(result, patient)
        db.execute.assert_awaited_once()

    async def test_non_patient_cannot_resolve_patient(self):
        db = SimpleNamespace(execute=AsyncMock())
        user = SimpleNamespace(id="physician-user-id", role=RoleEnum.physician)

        with self.assertRaises(HTTPException) as raised:
            await get_current_patient(user, db)

        self.assertEqual(raised.exception.status_code, 403)
        db.execute.assert_not_awaited()

    async def test_resolves_physician_from_internal_user_id(self):
        physician = SimpleNamespace(user_id="me-square-user-id")
        db = SimpleNamespace(
            execute=AsyncMock(
                return_value=SimpleNamespace(
                    scalar_one_or_none=lambda: physician,
                )
            )
        )
        user = SimpleNamespace(id="me-square-user-id", role=RoleEnum.physician)

        result = await get_current_physician(user, db)

        self.assertIs(result, physician)
        db.execute.assert_awaited_once()

    async def test_non_physician_cannot_resolve_physician(self):
        db = SimpleNamespace(execute=AsyncMock())
        user = SimpleNamespace(id="patient-user-id", role=RoleEnum.patient)

        with self.assertRaises(HTTPException) as raised:
            await get_current_physician(user, db)

        self.assertEqual(raised.exception.status_code, 403)
        db.execute.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
