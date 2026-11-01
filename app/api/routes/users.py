from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import verified_identity
from app.api.schemas.user import OnboardedUserResponse, OnboardingRequest
from app.core.db import get_db
from app.core.security import verify_auth0_token
from app.models.users import Admin, Patient, Physician, RoleEnum, User

router = APIRouter(prefix="/users", tags=["Users"])


def _role_profile(user: User, payload: OnboardingRequest) -> object:
    """Build the role-specific row linked to the new user."""
    if payload.role == RoleEnum.patient:
        return Patient(
            user=user,
            date_of_birth=payload.date_of_birth,
            biological_sex=payload.biological_sex,
            baseline_height_cm=payload.baseline_height_cm,
            baseline_weight_kg=payload.baseline_weight_kg,
            allergies=payload.allergies,
            medical_conditions=payload.medical_conditions,
        )
    if payload.role == RoleEnum.physician:
        return Physician(
            user=user,
            medical_license_number=payload.medical_license_number,
            specialty=payload.specialty,
        )
    return Admin(user=user, access_level=payload.access_level)


@router.post("/me/onboarding", status_code=status.HTTP_201_CREATED, response_model=OnboardedUserResponse)
async def onboard_current_user(
    payload: OnboardingRequest,
    token_payload: dict[str, object] = Depends(verify_auth0_token),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Self-register the authenticated Auth0 identity as a MeSquared user.

    The Auth0 issuer and subject are taken from the verified token, never from
    the request body. For now every role may self-register; role-gating for
    physicians and admins will be added later.
    """
    issuer, subject = verified_identity(token_payload)

    existing_identity = await db.execute(
        select(User).where(
            User.auth0_issuer == issuer,
            User.auth0_subject == subject,
        )
    )
    if existing_identity.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This Auth0 identity is already linked to a MeSquared account.",
        )

    existing_email = await db.execute(select(User).where(User.email == payload.email))
    if existing_email.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A MeSquared account with this email already exists.",
        )

    user = User(
        email=payload.email,
        first_name=payload.first_name,
        last_name=payload.last_name,
        role=payload.role,
        auth0_issuer=issuer,
        auth0_subject=subject,
        # Onboarding is a trusted event, so it counts as the first use.
        last_used_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.add(_role_profile(user, payload))

    try:
        await db.commit()
    except IntegrityError:
        # Concurrent onboarding raced us for the identity, email, or license.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This account could not be created; it may already exist.",
        )
    await db.refresh(user)
    return user