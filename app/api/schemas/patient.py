from datetime import date, datetime
import uuid
from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Dict, List, Optional

from app.api.schemas.user import UserRead

# Patient Schemas
class PatientUpdate(BaseModel):
    """Partial update of the patient profile; only provided fields are applied.

    Used by the onboarding form to fill in the attributes that were not
    collected at account creation. Passing null for a field clears it
    back to "not answered yet".
    """

    date_of_birth: Optional[date] = None
    biological_sex: Optional[str] = None
    race: Optional[List[str]] = None
    region: Optional[str] = None
    diagnosed_conditions: Optional[List[str]] = None
    other_condition: Optional[str] = None
    current_medications: Optional[str] = None
    blood_pressure_medication: Optional[str] = None
    blood_pressure_details: Optional[str] = None
    cholesterol_medication: Optional[str] = None
    cholesterol_details: Optional[str] = None
    alcohol: Optional[str] = None
    smoking: Optional[str] = None
    recreational_drugs: Optional[str] = None
    exercise_hours: Optional[str] = None
    sleep_hours: Optional[str] = None
    high_blood_pressure_history: Optional[str] = None
    high_cholesterol_history: Optional[str] = None
    baseline_height_cm: Optional[float] = Field(None, ge=0)
    baseline_weight_kg: Optional[float] = Field(None, ge=0)
    waist_cm: Optional[float] = Field(None, ge=0)
    allergies: Optional[str] = None
    medical_history: Optional[str] = None

class PatientProfileResponse(BaseModel):
    """Patient profile as stored in the database.

    Only date_of_birth and biological_sex are guaranteed non-null (they are
    collected at account creation); every other attribute is null until the
    patient completes onboarding.
    """

    date_of_birth: date
    biological_sex: str
    race: Optional[List[str]] = None
    region: Optional[str] = None
    diagnosed_conditions: Optional[List[str]] = None
    other_condition: Optional[str] = None
    current_medications: Optional[str] = None
    blood_pressure_medication: Optional[str] = None
    blood_pressure_details: Optional[str] = None
    cholesterol_medication: Optional[str] = None
    cholesterol_details: Optional[str] = None
    alcohol: Optional[str] = None
    smoking: Optional[str] = None
    recreational_drugs: Optional[str] = None
    exercise_hours: Optional[str] = None
    sleep_hours: Optional[str] = None
    high_blood_pressure_history: Optional[str] = None
    high_cholesterol_history: Optional[str] = None
    baseline_height_cm: Optional[float] = None
    baseline_weight_kg: Optional[float] = None
    waist_cm: Optional[float] = None
    allergies: Optional[str] = None
    medical_history: Optional[str] = None
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