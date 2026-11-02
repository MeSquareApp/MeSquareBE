import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.users import RoleEnum


class UserRead(BaseModel):
    id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    role: RoleEnum
    created_at: datetime
    auth0_issuer: str
    auth0_subject: str
    last_used_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OnboardingRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=255)
    last_name: str = Field(min_length=1, max_length=255)
    role: RoleEnum

    model_config = ConfigDict(extra="forbid")

    @field_validator("first_name", "last_name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Name must not be blank.")
        return normalized


class OnboardedUserResponse(UserRead):
    role: RoleEnum
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)