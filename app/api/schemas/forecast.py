
"""Response schemas for cardiovascular biomarker forecasts."""

from datetime import date
from typing import Literal

from pydantic import BaseModel


class PredictionResponse(BaseModel):
    """Forecasted biomarker value and uncertainty range."""

    biomarker: str
    p10: float
    p50: float
    p90: float
    unit: str
    as_of: date

    basis: Literal[
        "population",
        "lab",
        "population_wearable",
        "lab_wearable",
    ]
    basis_label: str


class WearableWindowResponse(BaseModel):
    """Wearable data analysis window."""

    days: int


class LabPromptResponse(BaseModel):
    """Suggested date for the next laboratory measurement."""

    due_on: date
    due: bool


class ForecastResponse(BaseModel):
    """Response containing the user's biomarker forecasts."""

    predictions: list[PredictionResponse]
    wearable_windows: dict[str, WearableWindowResponse]
    lab_prompt: LabPromptResponse
