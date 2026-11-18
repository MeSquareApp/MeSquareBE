
"""Endpoints for patient cardiovascular forecasts."""

from datetime import date

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_patient
from app.api.schemas.forecast import ForecastResponse
from app.core.config import settings
from app.core.db import get_db
from app.models.health import RawBiomarkerLog

router = APIRouter(prefix="/patients", tags=["Patients"])


ETHNICITY_CODES = {
    "Mexican American": 1,
    "Other Hispanic": 2,
    "Non-Hispanic White": 3,
    "Non-Hispanic Black": 4,
    "Non-Hispanic Asian": 6,
    "Other Race - Including Multi-Racial": 7,
}


def _age_on(dob: date, as_of: date) -> int:
    return as_of.year - dob.year - (
        (as_of.month, as_of.day) < (dob.month, dob.day)
    )


def _yes_no(value: str | None) -> int | None:
    """Convert profile Yes/No values to the ML Engine's 1/0 flags."""
    if value == "Yes":
        return 1
    if value == "No":
        return 0
    return None


@router.get("/me/forecast", response_model=ForecastResponse)
async def get_my_forecast(
    patient=Depends(get_current_patient),
    db: AsyncSession = Depends(get_db),
):
    today = date.today()
    age = _age_on(patient.date_of_birth, today)

    if not 20 <= age <= 79:
        raise HTTPException(
            status_code=422,
            detail="Forecasts are currently supported for patients aged 20–79.",
        )

    ethnicity = getattr(patient, "ethnicity", None)
    race_eth = ETHNICITY_CODES.get(ethnicity)
    
    smoking_values = {
        "No": "never",
        "Previously": "former",
        "Yes": "current",
    }

    profile = {
        "sex": patient.biological_sex,
        "age": float(age),
        "race_eth": race_eth,
        "height_cm": patient.baseline_height_cm,
        "weight_kg": patient.baseline_weight_kg,
        "waist_cm": patient.waist_cm,
        "smoking": smoking_values.get(patient.smoking),
        "told_high_bp": _yes_no(patient.high_blood_pressure_history),
        "bp_meds": _yes_no(patient.blood_pressure_medication),
        "told_high_chol": _yes_no(patient.high_cholesterol_history),
        "chol_meds": _yes_no(patient.cholesterol_medication),
    }

    result = await db.execute(
        select(RawBiomarkerLog)
        .where(RawBiomarkerLog.patient_id == patient.user_id)
        .order_by(RawBiomarkerLog.measured_at)
    )
    biomarker_logs = result.scalars().all()

    records = [
        {
            "id": str(record.id),
            "biomarker_abbr": record.biomarker_abbr,
            "value": record.value,
            "unit": record.unit,
            "measurement_method": record.measurement_method,
            "measured_at": record.measured_at.isoformat(),
        }
        for record in biomarker_logs
    ]

    payload = {
        "user_id": str(patient.user_id),
        "profile": profile,
        "records": records,
    }

    url = f"{settings.ml_engine_url.rstrip('/')}/v1/twin/state"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="The forecasting service timed out.",
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "The forecasting service returned an error "
                f"(HTTP {exc.response.status_code})."
            ),
        )
    except httpx.RequestError:
        raise HTTPException(
            status_code=503,
            detail="The forecasting service is currently unavailable.",
        )

    try:
        ml_result = response.json()

        return ForecastResponse(
            predictions=ml_result["predictions"],
            wearable_windows={
                name: {"days": window["days"]}
                for name, window in ml_result["wearable_windows"].items()
            },
            lab_prompt={
                "due_on": ml_result["lab_prompt"]["due_on"],
                "due": ml_result["lab_prompt"]["due"],
            },
        )
    except (ValueError, KeyError, TypeError, ValidationError) as exc:
        raise HTTPException(
            status_code=502,
            detail="The forecasting service returned an invalid response.",
        ) from exc
