# MeSqureBE .env Setup

Create file called ".env"

Paste into file:
``` m
DATABASE_URL=
LLAMA_CLOUD_API_KEY='your-key'
AUTH0_DOMAIN=
AUTH0_AUDIENCE=
```
# MeSquareBE

Run 
```bash
uv add uvicorn
```
Start your Docker app, then run this command:
```bash
docker compose up --build
```

If you want to run app locally with no docker, just run these 2 commands
```bash
uv sync
uv run fastapi dev
```

Once app runs, go to this link: http://localhost:8000/

For documentation, go to this link: http://localhost:8000/docs

## Auth0 API authentication

The backend reads `AUTH0_DOMAIN` and `AUTH0_AUDIENCE` from `.env`. Set the domain
without `https://`, and set the audience to the API identifier configured in
Auth0. `.env` is ignored by Git; do not commit it.

From `MeSquareBE`, activate the existing environment in Command Prompt and run
the API:

```bat
.venv\Scripts\activate.bat
uvicorn app.main:app --reload
```

`app.core.security.verify_auth0_token` is the shared FastAPI dependency for
validating Auth0 bearer access tokens. It resolves the tenant signing key from
the tenant's JWKS endpoint and verifies the signature, RS256 algorithm,
configured audience, and issuer before returning claims. Missing or invalid
tokens receive a generic 401 response.

The sample `/api/public`, `/api/private`, `/api/private-scoped`, and `/api/me`
routes have been removed. Patient routes now use `/patients/me/...` and derive
the patient from the verified Auth0 identity. Physician routes use
`/physicians/me/...`, and access to a patient's data requires an active
patient-physician relationship. Health-data upload routes use
`/health-data/me/...` and are restricted to the authenticated patient's own
record. The former routes that accepted the caller's `user_id` are no longer
registered.

The `users` SQLAlchemy model expects non-nullable `auth0_issuer` and
`auth0_subject` columns plus a nullable `last_used_at` column. A unique
constraint on `(auth0_issuer, auth0_subject)` identifies the one Auth0 identity
linked to a MeSquared user; every user must have a linked identity because
authentication is Auth0-only. The shared `get_current_user` dependency validates
the token first, then resolves the verified issuer and subject to the internal
`users.id`; unmapped identities receive 404. The Alembic migration
`36043d5dc19e` adds these columns, drops the legacy `username` column, and
removes pre-Auth0 users (they cannot authenticate once JWT validation is
enforced).

`last_used_at` is modeled as a nullable timestamp but is not updated by the
current-user lookup: an authenticated API request is not necessarily a login.
Update it only when a trusted login/onboarding event is implemented.

The database schema must include these Auth0 columns before protected
user-specific routes can resolve a MeSquared account. The application does not
create or migrate these columns at startup.
