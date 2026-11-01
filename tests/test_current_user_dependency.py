import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException

from app.api.deps import get_current_user
from app.core.config import settings


class CurrentUserDependencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolves_auth0_identity_to_me_squared_user(self):
        user = SimpleNamespace(id="internal-user-id")
        db = SimpleNamespace(
            execute=AsyncMock(
                return_value=SimpleNamespace(
                    scalar_one_or_none=lambda: user,
                )
            )
        )
        claims = {
            "iss": f"https://{settings.auth0_domain}/",
            "sub": "auth0|example-user",
        }

        result = await get_current_user(claims, db)

        self.assertIs(result, user)
        db.execute.assert_awaited_once()

    async def test_returns_not_found_when_auth0_identity_is_unmapped(self):
        db = SimpleNamespace(
            execute=AsyncMock(
                return_value=SimpleNamespace(scalar_one_or_none=lambda: None)
            )
        )
        claims = {
            "iss": f"https://{settings.auth0_domain}/",
            "sub": "auth0|unmapped-user",
        }

        with self.assertRaises(HTTPException) as raised:
            await get_current_user(claims, db)

        self.assertEqual(raised.exception.status_code, 404)

    async def test_rejects_claims_with_unexpected_issuer(self):
        db = SimpleNamespace(execute=AsyncMock())
        claims = {
            "iss": "https://unexpected.example/",
            "sub": "auth0|example-user",
        }

        with self.assertRaises(HTTPException) as raised:
            await get_current_user(claims, db)

        self.assertEqual(raised.exception.status_code, 401)
        db.execute.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
