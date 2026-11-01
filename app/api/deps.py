from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.core.security import verify_auth0_token
from app.models.users import Patient, Physician, RoleEnum, User


async def get_current_user(
    token_payload: dict[str, object] = Depends(verify_auth0_token),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Resolve the verified Auth0 issuer and subject to a MeSquared user record.
    """
    subject = token_payload.get("sub")
    issuer = token_payload.get("iss")
    expected_issuer = f"https://{settings.auth0_domain}/"

    if (
        not isinstance(subject, str)
        or not subject
        or not isinstance(issuer, str)
        or issuer != expected_issuer
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    statement = select(User).where(
        User.auth0_issuer == issuer,
        User.auth0_subject == subject,
    )
    result = await db.execute(statement)
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No MeSquared account is linked to this Auth0 identity.",
        )

    return user


async def get_current_patient(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Patient:
    if user.role != RoleEnum.patient:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A patient account is required.",
        )

    result = await db.execute(select(Patient).where(Patient.user_id == user.id))
    patient = result.scalar_one_or_none()
    if patient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient profile not found.",
        )
    return patient


async def get_current_physician(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Physician:
    if user.role != RoleEnum.physician:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A physician account is required.",
        )

    result = await db.execute(select(Physician).where(Physician.user_id == user.id))
    physician = result.scalar_one_or_none()
    if physician is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Physician profile not found.",
        )
    return physician
