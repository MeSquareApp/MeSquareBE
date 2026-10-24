from pydantic import BaseModel, Field
from typing import Optional

class BiomarkerExtraction(BaseModel):
    non_hdl: Optional[float] = Field(description="Non-HDL cholesterol value")
    hdl: Optional[float] = Field(description="HDL cholesterol value")
    hba1c: Optional[float] = Field(description="HbA1c percentage")
    egfr: Optional[float] = Field(description="eGFR (estimated glomerular filtration rate) value")

class VitalsExtraction(BaseModel):
    height: Optional[float] = Field(description="Height value of the patient in inches (in)")
    weight: Optional[float] = Field(description="Weight value of the patient in pounds (lb)")
    systolic_bp: Optional[float] = Field(description="Systolic blood pressure value (the higher number)")

# Convert the Pydantic model into a JSON Schema dictionary for the LlamaCloud API
biomarker_extraction_schema = BiomarkerExtraction.model_json_schema()
vitals_extraction_schema = VitalsExtraction.model_json_schema()