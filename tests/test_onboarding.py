import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.api.routes.users import onboard_current_user
from app.api.schemas.user import PatientOnboarding, PhysicianOnboarding
from app.core.config import settings
from app.models.users import Patient, Physician, RoleEnum, User


def _claims() -> dict[str, object]:
    return {
        "iss": f"https://{settings.auth0_domain}/",
        "sub": "auth0|new-user",
    }


def _db(execute_results: list) -> SimpleNamespace:
    """Session stub; one scalar_one_or_none result per expected execute call."""
    execute = AsyncMock(
        side_effect=[
            # Bind result now: a plain closure would capture the loop variable.
            SimpleNamespace(scalar_one_or_none=lambda result=result: result)
            for result in execute_results
        ]
    )
    return SimpleNamespace(
        execute=execute,
        add=MagicMock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
        refresh=AsyncMock(),
    )


def _patient_payload() -> PatientOnboarding:
    return PatientOnboarding(
        email="new.patient@example.com",
        first_name="New",
        last_name="Patient",
        date_of_birth="1990-01-01",
        biological_sex="female",
        baseline_height_cm=170,
        baseline_weight_kg=65,
    )


class OnboardingRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_creates_patient_account_from_verified_identity(self):
        db = _db([None, None])

        user = await onboard_current_user(_patient_payload(), _claims(), db)

        self.assertEqual(user.email, "new.patient@example.com")
        self.assertEqual(user.role, RoleEnum.patient)
        self.assertEqual(user.auth0_issuer, f"https://{settings.auth0_domain}/")
        self.assertEqual(user.auth0_subject, "auth0|new-user")
        self.assertIsNotNone(user.last_used_at)

        added_user, added_patient = (call.args[0] for call in db.add.call_args_list)
        self.assertIsInstance(added_user, User)
        self.assertIsInstance(added_patient, Patient)
        self.assertIs(added_patient.user, added_user)
        self.assertEqual(added_patient.date_of_birth.isoformat(), "1990-01-01")
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once_with(user)

    async def test_creates_physician_account(self):
        db = _db([None, None])
        payload = PhysicianOnboarding(
            email="new.physician@example.com",
            first_name="New",
            last_name="Physician",
            medical_license_number="LIC-123",
            specialty="Cardiology",
        )

        user = await onboard_current_user(payload, _claims(), db)

        self.assertEqual(user.role, RoleEnum.physician)
        _, added_physician = (call.args[0] for call in db.add.call_args_list)
        self.assertIsInstance(added_physician, Physician)
        self.assertEqual(added_physician.medical_license_number, "LIC-123")

    async def test_returns_conflict_when_identity_already_linked(self):
        db = _db([SimpleNamespace(id="existing-user"), None])

        with self.assertRaises(HTTPException) as raised:
            await onboard_current_user(_patient_payload(), _claims(), db)

        self.assertEqual(raised.exception.status_code, 409)
        db.add.assert_not_called()
        db.commit.assert_not_awaited()

    async def test_returns_conflict_when_email_already_registered(self):
        db = _db([None, SimpleNamespace(id="existing-user")])

        with self.assertRaises(HTTPException) as raised:
            await onboard_current_user(_patient_payload(), _claims(), db)

        self.assertEqual(raised.exception.status_code, 409)
        db.add.assert_not_called()

    async def test_rejects_claims_with_unexpected_issuer(self):
        db = _db([])
        claims = {"iss": "https://unexpected.example/", "sub": "auth0|new-user"}

        with self.assertRaises(HTTPException) as raised:
            await onboard_current_user(_patient_payload(), claims, db)

        self.assertEqual(raised.exception.status_code, 401)
        db.execute.assert_not_awaited()

    async def test_maps_integrity_error_to_conflict(self):
        db = _db([None, None])
        db.commit = AsyncMock(side_effect=IntegrityError("stmt", "params", Exception()))

        with self.assertRaises(HTTPException) as raised:
            await onboard_current_user(_patient_payload(), _claims(), db)

        self.assertEqual(raised.exception.status_code, 409)
        db.rollback.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()