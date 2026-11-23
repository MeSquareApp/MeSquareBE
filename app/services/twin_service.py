"""Orchestrates a twin computation and persists the result.

This is the heart of the pipeline (flow steps 2-5): read the patient and their
records, translate them, call the ML Engine, and upsert the ``twins`` row so the
state is cached for fast reads. Everything above (routes) and below (client,
adapter) is wired together here.
"""

from __future__ import annotations

import logging
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.twin import DigitalTwinStateResponse
from app.core.db import SessionLocal
from app.models.health import RawBiomarkerLog, Twin
from app.models.users import Patient
from app.services import twin_adapter
from app.services.ml_engine_client import (
    MLEngineClient,
    MLEngineError,
    MLEngineResponseError,
    MLEngineTimeout,
    MLEngineUnavailable,
)

__all__ = [
    "sync_patient_twin",
    "recompute_twin_in_background",
    "TwinServiceError",
    "PatientNotFound",
    "PatientNotForecastable",
    "MLEngineError",
    "MLEngineResponseError",
    "MLEngineTimeout",
    "MLEngineUnavailable",
]

logger = logging.getLogger(__name__)

# The ML Engine's PREVENT models are validated for ages 20-79; its schema rejects
# anything outside that range. We check here so we never make a doomed call.
MIN_AGE = 20
MAX_AGE = 79


class TwinServiceError(Exception):
    """Base class for twin orchestration errors."""


class PatientNotFound(TwinServiceError):
    """No patient row exists for the given id."""


class PatientNotForecastable(TwinServiceError):
    """The patient cannot be forecast (e.g. age outside the supported range)."""


async def sync_patient_twin(
    patient_id: UUID,
    db: AsyncSession,
    *,
    client: MLEngineClient | None = None,
    as_of: date | None = None,
) -> Twin:
    """Compute and persist the digital twin state for one patient.

    Args:
        patient_id: The patient's ``user_id``.
        db: Async DB session.
        client: ML Engine client (injectable for tests). Defaults to a new one.
        as_of: Date to compute against. Defaults to today.

    Returns:
        The upserted ``Twin`` row, with ``t_zero_state`` holding the full state.

    Raises:
        PatientNotFound: No such patient.
        PatientNotForecastable: Patient age is outside the supported range.
        MLEngineError: Any failure talking to the ML Engine (timeout,
            unavailable, or a non-2xx response).
    """
    client = client or MLEngineClient()
    today = as_of or date.today()

    patient = await db.get(Patient, patient_id)
    if patient is None:
        raise PatientNotFound(f"No patient with id {patient_id}.")

    age = twin_adapter._age_on(patient.date_of_birth, today)
    if not MIN_AGE <= age <= MAX_AGE:
        raise PatientNotForecastable(
            f"Forecasts are currently supported for patients aged {MIN_AGE}-{MAX_AGE}."
        )

    result = await db.execute(
        select(RawBiomarkerLog)
        .where(RawBiomarkerLog.patient_id == patient_id)
        .order_by(RawBiomarkerLog.measured_at)
    )
    logs = result.scalars().all()

    payload = {
        "user_id": str(patient_id),
        "profile": twin_adapter.build_patient_profile(patient, as_of=today),
        "records": twin_adapter.build_records_payload(logs),
        "as_of": today.isoformat(),
    }

    raw_state = await client.post_twin_state(payload)

    # Validate against our mirror of the engine's schema, then store JSON-safe.
    state = DigitalTwinStateResponse.model_validate(raw_state)
    state_json = state.model_dump(mode="json")

    twin = await _upsert_twin(db, patient_id, state_json)
    return twin


async def _upsert_twin(
    db: AsyncSession, patient_id: UUID, state_json: dict
) -> Twin:
    """Insert or update the single ``twins`` row for this patient."""
    existing = await db.execute(select(Twin).where(Twin.patient_id == patient_id))
    twin = existing.scalar_one_or_none()

    if twin is None:
        twin = Twin(patient_id=patient_id, t_zero_state=state_json)
        db.add(twin)
    else:
        twin.t_zero_state = state_json

    await db.commit()
    await db.refresh(twin)
    return twin


async def recompute_twin_in_background(patient_id: UUID) -> None:
    """Best-effort twin recompute for a background task.

    Opens its own DB session (the request's session is closed by the time a
    FastAPI background task runs) and never raises: a failed recompute must not
    break the extraction request that scheduled it. The next read with
    ``compute=true`` (or the next extraction) will try again.
    """
    try:
        async with SessionLocal() as db:
            await sync_patient_twin(patient_id, db)
    except PatientNotForecastable as exc:
        logger.info("Skipped twin recompute for %s: %s", patient_id, exc)
    except (TwinServiceError, MLEngineError) as exc:
        logger.warning("Background twin recompute failed for %s: %s", patient_id, exc)
    except Exception:  # pragma: no cover - defensive catch-all
        logger.exception("Unexpected error in background twin recompute for %s", patient_id)
