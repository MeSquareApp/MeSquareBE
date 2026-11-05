"""Shared test fixtures.

Before any application module is imported, DATABASE_URL is redirected to a
dedicated test database (the development database name suffixed with
"_test"), so tests never touch real data. pydantic-settings gives
environment variables precedence over the .env file, which makes this work
without changing any application code.

The test database is created if missing and migrated with Alembic on
session start; all tables are truncated between tests. Authentication is
faked by overriding the `verify_auth0_token` dependency with canned claims.
"""

import asyncio
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_SUB = "auth0|test-user-1"
DEFAULT_EMAIL = "janedoe@test.com"
EMAIL_CLAIM = "https://mesquared.app/claims/email"
EMAIL_VERIFIED_CLAIM = "https://mesquared.app/claims/email_verified"


def _derive_test_database_url() -> str:
    """Build the test DB URL from the configured DATABASE_URL."""
    url = os.environ.get("DATABASE_URL") or dotenv_values(PROJECT_ROOT / ".env").get(
        "DATABASE_URL"
    )
    if not url:
        raise RuntimeError(
            "DATABASE_URL must be set (env var or .env) to run the tests."
        )
    parts = urlsplit(url)
    db_name = parts.path.strip("/").split("/")[0]
    return urlunsplit(parts._replace(path=f"/{db_name}_test"))


TEST_DATABASE_URL = _derive_test_database_url()
# Redirect the application to the test database before it is imported.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

# Application imports must happen AFTER the env var override above.
from alembic import command  # noqa: E402
from alembic.config import Config as AlembicConfig  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.db import engine  # noqa: E402
from app.core.security import verify_auth0_token  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402


async def _create_database_if_missing() -> None:
    """Connect to the maintenance database and create the test DB if needed."""
    parts = urlsplit(TEST_DATABASE_URL)
    db_name = parts.path.strip("/")
    server_url = urlunsplit(parts._replace(path="/postgres"))
    admin_engine = create_async_engine(server_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as conn:
            exists = await conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": db_name},
            )
            if exists.scalar() is None:
                await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        await admin_engine.dispose()


def _run_migrations() -> None:
    """Apply all Alembic migrations to the test database.

    `alembic/env.py` reads the URL from `app.core.config.settings`, which
    already points at the test database because of the env var override.
    """
    alembic_cfg = AlembicConfig(str(PROJECT_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    command.upgrade(alembic_cfg, "head")


async def _truncate_tables() -> None:
    """Empty every table so each test starts from a clean database."""
    table_names = ", ".join(f'"{name}"' for name in sorted(Base.metadata.tables))
    async with engine.begin() as conn:
        await conn.execute(
            text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE")
        )
    # The connections created here are bound to this throwaway event loop;
    # drop them so the app (running on TestClient's own loop) always gets
    # fresh connections.
    await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def database():
    """Create + migrate the test database once per test session."""
    asyncio.run(_create_database_if_missing())
    _run_migrations()
    yield
    asyncio.run(engine.dispose())


@pytest.fixture(autouse=True)
def clean_tables():
    """Truncate all tables around every test."""
    asyncio.run(_truncate_tables())
    yield


@pytest.fixture
def client():
    """Plain test client with no authentication override."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth(client):
    """
    Return a factory that authorizes requests as a fake Auth0 identity.

    Usage:
        c = auth()                          # default verified user
        c = auth(sub="auth0|other")         # a different identity
        c = auth(email_verified=False)      # unverified email -> 403
        c = auth(email=None)                # missing email claim -> 403
    """

    def _auth(
        sub: str = DEFAULT_SUB,
        email: str | None = DEFAULT_EMAIL,
        email_verified: bool = True,
    ):
        claims: dict[str, object] = {
            "iss": f"https://{settings.auth0_domain}/",
            "sub": sub,
        }
        if email is not None:
            claims[EMAIL_CLAIM] = email
        claims[EMAIL_VERIFIED_CLAIM] = email_verified
        app.dependency_overrides[verify_auth0_token] = lambda: claims
        return client

    yield _auth
    app.dependency_overrides.pop(verify_auth0_token, None)
