from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes.health import router as health_router
from app.api.routes.patient import router as patient_router  # Import the patient router
from app.api.routes.physician import router as physician_router # Import the physician router
from app.api.routes.lab_results_bio_extract import router as extract_biomarkers_from_lab_results
from app.api.routes.vitals_bio_extract import router as extract_vitals_from_visit_summary
from app.core.db import engine


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