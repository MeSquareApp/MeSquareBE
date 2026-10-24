import asyncio
import logging
import os
import tempfile
import time
import uuid
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from llama_cloud import AsyncLlamaCloud
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.api.schemas.file_extract_schema import BiomarkerExtraction, biomarker_extraction_schema
from app.api.schemas.patient import BiomarkerLogResponse
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

# Canonical unit for each biomarker field of BiomarkerExtraction, used when
# persisting rows into raw_biomarker_logs.
BIOMARKER_UNITS = {
    "non_hdl": "mg/dL",
    "hdl": "mg/dL",
    "hba1c": "%",
    "egfr": "mL/min/1.73m^2",
}


@router.post("/{user_id}/extract-biomarkers-from-lab-results", response_model=List[BiomarkerLogResponse])
async def extract_biomarkers_from_file(
    user_id: uuid.UUID,
    file: UploadFile = File(
        ...,
        description="A blood test lab results document (PDF, JPEG, PNG, or TXT) to extract biomarkers from",
    ),
    db: AsyncSession = Depends(get_db),
) -> List[BiomarkerLogResponse]:
    """
    [DEV ONLY] Extract biomarkers from an uploaded lab results document for a patient,
    persist them as raw biomarker logs, and return the saved logs.
    """
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Unsupported file type. Please upload a PDF, JPEG, PNG, or TXT file.",
        )

    # Fail fast if the patient does not exist, before spending LlamaCloud credits.
    result = await db.execute(select(Patient.user_id).where(Patient.user_id == user_id))
    if result.scalar_one_or_none() is None:
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
                "data_schema": biomarker_extraction_schema,
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
        extracted = BiomarkerExtraction.model_validate(job.extract_result)

        # One row per biomarker: only persist the fields the model actually found.
        biomarker_values = extracted.model_dump(exclude_none=True)
        if not biomarker_values:
            raise HTTPException(status_code=422, detail="No biomarkers could be extracted from the file.")

        measured_at = datetime.now(timezone.utc)
        logs = [
            RawBiomarkerLog(
                patient_id=user_id,
                biomarker_abbr=abbr,
                value=value,
                unit=BIOMARKER_UNITS[abbr],
                measurement_method="blood_test_lab_report_upload",
                measured_at=measured_at,
            )
            for abbr, value in biomarker_values.items()
        ]
        db.add_all(logs)
        await db.commit()
        logger.info("Saved %d biomarker logs for patient %s", len(logs), user_id)

        return logs

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
