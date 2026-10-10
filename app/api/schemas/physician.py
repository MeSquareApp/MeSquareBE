import uuid
from pydantic import BaseModel, ConfigDict
from typing import List
from app.api.schemas.patient import PatientProfileResponse, TwinResponse, BiomarkerLogResponse

# Import the UserRead schema you already built for patients
from app.api.schemas.patient import UserRead

class ClinicResponse(BaseModel):
    id: uuid.UUID
    name: str
    street_address: str
    city: str
    state: str
    country: str

    model_config = ConfigDict(from_attributes=True)

class PhysicianClinicResponse(BaseModel):
    # This maps to the junction table which holds the actual Clinic object
    clinic: ClinicResponse

    model_config = ConfigDict(from_attributes=True)

class PhysicianProfileResponse(BaseModel):
    medical_license_number: str
    specialty: str
    user: UserRead
    clinics: List[PhysicianClinicResponse]

    model_config = ConfigDict(from_attributes=True)

class PatientDataForPhysicianResponse(BaseModel):
    profile: PatientProfileResponse
    twin: TwinResponse
    recent_biomarkers: List[BiomarkerLogResponse]

    model_config = ConfigDict(from_attributes=True)