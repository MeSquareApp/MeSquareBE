import uuid
from datetime import date, datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.patient import UserRead
from app.models.users import RoleEnum


class _OnboardingBase(BaseModel):
    email: str
    first_name: str
    last_name: str


class PatientOnboarding(_OnboardingBase):
    """Self-registration payload for a patient account."""

    role: Literal[RoleEnum.patient] = RoleEnum.patient
    date_of_birth: date
    biological_sex: str
    baseline_height_cm: float = Field(ge=0)
    baseline_weight_kg: float = Field(ge=0)
    allergies: str = ""
    medical_conditions: str = ""


class PhysicianOnboarding(_OnboardingBase):
    """Self-registration payload for a physician account."""

    role: Literal[RoleEnum.physician] = RoleEnum.physician
    medical_license_number: str
    specialty: str


class AdminOnboarding(_OnboardingBase):
    """Self-registration payload for an admin account."""

    role: Literal[RoleEnum.admin] = RoleEnum.admin
    access_level: str


OnboardingRequest = Annotated[
    Union[PatientOnboarding, PhysicianOnboarding, AdminOnboarding],
    Field(discriminator="role"),
]


class OnboardedUserResponse(UserRead):
    role: RoleEnum
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)