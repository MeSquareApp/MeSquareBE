# MeSqureBE .env Setup

Create file called ".env"

Paste into file:
```
DATABASE_URL=postgresql+asyncpg://postgres.wamrrpwykkcuowdyewxd:mequare2026@aws-0-us-east-2.pooler.supabase.com:5432/postgres?ssl=require
LLAMA_CLOUD_API_KEY='your-key'
AUTH0_DOMAIN=dev-tk23yhyc2e62i1a5.us.auth0.com
AUTH0_AUDIENCE=https://mesquared-api-endpoint
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

`POST /users/me/create-m2-account` creates only the authenticated user's `users` row.
The request body contains `first_name`, `last_name`, and a selected `role`
(`patient`, `physician`, or `admin`). The API takes the issuer and subject from
the verified token, email from a verified Auth0 access-token claim, and
generates the UUID in the ORM. It sets `created_at` and `last_used_at` to the
same time. Existing identities or emails return 409. It does not create a
patient, physician, or admin profile; endpoints requiring those profiles will
remain unavailable until those profile rows are created separately. Admin
self-registration is rejected by the API even though the form displays the
current role choices; admin accounts must be provisioned through a trusted
administrative process.

Every data-touching endpoint requires an `Authorization: Bearer <token>`
header and resolves the caller through the `verify_auth0_token` →
`get_current_user` dependency chain; requests without a valid token receive
401. The `/health` endpoint (for uptime probes and container healthchecks),
the `/` root, and the auto-generated API docs (`/docs`, `/redoc`,
`/openapi.json`) are intentionally left public because they expose no user
data.

## Note on Testing Protected API on the Docs

If you want to test any API that is protected by needing a bearer token,
you need to first login/create an account through the front end. After
that, once you're on dashboard logged in you can press Ctrl + Shift + I
to get into the Dev Tools. Once you're in the Dev Tools, Navigate to 
Application > Storage > Local storage > and check the second key. From 
there check the value/body and look for access_token. Copy that w/o the
"" and paste into the Authorize field in the FastAPI docs. Now you're 
good to go for testing.
