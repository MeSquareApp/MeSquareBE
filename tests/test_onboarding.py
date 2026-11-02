import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.api.routes.users import (
    AUTH0_EMAIL_CLAIM,
    AUTH0_EMAIL_VERIFIED_CLAIM,
    create_m2_account,
    get_me,
)
from app.api.schemas.user import OnboardingRequest
from app.core.config import settings
from app.models.users import RoleEnum, User


def _claims() -> dict[str, object]:
    return {
        "iss": f"https://{settings.auth0_domain}/",
        "sub": "auth0|new-user",
        AUTH0_EMAIL_CLAIM: " New.Patient@Example.com ",
        AUTH0_EMAIL_VERIFIED_CLAIM: True,
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


def _payload(role: RoleEnum = RoleEnum.patient) -> OnboardingRequest:
    return OnboardingRequest(
        first_name="New",
        last_name="Patient",
        role=role,
    )


class OnboardingRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_me_returns_the_authenticated_database_user(self):
        user = SimpleNamespace(
            id=UUID("3f5150ea-0c80-4b79-bc27-e261f1702dca"),
            email="user@example.com",
            first_name="Database",
            last_name="User",
        )

        result = await get_me(user)

        self.assertIs(result, user)

    async def test_creates_only_user_from_verified_identity(self):
        db = _db([None, None])

        user = await create_m2_account(_payload(), _claims(), db)

        self.assertEqual(user.email, "new.patient@example.com")
        self.assertIsInstance(user.id, UUID)
        self.assertEqual(user.first_name, "New")
        self.assertEqual(user.last_name, "Patient")
        self.assertEqual(user.role, RoleEnum.patient)
        self.assertEqual(user.auth0_issuer, f"https://{settings.auth0_domain}/")
        self.assertEqual(user.auth0_subject, "auth0|new-user")
        self.assertEqual(user.created_at, user.last_used_at)
        db.add.assert_called_once_with(user)
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once_with(user)

    async def test_returns_conflict_when_identity_already_linked(self):
        db = _db([SimpleNamespace(id="existing-user"), None])

        with self.assertRaises(HTTPException) as raised:
            await create_m2_account(_payload(), _claims(), db)

        self.assertEqual(raised.exception.status_code, 409)
        db.add.assert_not_called()
        db.commit.assert_not_awaited()

    async def test_returns_conflict_when_email_already_registered(self):
        db = _db([None, SimpleNamespace(id="existing-user")])

        with self.assertRaises(HTTPException) as raised:
            await create_m2_account(_payload(), _claims(), db)

        self.assertEqual(raised.exception.status_code, 409)
        db.add.assert_not_called()

    async def test_rejects_missing_or_unverified_auth0_email(self):
        invalid_claims = [
            {**_claims(), AUTH0_EMAIL_VERIFIED_CLAIM: False},
            {key: value for key, value in _claims().items() if key != AUTH0_EMAIL_CLAIM},
        ]
        for claims in invalid_claims:
            db = _db([])
            with self.subTest(claims=claims), self.assertRaises(HTTPException) as raised:
                await create_m2_account(_payload(), claims, db)
            self.assertEqual(raised.exception.status_code, 403)
            db.execute.assert_not_awaited()

    async def test_admin_role_cannot_be_self_registered(self):
        db = _db([])
        with self.assertRaises(HTTPException) as raised:
            await create_m2_account(_payload(RoleEnum.admin), _claims(), db)
        self.assertEqual(raised.exception.status_code, 403)
        db.execute.assert_not_awaited()

    async def test_rejects_claims_with_unexpected_issuer(self):
        db = _db([])
        claims = {"iss": "https://unexpected.example/", "sub": "auth0|new-user"}

        with self.assertRaises(HTTPException) as raised:
            await create_m2_account(_payload(), claims, db)

        self.assertEqual(raised.exception.status_code, 401)
        db.execute.assert_not_awaited()

    async def test_maps_integrity_error_to_conflict(self):
        db = _db([None, None])
        db.commit = AsyncMock(side_effect=IntegrityError("stmt", "params", Exception()))

        with self.assertRaises(HTTPException) as raised:
            await create_m2_account(_payload(), _claims(), db)

        self.assertEqual(raised.exception.status_code, 409)
        db.rollback.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()