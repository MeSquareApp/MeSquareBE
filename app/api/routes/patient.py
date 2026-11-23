## Test if Patients route works when we get data in db

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.deps import get_current_patient
from app.api.schemas.patient import (
    BiomarkerLogResponse,
    LinkPhysicianRequest,
    PatientProfileResponse,
    PatientUpdate,
)
from app.api.schemas.twin import DigitalTwinStateResponse, TwinStateRead
from app.core.db import get_db
from app.models.associations import AccessStatusEnum, PatientPhysician
from app.models.health import RawBiomarkerLog, Twin
from app.models.users import Patient
from app.services import twin_service
from app.services.ml_engine_client import (
    MLEngineResponseError,
    MLEngineTimeout,
    MLEngineUnavailable,
)

router = APIRouter(prefix="/patients", tags=["Patients"])


@router.get("/me/profile", response_model=PatientProfileResponse)
async def get_patient_profile(
    patient: Patient = Depends(get_current_patient),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Patient)
        .options(joinedload(Patient.user))
        .where(Patient.user_id == patient.user_id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail="Patient profile not found.")
    return profile


@router.put("/me/profile", response_model=PatientProfileResponse)
async def update_patient_profile(
    profile_update: PatientUpdate,
    patient: Patient = Depends(get_current_patient),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Patient)
        .options(joinedload(Patient.user))
        .where(Patient.user_id == patient.user_id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail="Patient profile not found.")

    for key, value in profile_update.model_dump(exclude_unset=True).items():
        setattr(profile, key, value)

    try:
        await db.commit()
    except IntegrityError:
        # Defensive: constraint violation on update (e.g. concurrent modification).
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Profile update failed.",
        )
    await db.refresh(profile)
    return profile


def _twin_to_read(twin: Twin) -> TwinStateRead:
    """Shape a persisted Twin row into the typed read response."""
    return TwinStateRead(
        patient_id=str(twin.patient_id),
        last_updated=twin.last_updated.isoformat() if twin.last_updated else None,
        state=DigitalTwinStateResponse.model_validate(twin.t_zero_state),
    )


async def _sync_or_http(patient_id, db: AsyncSession) -> Twin:
    """Run a twin sync, translating service/engine errors into HTTP errors."""
    try:
        return await twin_service.sync_patient_twin(patient_id, db)
    except twin_service.PatientNotForecastable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except twin_service.PatientNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MLEngineTimeout as exc:
        raise HTTPException(
            status_code=504, detail="The forecasting service timed out."
        ) from exc
    except MLEngineUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="The forecasting service is currently unavailable.",
        ) from exc
    except MLEngineResponseError as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "The forecasting service returned an error "
                f"(HTTP {exc.status_code})."
            ),
        ) from exc


@router.get("/me/twin", response_model=TwinStateRead)
async def get_patient_twin(
    compute: bool = Query(
        False,
        description="Force a fresh recomputation even if a saved state exists.",
    ),
    patient: Patient = Depends(get_current_patient),
    db: AsyncSession = Depends(get_db),
):
    """Return the patient's digital twin state.

    Reads the cached state when one exists. If none exists yet, or if
    ``compute=true`` is passed, the state is computed and saved first.
    """
    result = await db.execute(select(Twin).where(Twin.patient_id == patient.user_id))
    twin = result.scalar_one_or_none()

    if twin is None or compute:
        twin = await _sync_or_http(patient.user_id, db)

    return _twin_to_read(twin)


@router.post("/me/twin/sync", response_model=TwinStateRead)
async def sync_patient_twin(
    patient: Patient = Depends(get_current_patient),
    db: AsyncSession = Depends(get_db),
):
    """Recompute the patient's digital twin state and return the saved result."""
    twin = await _sync_or_http(patient.user_id, db)
    return _twin_to_read(twin)


@router.get("/me/biomarkers", response_model=List[BiomarkerLogResponse])
async def get_patient_biomarkers(
    patient: Patient = Depends(get_current_patient),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RawBiomarkerLog)
        .where(RawBiomarkerLog.patient_id == patient.user_id)
        .order_by(RawBiomarkerLog.measured_at.desc())
    )
    return result.scalars().all()


@router.post("/me/physicians", status_code=201)
async def link_physician_to_patient(
    payload: LinkPhysicianRequest,
    patient: Patient = Depends(get_current_patient),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PatientPhysician).where(
            PatientPhysician.patient_id == patient.user_id,
            PatientPhysician.physician_id == payload.physician_id,
        )
    )
    existing_link = result.scalar_one_or_none()

    if existing_link:
        if existing_link.status == AccessStatusEnum.revoked:
            existing_link.status = AccessStatusEnum.active
            await db.commit()
            return {"message": "Physician access successfully restored."}
        raise HTTPException(
            status_code=400,
            detail="Physician is already actively linked to this patient.",
        )

    db.add(
        PatientPhysician(
            patient_id=patient.user_id,
            physician_id=payload.physician_id,
        )
    )
    await db.commit()
    return {"message": "Physician successfully linked to patient."}


@router.patch("/me/physicians/{physician_id}/revoke")
async def revoke_physician_access(
    physician_id: UUID,
    patient: Patient = Depends(get_current_patient),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PatientPhysician).where(
            PatientPhysician.patient_id == patient.user_id,
            PatientPhysician.physician_id == physician_id,
        )
    )
    link = result.scalar_one_or_none()
    if link is None:
        raise HTTPException(
            status_code=404,
            detail="Link between patient and physician not found.",
        )
    if link.status == AccessStatusEnum.revoked:
        raise HTTPException(
            status_code=400,
            detail="Physician access is already revoked.",
        )

    link.status = AccessStatusEnum.revoked
    await db.commit()
    return {"message": "Physician access successfully revoked."}
