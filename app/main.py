from contextlib import asynccontextmanager
import os

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi_plugin.fast_api_client import Auth0FastAPI

from app.api.routes.health import router as health_router
from app.api.routes.patient import router as patient_router  # Import the patient router
from app.api.routes.physician import router as physician_router # Import the physician router
from app.api.routes.lab_results_bio_extract import router as extract_biomarkers_from_lab_results
from app.api.routes.vitals_bio_extract import router as extract_vitals_from_visit_summary
from app.core.db import engine

load_dotenv()

auth0_domain = os.environ.get("AUTH0_DOMAIN", "").strip()
auth0_audience = os.environ.get("AUTH0_AUDIENCE", "").strip()
if not auth0_domain or auth0_domain.lower() in {"null", "none"}:
    raise RuntimeError("AUTH0_DOMAIN must be set to your Auth0 tenant domain.")
if "://" in auth0_domain:
    raise RuntimeError("AUTH0_DOMAIN must not include a URL scheme.")
if not auth0_audience or auth0_audience.lower() in {"null", "none"}:
    raise RuntimeError("AUTH0_AUDIENCE must be set to your Auth0 API identifier.")

auth0 = Auth0FastAPI(domain=auth0_domain, audience=auth0_audience)


async def require_authorization_header(request: Request) -> None:
    if not request.headers.get("authorization", "").strip():
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
CORSMiddleware,
allow_origins=["http://localhost:8081"], # Or ["*"] for local development
allow_credentials=True,
allow_methods=["*"],
allow_headers=["*"],
)

# Register the routers to the application
app.include_router(health_router)
app.include_router(patient_router)  
app.include_router(physician_router)
app.include_router(extract_biomarkers_from_lab_results)
app.include_router(extract_vitals_from_visit_summary)


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.get("/api/public")
async def public():
    return {
        "message": "Hello from a public endpoint! You don't need to be authenticated to see this."
    }


@app.get("/api/private")
async def private(
    _: None = Depends(require_authorization_header),
    claims: dict = Depends(auth0.require_auth()),
):
    return {
        "message": "Hello from a private endpoint! You need to be authenticated to see this.",
        "user_id": claims.get("sub"),
    }


@app.get("/api/private-scoped")
async def private_scoped(
    _: None = Depends(require_authorization_header),
    claims: dict = Depends(auth0.require_auth(scopes="read:messages")),
):
    return {
        "message": "Hello from a private endpoint! You need to be authenticated and have a scope of read:messages to see this.",
        "user_id": claims.get("sub"),
    }