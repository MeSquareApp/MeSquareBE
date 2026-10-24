import asyncio
import logging
import os
import tempfile
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from llama_cloud import AsyncLlamaCloud
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.api.schemas.file_extract_schema import VitalsExtraction, vitals_extraction_schema
from app.api.schemas.patient import VitalsLogResponse
from app.models.health import RawBiomarkerLog
from app.models.users import Patient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health-data", tags=["Data Extraction"])

# Initialize the async client so network calls never block the event loop.
client = AsyncLlamaCloud(api_key=settings.llama_cloud_api_key)

ALLOWED_CONTENT_TYPES = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "text/plain": ".txt",
}

# Reject uploads larger than 20 MB (read with a limit so they never fully hit memory).
MAX_FILE_SIZE = 20 * 1024 * 1024

# Polling configuration for the extraction job.
POLL_INTERVAL_SECONDS = 2
EXTRACTION_TIMEOUT_SECONDS = 300

TERMINAL_JOB_STATUSES = ("COMPLETED", "FAILED", "CANCELLED")

# The extraction schema reports imperial units; convert to the metric baseline columns.
INCHES_TO_CM = 2.54
POUNDS_TO_KG = 2.20462


@router.post("/{user_id}/extract-vitals-from-visit-summary", response_model=VitalsLogResponse)
async def extract_vitals_from_visit_summary(
    user_id: uuid.UUID,
    file: UploadFile = File(
        ...,
        description="A visit summary document (PDF, JPEG, PNG, or TXT) to extract vitals from",
    ),
    db: AsyncSession = Depends(get_db),
) -> VitalsLogResponse:
    """
    [DEV ONLY] Extract vitals such as height, weight and systolic blood pressure from an uploaded visit
    summary document for a patient, persist the systolic blood pressure as a raw biomarker log, update the
    patient's baseline height (cm) and weight (kg), and return the extracted vitals.
    """
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Unsupported file type. Please upload a PDF, JPEG, PNG, or TXT file.",
        )

    # Fail fast if the patient does not exist, before spending LlamaCloud credits.
    # Fetch the full entity (not just the id) so we can update its baseline vitals below.
    patient = (await db.execute(select(Patient).where(Patient.user_id == user_id))).scalar_one_or_none()
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found.")

    # Read the upload with a size cap so oversized files never fully load into memory.
    file_bytes = await file.read(MAX_FILE_SIZE + 1)
    if not file_bytes:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File is too large. Maximum allowed size is {MAX_FILE_SIZE // (1024 * 1024)} MB.",
        )

    # Derive the temp file suffix from the validated content type instead of trusting
    # the client-provided filename.
    file_ext = ALLOWED_CONTENT_TYPES[file.content_type]
    temp_fd, temp_filepath = tempfile.mkstemp(suffix=file_ext)
    # Close the descriptor immediately: we only care about the path, and this avoids
    # leaking descriptors or closing an already-closed one later.
    os.close(temp_fd)

    try:
        with open(temp_filepath, "wb") as f:
            f.write(file_bytes)

        # 1. Upload the file to LlamaCloud
        logger.info("Uploading file %r (%d bytes) to LlamaCloud", file.filename, len(file_bytes))
        file_obj = await client.files.create(file=temp_filepath, purpose="extract")

        # 2. Create the extraction job using the generated schema
        job = await client.extract.create(
            file_input=file_obj.id,
            configuration={
                "data_schema": vitals_extraction_schema,
                "tier": "agentic",
                "cite_sources": True,          # Enable citations
                "confidence_scores": True,     # Enable confidence scores
            },
        )
        logger.info("Started extraction job %s for uploaded file %r", job.id, file.filename)

        # 3. Poll for completion without blocking the event loop, with a timeout
        #    so a stuck job can never hang the request forever.
        deadline = time.monotonic() + EXTRACTION_TIMEOUT_SECONDS
        while job.status not in TERMINAL_JOB_STATUSES:
            if time.monotonic() >= deadline:
                logger.error("Extraction job %s timed out after %s seconds", job.id, EXTRACTION_TIMEOUT_SECONDS)
                raise HTTPException(status_code=504, detail="Extraction timed out. Please try again later.")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            job = await client.extract.get(job.id)

        if job.status != "COMPLETED":
            logger.warning("Extraction job %s ended with status %s", job.id, job.status)
            raise HTTPException(
                status_code=502,
                detail=f"LlamaCloud extraction failed with status: {job.status}",
            )

        if not job.extract_result:
            logger.warning("Extraction job %s completed but returned no data", job.id)
            raise HTTPException(status_code=502, detail="Extraction completed but returned no data.")

        logger.info("Extraction job %s completed successfully", job.id)

        # Re-validate the LLM output against the schema so malformed extractions
        # fail loudly here instead of polluting the database downstream.
        extracted = VitalsExtraction.model_validate(job.extract_result)

        # Each vital is optional: only persist the fields the model actually found.
        if extracted.height is None and extracted.weight is None and extracted.systolic_bp is None:
            raise HTTPException(status_code=422, detail="No vitals could be extracted from the file.")

        measured_at = datetime.now(timezone.utc)

        # Systolic blood pressure is a longitudinal measurement: log it as a time series.
        if extracted.systolic_bp is not None:
            db.add(
                RawBiomarkerLog(
                    patient_id=user_id,
                    biomarker_abbr="systolic_bp",
                    value=extracted.systolic_bp,
                    unit="mmHg",
                    measurement_method="visit_summary_upload",
                    measured_at=measured_at,
                )
            )

        # Height and weight are physiological constants: update the patient's baseline.
        # The extraction schema reports inches and pounds, so convert to metric first.
        height_cm = extracted.height * INCHES_TO_CM if extracted.height is not None else None
        weight_kg = extracted.weight / POUNDS_TO_KG if extracted.weight is not None else None
        if height_cm is not None:
            patient.baseline_height_cm = height_cm
        if weight_kg is not None:
            patient.baseline_weight_kg = weight_kg

        await db.commit()
        logger.info(
            "Saved vitals for patient %s (height_cm=%s, weight_kg=%s, systolic_bp=%s)",
            user_id,
            height_cm,
            weight_kg,
            extracted.systolic_bp,
        )

        # Build the response from the local values: ORM objects may be expired after
        # commit, and re-reading them would trigger another lazy query.
        return VitalsLogResponse(
            height_cm=height_cm,
            weight_kg=weight_kg,
            systolic_bp=extracted.systolic_bp,
        )

    except HTTPException:
        # Let intentional, already-shaped errors (400/413/415/502/504) pass through
        # instead of re-wrapping them as a generic 500.
        raise
    except Exception:
        # Log the full traceback server-side; keep the client-facing message generic.
        logger.exception("Unexpected error while extracting biomarkers from file %r", file.filename)
        raise HTTPException(status_code=500, detail="Extraction failed. Please try again later.")

    finally:
        # Ensure the temporary file is deleted
        await file.close()
        if os.path.exists(temp_filepath):
            os.remove(temp_filepath)
