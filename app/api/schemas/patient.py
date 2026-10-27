import uuid
from datetime import date, datetime
from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Dict, List, Optional

# Base User Schema
class UserRead(BaseModel):
    id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    username: str
    
    model_config = ConfigDict(from_attributes=True)

# Patient Schemas
class PatientUpdate(BaseModel):
    baseline_height_cm: Optional[float] = Field(None, ge=0)
    baseline_weight_kg: Optional[float] = Field(None, ge=0)
    allergies: Optional[str] = None
    medical_conditions: Optional[str] = None

class PatientProfileResponse(BaseModel):
    date_of_birth: date
    biological_sex: str
    baseline_height_cm: float
    baseline_weight_kg: float
    allergies: str
    medical_conditions: str
    user: UserRead # Nests the core identity data inside the patient response

    model_config = ConfigDict(from_attributes=True)

class TwinResponse(BaseModel):
    id: uuid.UUID
    t_zero_state: Dict[str, Any]
    last_updated: datetime

    model_config = ConfigDict(from_attributes=True)


class BiomarkerLogResponse(BaseModel):
    id: uuid.UUID
    biomarker_abbr: str
    value: float
    unit: str
    measurement_method: str
    measured_at: datetime

    model_config = ConfigDict(from_attributes=True)

class VitalsLogResponse(BaseModel):
    """Vitals extracted from a single document; any vital the document did not contain is null."""
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    systolic_bp: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)

class LinkPhysicianRequest(BaseModel):
    physician_id: uuid.UUID