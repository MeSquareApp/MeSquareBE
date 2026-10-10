import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from typing import List
from app.models.health import Twin, RawBiomarkerLog
from app.api.schemas.patient import TwinResponse, BiomarkerLogResponse
from app.models.users import Patient
from app.api.schemas.patient import PatientProfileResponse, PatientUpdate
from app.models.associations import PatientPhysician
from app.api.schemas.patient import LinkPhysicianRequest
from app.core.db import get_db

router = APIRouter(prefix="/patients", tags=["Patients"])

@router.get("/{user_id}/profile", response_model=PatientProfileResponse)
async def get_patient_profile(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    [DEV ONLY] Retrieve a patient's profile data using their user_id in the path.
    """
    stmt = (
        select(Patient)
        .options(joinedload(Patient.user))
        .where(Patient.user_id == user_id)
    )
    # Async database execution requires 'await'
    result = await db.execute(stmt)
    patient = result.scalar_one_or_none()

    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found.")

    return patient


@router.put("/{user_id}/profile", response_model=PatientProfileResponse)
async def update_patient_profile(
    user_id: uuid.UUID,
    profile_update: PatientUpdate,
    db: AsyncSession = Depends(get_db)
):
    """
    [DEV ONLY] Update a patient's physiological constants using their user_id in the path.
    """
    stmt = (
        select(Patient)
        .options(joinedload(Patient.user))
        .where(Patient.user_id == user_id)
    )
    result = await db.execute(stmt)
    patient = result.scalar_one_or_none()

    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found.")

    update_data = profile_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(patient, key, value)

    # Commits and refreshes must also be awaited in async mode
    await db.commit()
    await db.refresh(patient)

    return patient


@router.get("/{user_id}/twin", response_model=TwinResponse)
async def get_patient_twin(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    [DEV ONLY] Retrieve the computed digital twin state (t_zero) for a patient.
    """
    stmt = select(Twin).where(Twin.patient_id == user_id)
    result = await db.execute(stmt)
    twin = result.scalar_one_or_none()

    if not twin:
        raise HTTPException(status_code=404, detail="Digital twin state not found for this patient.")

    return twin


@router.get("/{user_id}/biomarkers", response_model=List[BiomarkerLogResponse])
async def get_patient_biomarkers(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    [DEV ONLY] Retrieve the longitudinal time-series biomarker history for a patient.
    """
    # Order by measured_at descending to return the most recent data first
    stmt = (
        select(RawBiomarkerLog)
        .where(RawBiomarkerLog.patient_id == user_id)
        .order_by(RawBiomarkerLog.measured_at.desc())
    )
    result = await db.execute(stmt)
    
    # scalars().all() extracts the list of model instances from the AsyncResult
    biomarkers = result.scalars().all()

    return biomarkers

@router.post("/{user_id}/physicians", status_code=201)
async def link_physician_to_patient(
    user_id: uuid.UUID,
    payload: LinkPhysicianRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    [DEV ONLY] Grant a physician access to a patient's digital twin and biomarkers.
    """
    # Check if the relationship already exists
    stmt = select(PatientPhysician).where(
        PatientPhysician.patient_id == user_id,
        PatientPhysician.physician_id == payload.physician_id
    )
    result = await db.execute(stmt)
    existing_link = result.scalar_one_or_none()

    if existing_link:
        # If it exists but was revoked, reactivate it
        if existing_link.status == "revoked":
            existing_link.status = "active"
            await db.commit()
            return {"message": "Physician access successfully restored."}
        
        raise HTTPException(status_code=400, detail="Physician is already actively linked to this patient.")

    # Create a new active link
    new_link = PatientPhysician(
        patient_id=user_id,
        physician_id=payload.physician_id
    )
    
    db.add(new_link)
    await db.commit()

    return {"message": "Physician successfully linked to patient."}

@router.patch("/{user_id}/physicians/{physician_id}/revoke")
async def revoke_physician_access(
    user_id: uuid.UUID,
    physician_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    [DEV ONLY] Patient revokes a physician's access to their digital twin data.
    """
    stmt = select(PatientPhysician).where(
        PatientPhysician.patient_id == user_id,
        PatientPhysician.physician_id == physician_id
    )
    result = await db.execute(stmt)
    link = result.scalar_one_or_none()

    if not link:
        raise HTTPException(status_code=404, detail="Link between patient and physician not found.")

    if link.status == "revoked":
        raise HTTPException(status_code=400, detail="Physician access is already revoked.")

    link.status = "revoked"
    await db.commit()

    return {"message": "Physician access successfully revoked."}