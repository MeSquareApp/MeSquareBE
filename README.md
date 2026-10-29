# MeSqureBE .env Setup

Create file called ".env"

Paste into file:
DATABASE_URL=postgresql+asyncpg://postgres.wamrrpwykkcuowdyewxd:mequare2026@aws-0-us-east-2.pooler.supabase.com:5432/postgres?ssl=require
LLAMA_CLOUD_API_KEY='your-key'
AUTH0_DOMAIN=dev-tk23yhyc2e62i1a5.us.auth0.com
AUTH0_AUDIENCE=https://mesquared-api-endpoint

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

The Auth0 SDK example endpoints are:

- `GET /api/public` does not require a token.
- `GET /api/private` requires a valid access token for this API.
- `GET /api/private-scoped` requires a valid access token with the
  `read:messages` permission.

To configure the scoped endpoint, open **Applications > APIs** in the Auth0
Dashboard, select the API matching `AUTH0_AUDIENCE`, and add the
`read:messages` and `write:messages` permissions. The sample scoped endpoint
requires `read:messages`. Use the API's **Test** tab to obtain an access token,
then try these single-line requests:

```bash
curl http://localhost:8000/api/public
curl -X GET http://localhost:8000/api/private -H "authorization: Bearer YOUR_ACCESS_TOKEN"
curl -X GET http://localhost:8000/api/private-scoped -H "authorization: Bearer YOUR_ACCESS_TOKEN"
```

In the existing backend, only these Auth0 example routes are protected. The
existing patient, physician, and health-data routes retain their prior access
behavior.
