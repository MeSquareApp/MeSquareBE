import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.users import Physician, Patient
from app.models.associations import PhysicianClinic, PatientPhysician
from app.api.schemas.physician import PhysicianProfileResponse, PatientDataForPhysicianResponse
from app.core.db import get_db

router = APIRouter(prefix="/physicians", tags=["Physicians"])

@router.get("/{user_id}/profile", response_model=PhysicianProfileResponse)
async def get_physician_profile(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    [DEV ONLY] Retrieve a physician's profile, including their identity and assigned clinics.
    """
    stmt = (
        select(Physician)
        .options(
            joinedload(Physician.user),
            # Chain the joinedload to fetch the junction table, then the actual clinic
            joinedload(Physician.clinics).joinedload(PhysicianClinic.clinic)
        )
        .where(Physician.user_id == user_id)
    )
    result = await db.execute(stmt)
    physician = result.unique().scalar_one_or_none()

    if not physician:
        raise HTTPException(status_code=404, detail="Physician profile not found.")

    return physician

@router.get("/{user_id}/patients/{patient_id}/data", response_model=PatientDataForPhysicianResponse)
async def view_patient_data(
    user_id: uuid.UUID,
    patient_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    [DEV ONLY] Physician views a patient's profile, twin, and biomarkers (requires active link).
    """
    # 1. Verify authorization (active link exists)
    auth_stmt = select(PatientPhysician).where(
        PatientPhysician.physician_id == user_id,
        PatientPhysician.patient_id == patient_id,
        PatientPhysician.status == "active"
    )
    auth_result = await db.execute(auth_stmt)
    if not auth_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Not authorized to view this patient's data.")

    # 2. Fetch the patient data with eagerly loaded relationships
    patient_stmt = (
        select(Patient)
        .options(
            joinedload(Patient.user),
            joinedload(Patient.twin),
            joinedload(Patient.biomarker_logs)
        )
        .where(Patient.user_id == patient_id)
    )
    patient_result = await db.execute(patient_stmt)
    patient = patient_result.unique().scalar_one_or_none()

    if not patient:
        raise HTTPException(status_code=404, detail="Patient data not found.")

    # Sort biomarkers so the most recent are first in the response
    sorted_biomarkers = sorted(patient.biomarker_logs, key=lambda x: x.measured_at, reverse=True)

    return {
        "profile": patient,
        "twin": patient.twin,
        "recent_biomarkers": sorted_biomarkers
    }


@router.delete("/{user_id}/patients/{patient_id}", status_code=204)
async def remove_patient_from_roster(
    user_id: uuid.UUID,
    patient_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    [DEV ONLY] Physician removes a patient from their clinic roster.
    """
    stmt = select(PatientPhysician).where(
        PatientPhysician.physician_id == user_id,
        PatientPhysician.patient_id == patient_id
    )
    result = await db.execute(stmt)
    link = result.scalar_one_or_none()

    if not link:
        raise HTTPException(status_code=404, detail="Patient is not in your roster.")

    # Hard delete the relationship row
    await db.delete(link)
    await db.commit()
    
    return None