import uuid
from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional
from app.api.schemas.patient import PatientProfileResponse, TwinResponse, BiomarkerLogResponse

from app.api.schemas.user import UserRead

class ClinicResponse(BaseModel):
    id: uuid.UUID
    name: str
    street_address: str
    city: str
    state: str
    country: str

    model_config = ConfigDict(from_attributes=True)

class PhysicianUpdate(BaseModel):
    """Partial update of the physician profile; only provided fields are applied.

    Used by the onboarding form to fill in the license and specialty that
    were not collected at account creation.
    """

    medical_license_number: Optional[str] = Field(None, min_length=1, max_length=255)
    specialty: Optional[str] = Field(None, min_length=1, max_length=255)

class PhysicianClinicResponse(BaseModel):
    # This maps to the junction table which holds the actual Clinic object
    clinic: ClinicResponse

    model_config = ConfigDict(from_attributes=True)

class PhysicianProfileResponse(BaseModel):
    """Physician profile as stored in the database.

    The row is created (empty) at account creation, so license and
    specialty are null until the physician completes onboarding.
    """

    medical_license_number: Optional[str] = None
    specialty: Optional[str] = None
    user: UserRead
    clinics: List[PhysicianClinicResponse]

    model_config = ConfigDict(from_attributes=True)

class PatientDataForPhysicianResponse(BaseModel):
    profile: PatientProfileResponse
    twin: TwinResponse
    recent_biomarkers: List[BiomarkerLogResponse]

    model_config = ConfigDict(from_attributes=True)