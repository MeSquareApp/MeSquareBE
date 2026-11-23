"""Assemble the DigitalTwinContext shown to the chatbot from existing tables.

There are no dedicated user_labs / wearable_daily / predictions_history tables
in this codebase: the longitudinal store is `raw_biomarker_logs` (lab and
wearable time series) and the computed twin state lives in
`twins.t_zero_state`. Every section is best-effort -- a patient with no data
gets null fields rather than an error, so the chatbot still works with
partial context.
"""

import logging
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.chat import DigitalTwinContext, LabAnchors, RiskProfile, WearablesSummary
from app.models.health import RawBiomarkerLog, Twin
from app.models.users import Patient

logger = logging.getLogger(__name__)

WEARABLE_WINDOW_DAYS = 14

# raw_biomarker_logs stores free-form biomarker abbreviations. These are the
# abbreviations the aggregator recognizes; they match what the extraction
# routes persist ("non_hdl", "hdl", "hba1c", "egfr", "systolic_bp", ...).
# The first entry of each tuple is the canonical spelling going forward.
LAB_ANCHOR_ABBRS: dict[str, tuple[str, ...]] = {
    "total_cholesterol": ("total_cholesterol", "tc"),
    "hdl": ("hdl",),
    "ldl": ("ldl",),
    "systolic_bp": ("systolic_bp", "sbp"),
    "diastolic_bp": ("diastolic_bp", "dbp"),
    "fasting_glucose": ("fasting_glucose", "glucose"),
    "hba1c": ("hba1c",),
}

WEARABLE_ABBRS: dict[str, tuple[str, ...]] = {
    "resting_heart_rate_avg_14d": ("resting_heart_rate", "rhr"),
    "step_count_avg_14d": ("steps", "step_count"),
    "sleep_hours_avg_14d": ("sleep_hours", "sleep_duration"),
}


def _all_abbrs(mapping: dict[str, tuple[str, ...]]) -> set[str]:
    return {abbr for abbrs in mapping.values() for abbr in abbrs}


def _field_for_abbr(mapping: dict[str, tuple[str, ...]], abbr: str) -> str | None:
    for field, abbrs in mapping.items():
        if abbr in abbrs:
            return field
    return None


def _age_on(date_of_birth: date, today: date) -> int:
    return today.year - date_of_birth.year - (
        (today.month, today.day) < (date_of_birth.month, date_of_birth.day)
    )


def _normalize_sex(biological_sex: str | None) -> str | None:
    """Normalize biological_sex for MeSquareAssistantBot.

    The bot validates sex as the case-sensitive Literal["male", "female"],
    while patient onboarding stores e.g. "Female". Anything unrecognized is
    sent as null (the bot tolerates a missing sex) rather than risking a 422.
    """
    if biological_sex is None:
        return None
    normalized = biological_sex.strip().lower()
    return normalized if normalized in ("male", "female") else None


async def _latest_lab_anchors(db: AsyncSession, patient_id) -> LabAnchors | None:
    """Latest measured value per recognized lab biomarker (one query)."""
    statement = (
        select(
            RawBiomarkerLog.biomarker_abbr,
            RawBiomarkerLog.value,
            RawBiomarkerLog.measured_at,
        )
        .where(
            RawBiomarkerLog.patient_id == patient_id,
            RawBiomarkerLog.biomarker_abbr.in_(_all_abbrs(LAB_ANCHOR_ABBRS)),
        )
        .order_by(RawBiomarkerLog.biomarker_abbr.asc(), RawBiomarkerLog.measured_at.desc())
    )
    rows = (await db.execute(statement)).all()
    if not rows:
        return None

    # Rows are sorted newest-first per abbreviation, so the first row seen for
    # each abbreviation is its most recent measurement.
    latest: dict[str, tuple[float, object]] = {}
    for abbr, value, measured_at in rows:
        if abbr not in latest:
            latest[abbr] = (value, measured_at)

    values: dict[str, float | None] = {field: None for field in LAB_ANCHOR_ABBRS}
    anchor_date: date | None = None
    for abbr, (value, measured_at) in latest.items():
        field = _field_for_abbr(LAB_ANCHOR_ABBRS, abbr)
        if field is None:
            continue
        values[field] = value
        measured_on = measured_at.date() if measured_at is not None else None
        if measured_on is not None and (anchor_date is None or measured_on > anchor_date):
            anchor_date = measured_on

    if all(value is None for value in values.values()):
        return None
    return LabAnchors(anchor_date=anchor_date, **values)


async def _wearables_summary(db: AsyncSession, patient_id) -> WearablesSummary | None:
    """14-day rolling averages for the recognized wearable biomarkers."""
    window_start = func.now() - timedelta(days=WEARABLE_WINDOW_DAYS)
    statement = (
        select(RawBiomarkerLog.biomarker_abbr, func.avg(RawBiomarkerLog.value))
        .where(
            RawBiomarkerLog.patient_id == patient_id,
            RawBiomarkerLog.biomarker_abbr.in_(_all_abbrs(WEARABLE_ABBRS)),
            RawBiomarkerLog.measured_at >= window_start,
        )
        .group_by(RawBiomarkerLog.biomarker_abbr)
    )
    rows = (await db.execute(statement)).all()
    if not rows:
        return None

    values: dict[str, float | None] = {field: None for field in WEARABLE_ABBRS}
    for abbr, average in rows:
        field = _field_for_abbr(WEARABLE_ABBRS, abbr)
        if field is not None and average is not None:
            values[field] = float(average)

    if all(value is None for value in values.values()):
        return None
    return WearablesSummary(**values)

async def _risk_profile(db: AsyncSession, patient_id) -> RiskProfile | None:
    """Read the latest computed twin state (AHA PREVENT score, percentiles)."""
    result = await db.execute(select(Twin).where(Twin.patient_id == patient_id))
    twin = result.scalar_one_or_none()
    if twin is None or not isinstance(twin.t_zero_state, dict):
        return None
    state = twin.t_zero_state

    def _number(key: str) -> float | None:
        value = state.get(key)
        return float(value) if isinstance(value, (int, float)) else None

    risk = RiskProfile(
        aha_prevent_10yr_score=_number("aha_prevent_10yr_score"),
        nhanes_percentile=_number("nhanes_percentile"),
        risk_category=(
            state["risk_category"] if isinstance(state.get("risk_category"), str) else None
        ),
    )
    if all(
        value is None
        for value in (risk.aha_prevent_10yr_score, risk.nhanes_percentile, risk.risk_category)
    ):
        return None
    return risk


async def build_digital_twin_context(db: AsyncSession, patient: Patient) -> DigitalTwinContext:
    """Build the twin context for one incoming chat message.

    Aggregates raw_biomarker_logs (latest lab anchors + 14-day wearable
    averages) and twins.t_zero_state (risk profile), plus the patient's
    static profile attributes (age, sex, smoking status).
    """
    today = date.today()
    return DigitalTwinContext(
        user_id=str(patient.user_id),
        age=_age_on(patient.date_of_birth, today) if patient.date_of_birth else None,
        sex=_normalize_sex(patient.biological_sex),
        smoking_status=patient.smoking,
        lab_anchors=await _latest_lab_anchors(db, patient.user_id),
        wearables_summary=await _wearables_summary(db, patient.user_id),
        risk_profile=await _risk_profile(db, patient.user_id),
    )
