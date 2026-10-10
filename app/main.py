from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.api.routes.patient import router as patient_router  # Import the patient router
from app.api.routes.physician import router as physician_router # Import the physician router
from app.core.db import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(lifespan=lifespan)

# Register the routers to the application
app.include_router(health_router)
app.include_router(patient_router)  # 2. Attach the patient endpoints
app.include_router(physician_router)


@app.get("/")
async def root():
    return {"message": "Hello World"}