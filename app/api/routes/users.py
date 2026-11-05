import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, verified_identity
from app.api.schemas.user import OnboardedUserResponse, OnboardingRequest, UserRead
from app.core.db import get_db
from app.core.security import verify_auth0_token
from app.models.users import Patient, Physician, RoleEnum, User

router = APIRouter(prefix="/users", tags=["Users"])

AUTH0_EMAIL_CLAIM = "https://mesquared.app/claims/email"
AUTH0_EMAIL_VERIFIED_CLAIM = "https://mesquared.app/claims/email_verified"


@router.get("/me", response_model=UserRead)
async def get_me(user: User = Depends(get_current_user)) -> User:
    """Return the authenticated user's MeSquared database record."""
    return user


@router.post(
    "/me/create-m2-account",
    status_code=status.HTTP_201_CREATED,
    response_model=OnboardedUserResponse,
)
async def create_m2_account(
    payload: OnboardingRequest,
    token_payload: dict[str, object] = Depends(verify_auth0_token),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Create the core MeSquared user row plus the role-specific profile row.

    The Auth0 issuer and subject are taken from the verified token, never from
    the request body. The email is taken from signed Auth0 access-token claims.
    For patients, the row is seeded with the dob and sex provided at signup;
    the remaining attributes stay NULL until the patient completes the
    onboarding form. For physicians, the row is created empty and completed
    the same way. Both rows are inserted in a single transaction.
    """
    issuer, subject = verified_identity(token_payload)
    email_claim = token_payload.get(AUTH0_EMAIL_CLAIM)
    email_verified = token_payload.get(AUTH0_EMAIL_VERIFIED_CLAIM)
    if (
        not isinstance(email_claim, str)
        or not email_claim.strip()
        or email_verified is not True
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A verified Auth0 email is required to create an account.",
        )
    email = email_claim.strip().lower()

    if payload.role == RoleEnum.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin accounts cannot be self-registered.",
        )

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

    existing_email = await db.execute(
        select(User).where(func.lower(User.email) == email)
    )
    if existing_email.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A MeSquared account with this email already exists.",
        )

    created_at = datetime.now(timezone.utc)
    user = User(
        id=uuid.uuid4(),
        email=email,
        first_name=payload.first_name,
        last_name=payload.last_name,
        role=payload.role,
        auth0_issuer=issuer,
        auth0_subject=subject,
        created_at=created_at,
        last_used_at=created_at,
    )
    db.add(user)

    if payload.role == RoleEnum.patient:
        db.add(
            Patient(
                user_id=user.id,
                date_of_birth=payload.dob,
                biological_sex=payload.sex.strip() if payload.sex else None,
            )
        )
    elif payload.role == RoleEnum.physician:
        db.add(Physician(user_id=user.id))

    try:
        await db.commit()
    except IntegrityError:
        # Concurrent onboarding raced us for the identity or email.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This account could not be created; it may already exist.",
        )
    await db.refresh(user)
    return user