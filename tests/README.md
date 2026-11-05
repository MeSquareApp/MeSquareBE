# Testing Guide

This document explains how the MeSquareBE test suite works and collects all
the commands you need to run it.

## Overview

The tests are **HTTP-level integration tests**: each test calls the real
FastAPI application through `TestClient`, hits the real PostgreSQL database
(a dedicated test database, never your dev data), and runs the full request
pipeline — routing, Pydantic validation, dependencies, SQLAlchemy queries —
against every endpoint.

The only thing that is faked is **Auth0**: the JWT signature verification is
swapped out for canned claims, so no network calls to Auth0 are made and no
real tokens are needed.

## Test files

| File | What it covers |
|---|---|
| `conftest.py` | Shared fixtures: test database bootstrap, table cleanup, auth faking (see below) |
| `test_m2_account.py` | `POST /users/me/create-m2-account` and `GET /users/me`: signup happy paths, role validation (`sex`/`dob` required for patient, rejected otherwise), admin 403, duplicate identity/email 409, unverified/missing email 403, 401 without token, 404 for unmapped identity |
| `test_patient_onboarding.py` | `PUT/GET /patients/me/profile`: onboarding form fills deferred attributes, partial updates leave other fields alone, validation errors, patient↔physician cross-role 403s |
| `test_physician_onboarding.py` | `PUT/GET /physicians/me/profile`: license/specialty fill, resubmitting own license allowed, blank license 422, duplicate license across physicians 409 |

## How the infrastructure works (`conftest.py`)

### 1. Test database isolation

Before any application module is imported, `conftest.py` reads
`DATABASE_URL` (from the environment or `.env`), appends `_test` to the
database name (e.g. `postgres` → `postgres_test`), and sets it back as the
`DATABASE_URL` environment variable. Because pydantic-settings gives
environment variables precedence over `.env`, the entire application
transparently runs against the test database. **Your development database
is never touched by the tests.**

On session start (once per `pytest` run), the `database` fixture:

1. Connects to the server's `postgres` maintenance database and runs
   `CREATE DATABASE` if the test database doesn't exist yet.
2. Runs `alembic upgrade head` against it — the full migration chain
   (this also acts as a replayability check: if a fresh database can't be
   built from the migrations, the test session fails).

Between every test, the `clean_tables` fixture truncates all tables
(`TRUNCATE ... RESTART IDENTITY CASCADE`), so tests are order-independent
and each one starts from an empty database.

### 2. Faking authentication

The `verify_auth0_token` dependency (the one every protected endpoint uses)
is overridden via `app.dependency_overrides` with a dictionary of canned
claims. The `auth` fixture returns a factory so each test can pick its
identity:

```python
def test_something(auth):
    c = auth()                          # default verified user (janedoe@test.com)
    c = auth(sub="auth0|doc-1", email="doc@test.com")   # a different identity
    c = auth(email_verified=False)      # unverified email -> 403 on signup
    c = auth(email=None)                # missing email claim -> 403 on signup
```

The fake claims include everything the endpoints read:

- `iss` / `sub` — the Auth0 issuer and subject (identity)
- `https://mesquared.app/claims/email` — the verified email
- `https://mesquared.app/claims/email_verified` — the verification flag

Because the override happens at the `verify_auth0_token` level, everything
*downstream* is still fully exercised: `verified_identity`,
`get_current_user`, `get_current_patient`, `get_current_physician`, and all
the role checks.

The plain `client` fixture (no override) produces genuinely unauthenticated
requests, which is how the 401 "Not authenticated" path is tested.

### 3. Reusable flow fixtures

`test_patient_onboarding.py` and `test_physician_onboarding.py` each define
a fixture (`patient_client` / `physician_client`) that creates an account
first and returns an authenticated client — the state a user is in right
after signup, before completing onboarding. Copy this pattern when testing
endpoints that require an account to exist.

## Running the tests

All commands are run from the project root. The only prerequisite is that
your PostgreSQL server (Docker) is running.

### Basic commands

```bash
uv run pytest                     # run the whole suite
uv run pytest -v                  # verbose: one line per test
uv run pytest -q                  # quiet: dots only
uv run pytest tests/test_m2_account.py          # one file
uv run pytest tests/test_m2_account.py::test_duplicate_email_conflict   # one test
```

### Selecting tests

```bash
uv run pytest -k duplicate                        # keyword match on test names
uv run pytest -k "duplicate and not license"      # boolean expressions
uv run pytest -k onboarding                      # matches file names too
uv run pytest tests/test_m2_account.py tests/test_physician_onboarding.py   # multiple files
```

### Debugging failures

```bash
uv run pytest -x                     # stop at the first failure
uv run pytest --lf                   # re-run only what failed last time
uv run pytest --ff                   # run failures first, then the rest
uv run pytest -s                     # show print() output (disable capture)
uv run pytest --pdb                  # drop into the debugger on failure
uv run pytest -v -s tests/test_m2_account.py::test_duplicate_email_conflict
```

On failure, pytest prints the assertion, the values that differed, and the
HTTP response body when a test uses the `resp.text` idiom in its assertion
message (e.g. `assert resp.status_code == 201, resp.text`).

### Speed

The first run of a session pays for the database bootstrap and migrations
(~10–40s). Subsequent runs only truncate tables between tests, which is
fast.

Do **not** install `pytest-xdist` for parallel execution without changes:
all tests share one database and truncate it between tests, so parallel
workers would destroy each other's state.


## Writing new tests

1. **Decide what identity the test needs.** No account → `client`.
   Verified user → `auth()`. Multiple users → call `auth(...)` with
   different `sub`/`email` values (each call re-configures the override;
   the last call before a request is the one that applies).

2. **Create prerequisite state through the API**, the way real users would.
   The flow fixtures are the template:

   ```python
   @pytest.fixture
   def patient_client(auth):
       resp = auth().post(
           "/users/me/create-m2-account",
           json={
               "first_name": "Jane",
               "last_name": "Doe",
               "role": "patient",
               "sex": "Female",
               "dob": "2006-11-01",
           },
       )
       assert resp.status_code == 201, resp.text
       return auth()
   ```

3. **Assert status codes first, then the response body.** The
   `assert resp.status_code == 201, resp.text` pattern (note the `, resp.text`)
   makes failures show the actual error body instead of just "201 != 422".

4. **Test the failure paths too** — 401/403/404/409/422 are where most
   regressions hide.

## Troubleshooting

- **`ModuleNotFoundError: No module named 'app'`** — run pytest from the
  project root (`pythonpath = ["."]` is configured in `pyproject.toml`).
- **Connection errors** — make sure Docker/PostgreSQL is running and
  `DATABASE_URL` in `.env` is correct.
- **Migration failure on session start** — the test database is built by
  replaying the full Alembic chain, so a failure there means a migration is
  not replayable on a fresh database (a real bug, not a test problem).
- **Weird schema errors or stale columns in the test DB** — drop it; it is
  rebuilt from migrations on the next run:

  ```bash
  uv run python -c "
  import asyncio, os
  from pathlib import Path
  from urllib.parse import urlsplit, urlunsplit
  from dotenv import dotenv_values
  from sqlalchemy import text
  from sqlalchemy.ext.asyncio import create_async_engine

  root = Path('.').resolve()
  url = os.environ.get('DATABASE_URL') or dotenv_values(root / '.env').get('DATABASE_URL')
  parts = urlsplit(url)
  db_name = parts.path.strip('/').split('/')[0] + '_test'
  server = urlunsplit(parts._replace(path='/postgres'))

  async def main():
      engine = create_async_engine(server, isolation_level='AUTOCOMMIT')
      async with engine.connect() as conn:
          await conn.execute(text(f'DROP DATABASE IF EXISTS \"{db_name}\" WITH (FORCE)'))
      await engine.dispose()

  asyncio.run(main())
  "
  ```

## Manual / exploratory testing (with real Auth0)

When you want to exercise endpoints by hand on `/docs` or in Postman:

1. Get a real access token:
   - **Auth0 Dashboard → APIs → your API → Test tab** — copy the generated
     token (easiest), or
   - the token endpoint with the Password grant (`grant_type: "password"`,
     needs the grant enabled on your Auth0 application and an existing user).
2. In Swagger UI (`http://localhost:8000/docs`): click **Authorize**, paste
   the token (no "Bearer " prefix).
3. In Postman: collection → Authorization → Type: **Bearer Token** → paste.

Note: `POST /users/me/create-m2-account` additionally requires the custom
claims `https://mesquared.app/claims/email` and
`https://mesquared.app/claims/email_verified` in the token — make sure your
Auth0 action/rule adds them to access tokens, otherwise the endpoint
returns 403 even with a valid token.

