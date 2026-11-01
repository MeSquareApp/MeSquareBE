import unittest
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.core.config import settings
from app.core.security import Auth0JWTValidator


class Auth0JWTValidatorTests(unittest.TestCase):
    def setUp(self):
        self.validator = Auth0JWTValidator()
        self.validator.jwks_client = SimpleNamespace(
            get_signing_key_from_jwt=lambda _token: SimpleNamespace(key="test-key")
        )
        self.credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials="test-token",
        )

    @patch("app.core.security.jwt.decode")
    def test_valid_token_returns_verified_claims(self, decode):
        decode.return_value = {"sub": "auth0|test-user", "aud": "test-audience"}

        claims = self.validator(self.credentials)

        self.assertEqual(claims["sub"], "auth0|test-user")
        decode.assert_called_once_with(
            "test-token",
            "test-key",
            algorithms=settings.auth0_algorithms,
            audience=settings.auth0_audience,
            issuer=self.validator.issuer,
        )

    @patch("app.core.security.jwt.decode")
    def test_invalid_token_returns_generic_unauthorized(self, decode):
        decode.side_effect = jwt.InvalidTokenError("sensitive decoder detail")

        with self.assertRaises(HTTPException) as raised:
            self.validator(self.credentials)

        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(raised.exception.detail, "Invalid authentication credentials.")
        self.assertEqual(
            raised.exception.headers,
            {"WWW-Authenticate": "Bearer"},
        )

    def test_missing_credentials_returns_unauthorized(self):
        with self.assertRaises(HTTPException) as raised:
            self.validator(None)

        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(raised.exception.detail, "Not authenticated")

    @patch("app.core.security.jwt.decode")
    def test_token_without_subject_is_rejected(self, decode):
        decode.return_value = {"aud": "test-audience"}

        with self.assertRaises(HTTPException) as raised:
            self.validator(self.credentials)

        self.assertEqual(raised.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
