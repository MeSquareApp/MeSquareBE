import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    sex: str | None = Field(default=None, max_length=255)
    dob: date | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("first_name", "last_name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Name must not be blank.")
        return normalized

    @model_validator(mode="after")
    def validate_role_fields(self) -> "OnboardingRequest":
        if self.role == RoleEnum.patient:
            if self.sex is None or not self.sex.strip():
                raise ValueError("sex is required when role is patient.")
            if self.dob is None:
                raise ValueError("dob is required when role is patient.")
        elif self.sex is not None or self.dob is not None:
            raise ValueError("sex and dob are only accepted when role is patient.")
        return self


class OnboardedUserResponse(UserRead):
    role: RoleEnum
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)