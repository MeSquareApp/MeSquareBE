## Test if Physician route works when we get data in db
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.deps import get_current_physician
from app.api.schemas.physician import (
    PatientDataForPhysicianResponse,
    PhysicianProfileResponse,
    PhysicianUpdate,
)
from app.core.db import get_db
from app.models.associations import AccessStatusEnum, PatientPhysician, PhysicianClinic
from app.models.users import Patient, Physician

router = APIRouter(prefix="/physicians", tags=["Physicians"])


@router.put("/me/profile", response_model=PhysicianProfileResponse)
async def update_physician_profile(
    profile_update: PhysicianUpdate,
    physician: Physician = Depends(get_current_physician),
    db: AsyncSession = Depends(get_db),
) -> Physician:
    """
    Update the authenticated physician's profile.

    This is the endpoint the onboarding form submits to: it fills in the
    license and specialty that were not collected at account creation.
    Only the provided fields are applied.
    """
    result = await db.execute(
        select(Physician)
        .options(
            joinedload(Physician.user),
            joinedload(Physician.clinics).joinedload(PhysicianClinic.clinic),
        )
        .where(Physician.user_id == physician.user_id)
    )
    profile = result.unique().scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail="Physician profile not found.")

    updates = profile_update.model_dump(exclude_unset=True)

    new_license = updates.get("medical_license_number")
    if new_license is not None and new_license != profile.medical_license_number:
        duplicate_license = await db.execute(
            select(Physician).where(
                Physician.medical_license_number == new_license,
                Physician.user_id != physician.user_id,
            )
        )
        if duplicate_license.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A physician with this medical license number already exists.",
            )

    for key, value in updates.items():
        setattr(profile, key, value)

    try:
        await db.commit()
    except IntegrityError:
        # Concurrent request claimed the license number first.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Profile update failed; the license number may already be taken.",
        )

    refreshed = await db.execute(
        select(Physician)
        .options(
            joinedload(Physician.user),
            joinedload(Physician.clinics).joinedload(PhysicianClinic.clinic),
        )
        .where(Physician.user_id == physician.user_id)
    )
    return refreshed.unique().scalar_one()


@router.get("/me/profile", response_model=PhysicianProfileResponse)
async def get_physician_profile(
    physician: Physician = Depends(get_current_physician),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Physician)
        .options(
            joinedload(Physician.user),
            joinedload(Physician.clinics).joinedload(PhysicianClinic.clinic),
        )
        .where(Physician.user_id == physician.user_id)
    )
    profile = result.unique().scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail="Physician profile not found.")
    return profile


@router.get(
    "/me/patients/{patient_id}/data",
    response_model=PatientDataForPhysicianResponse,
)
async def view_patient_data(
    patient_id: UUID,
    physician: Physician = Depends(get_current_physician),
    db: AsyncSession = Depends(get_db),
):
    authorization = await db.execute(
        select(PatientPhysician).where(
            PatientPhysician.physician_id == physician.user_id,
            PatientPhysician.patient_id == patient_id,
            PatientPhysician.status == AccessStatusEnum.active,
        )
    )
    if authorization.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=403,
            detail="Not authorized to view this patient's data.",
        )

    result = await db.execute(
        select(Patient)
        .options(
            joinedload(Patient.user),
            joinedload(Patient.twin),
            joinedload(Patient.biomarker_logs),
        )
        .where(Patient.user_id == patient_id)
    )
    patient = result.unique().scalar_one_or_none()
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient data not found.")

    sorted_biomarkers = sorted(
        patient.biomarker_logs,
        key=lambda biomarker: biomarker.measured_at,
        reverse=True,
    )
    return {
        "profile": patient,
        "twin": patient.twin,
        "recent_biomarkers": sorted_biomarkers,
    }


@router.delete("/me/patients/{patient_id}", status_code=204)
async def remove_patient_from_roster(
    patient_id: UUID,
    physician: Physician = Depends(get_current_physician),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PatientPhysician).where(
            PatientPhysician.physician_id == physician.user_id,
            PatientPhysician.patient_id == patient_id,
            PatientPhysician.status == AccessStatusEnum.active,
        )
    )
    link = result.scalar_one_or_none()
    if link is None:
        raise HTTPException(
            status_code=404,
            detail="Active patient roster link not found.",
        )

    await db.delete(link)
    await db.commit()
