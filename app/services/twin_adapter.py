"""Translate and sanitize our DB rows into the ML Engine's input shape.

The ML Engine (`src/schemas/twin.py`, `src/components/record_ingestion.py`) is
strict about its inputs. This module is the single place that converts a
``Patient`` and their ``RawBiomarkerLog`` rows into the exact ``profile`` and
``records`` the engine expects. Every rule the engine enforces -- required
fields, accepted labels, accepted measurement methods, accepted unit spellings
-- is handled here so the engine never 422s on a well-formed patient.

Pure functions only: no DB, no network. That keeps them trivially unit-testable.
"""

from __future__ import annotations

from datetime import date
from typing import Any

# --------------------------------------------------------------------------- #
# Demographic coding
# --------------------------------------------------------------------------- #

# The ML Engine's `sex` accepts the NHANES *label* ("Male"/"Female") and dumps
# the code itself. Our Patient.biological_sex is already "Male"/"Female".
_SEX_LABELS = {"male": "Male", "female": "Female"}

# The engine's `race_eth` is REQUIRED and accepts exactly one of six NHANES
# RIDRETH3 *labels*. Our Patient.race is a nullable multi-select list of
# Census-style labels, so we map it here.
#
# NOTE FOR THE TEAM: this mapping is a clinical input to the PREVENT risk score.
# Confirm it (and the missing-race fallback below) with whoever owns the
# onboarding race options. Changing it is a one-line edit to this dict.
NHANES_WHITE = "Non-Hispanic White"
NHANES_BLACK = "Non-Hispanic Black"
NHANES_ASIAN = "Non-Hispanic Asian"
NHANES_MEXICAN = "Mexican American"
NHANES_OTHER_HISPANIC = "Other Hispanic"
NHANES_OTHER = "Other Race - Including Multi-Racial"

# Fallback when race is missing, unknown, or multiple races are selected. We
# default to "Other Race" so the forecast still runs. Flip this to raising if the
# team decides a missing race should force the user back to onboarding instead.
RACE_FALLBACK = NHANES_OTHER

_RACE_TO_NHANES: dict[str, str] = {
    "white": NHANES_WHITE,
    "caucasian": NHANES_WHITE,
    "black or african american": NHANES_BLACK,
    "black": NHANES_BLACK,
    "african american": NHANES_BLACK,
    "asian": NHANES_ASIAN,
    "hispanic or latino": NHANES_OTHER_HISPANIC,
    "latino": NHANES_OTHER_HISPANIC,
    "hispanic": NHANES_OTHER_HISPANIC,
    "mexican american": NHANES_MEXICAN,
    "mexican": NHANES_MEXICAN,
    # Mapped to "Other Race" because NHANES has no dedicated category:
    "american indian or alaska native": NHANES_OTHER,
    "native hawaiian or other pacific islander": NHANES_OTHER,
    "other": NHANES_OTHER,
}

_SMOKING_TO_ENGINE = {"no": "never", "previously": "former", "yes": "current"}

# Map a patient's self-reported diagnosed conditions to PREVENT diabetes inputs.
# Conservative keyword match; everything unmatched stays None (unknown), which
# the engine treats as not-measured rather than as a wrong value.
_DIABETES_KEYWORDS = ("type 2 diabetes", "type ii diabetes", "diabetes", "t2dm", "t2d")
_PREDIABETES_KEYWORDS = ("prediabetes", "pre-diabetes", "pre diabetes")


def _age_on(dob: date, as_of: date) -> int:
    """Whole years from dob to as_of."""
    return as_of.year - dob.year - ((as_of.month, as_of.day) < (dob.month, dob.day))


def _yes_no(value: str | None) -> int | None:
    """Convert a Yes/No profile answer to the engine's 1/0 flag."""
    if value == "Yes":
        return 1
    if value == "No":
        return 0
    return None


def map_race_to_nhanes(race: list[str] | None) -> str:
    """Map the app's race selection to a single NHANES RIDRETH3 label.

    Rules:
        * No selection -> fallback.
        * Any Hispanic/Latino value present -> the Hispanic category (NHANES
          treats Hispanic ethnicity as overriding race).
        * Exactly one recognized race -> that race.
        * Multiple distinct recognized races, or anything unrecognized ->
          fallback ("Other Race - Including Multi-Racial").
    """
    if not race:
        return RACE_FALLBACK

    mapped = [_RACE_TO_NHANES.get(value.strip().lower()) for value in race]
    recognized = [label for label in mapped if label is not None]

    if not recognized:
        return RACE_FALLBACK

    hispanic = {NHANES_MEXICAN, NHANES_OTHER_HISPANIC}
    hispanic_hits = [label for label in recognized if label in hispanic]
    if hispanic_hits:
        # Prefer a specific Mexican American coding if that was the choice.
        return NHANES_MEXICAN if NHANES_MEXICAN in hispanic_hits else NHANES_OTHER_HISPANIC

    distinct = set(recognized)
    if len(distinct) == 1:
        return distinct.pop()
    return RACE_FALLBACK


def _diabetes_dx(conditions: list[str] | None) -> str | None:
    if not conditions:
        return None
    joined = " ".join(conditions).lower()
    if any(keyword in joined for keyword in _DIABETES_KEYWORDS):
        return "yes"
    return None


def _prediabetes_flag(conditions: list[str] | None) -> int | None:
    if not conditions:
        return None
    joined = " ".join(conditions).lower()
    if any(keyword in joined for keyword in _PREDIABETES_KEYWORDS):
        return 1
    return None


def build_patient_profile(patient: Any, as_of: date | None = None) -> dict[str, Any]:
    """Build the ML Engine ``profile`` object from a Patient row.

    Args:
        patient: A ``Patient`` ORM instance (or any object with the same fields).
        as_of: Date to compute age against. Defaults to today.

    Returns:
        A dict matching the engine's ``Profile`` schema. ``sex``, ``age`` and
        ``race_eth`` are always populated (the three required fields); optional
        fields are included only when known.
    """
    today = as_of or date.today()
    biological_sex = (patient.biological_sex or "").strip().lower()

    profile: dict[str, Any] = {
        "sex": _SEX_LABELS.get(biological_sex, patient.biological_sex),
        "age": float(_age_on(patient.date_of_birth, today)),
        "race_eth": map_race_to_nhanes(getattr(patient, "race", None)),
        "height_cm": patient.baseline_height_cm,
        "weight_kg": patient.baseline_weight_kg,
        "waist_cm": patient.waist_cm,
        "smoking": _SMOKING_TO_ENGINE.get((patient.smoking or "").strip().lower()),
        "told_high_bp": _yes_no(patient.high_blood_pressure_history),
        "bp_meds": _yes_no(patient.blood_pressure_medication),
        "told_high_chol": _yes_no(patient.high_cholesterol_history),
        "chol_meds": _yes_no(patient.cholesterol_medication),
        "diabetes_dx": _diabetes_dx(getattr(patient, "diagnosed_conditions", None)),
        "prediabetes_dx": _prediabetes_flag(
            getattr(patient, "diagnosed_conditions", None)
        ),
    }
    return profile


# --------------------------------------------------------------------------- #
# Record translation
# --------------------------------------------------------------------------- #

# Our write-side measurement_method values that the engine does not accept, and
# what to send instead. "visit_summary_upload" (written by the vitals extractor
# for blood pressure) is not in the engine's MEASURED_LAB_METHODS, so untranslated
# BP readings are silently rejected -- and PREVENT then runs without measured BP.
_METHOD_NORMALIZATION = {
    "visit_summary_upload": "clinic_measurement",
}


def _sanitize_unit(unit: str | None) -> str | None:
    """Make a unit string match the engine's normalized spellings.

    The engine lower-cases, strips spaces, and rewrites some glyphs, but it does
    NOT strip a caret, so "mL/min/1.73m^2" never matches its "ml/min/1.73m2"
    key and eGFR gets rejected. Drop the caret here.
    """
    if unit is None:
        return None
    return unit.replace("^", "")


def _normalize_method(method: str | None) -> str | None:
    if method is None:
        return None
    return _METHOD_NORMALIZATION.get(method, method)


def build_records_payload(logs: list[Any]) -> list[dict[str, Any]]:
    """Build the ML Engine ``records`` list from RawBiomarkerLog rows.

    Normalizes measurement methods and unit spellings the engine would otherwise
    reject, and serializes timestamps to ISO-8601. Bad records are left for the
    engine to reject (it reports them in ``rejected_records``); we do not drop
    them here.

    Args:
        logs: ``RawBiomarkerLog`` ORM instances, any order.

    Returns:
        A list of record dicts in the engine's input shape.
    """
    records: list[dict[str, Any]] = []
    for record in logs:
        records.append(
            {
                "id": str(record.id),
                "biomarker_abbr": record.biomarker_abbr,
                "value": record.value,
                "unit": _sanitize_unit(record.unit),
                "measurement_method": _normalize_method(record.measurement_method),
                "measured_at": record.measured_at.isoformat(),
            }
        )
    return records
