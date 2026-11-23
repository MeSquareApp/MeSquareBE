"""Typed schemas for the digital twin state.

These mirror the MeSquareMLEngine ``POST /v1/twin/state`` response
(`src/schemas/outputs.py` and `src/schemas/twin.py` in that repo) field for
field, so the full result -- including the PREVENT risk block and traceability
-- is validated, persisted, and returned, rather than silently dropped.

Keep these in sync with the ML Engine's output schema. If the engine adds a
field, add it here too.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel


class ChangeOut(BaseModel):
    """Latest lab vs the previous one against the 95% reference change value."""

    previous_lab_id: str
    previous_value: float
    previous_measured_at: date
    percent_change: float
    rcv_low_pct: float
    rcv_high_pct: float
    significant: bool


class PredictionOut(BaseModel):
    """The served band of one biomarker and what it is based on."""

    biomarker: str
    basis: Literal["population", "lab", "population_wearable", "lab_wearable"]
    basis_label: str
    p10: float
    p50: float
    p90: float
    unit: str
    as_of: date
    source_lab_id: str | None = None
    lab_measured_at: date | None = None
    change: ChangeOut | None = None


class InputUsedOut(BaseModel):
    """One PREVENT input and whether it was measured, reported or predicted."""

    value: float
    source: Literal["measured", "reported", "predicted"]


class RiskResultOut(BaseModel):
    """Risk for one outcome and horizon, in percent."""

    outcome: Literal["total_cvd", "ascvd", "heart_failure"]
    horizon_years: int
    risk_pct: float
    risk_low: float
    risk_high: float
    category: Literal["low", "borderline", "intermediate", "high"] | None = None


class RiskOut(BaseModel):
    """PREVENT risk response.

    ``risk_basis`` is "measured" when every lab-type input was measured,
    "estimated" when none was, else "mixed". The app should label a risk that is
    not "measured" as an estimate.
    """

    status: Literal["generated", "not_generated"]
    risk_basis: Literal["measured", "mixed", "estimated"] | None = None
    inputs_used: dict[str, InputUsedOut] = {}
    results: list[RiskResultOut] = []
    missing_inputs: list[str] = []
    reason: str | None = None
    out_of_range: list[str] = []


class RejectedRecordOut(BaseModel):
    """A record the ML Engine did not use, and why."""

    id: str | None = None
    biomarker_abbr: str | None = None
    reason: str


class WindowOut(BaseModel):
    """One wearable metric over one window ending at as_of."""

    metric: str
    days: int
    coverage: float
    sufficient: bool
    mean: float | None = None
    sd: float | None = None
    slope_per_day: float | None = None


class LabPromptOut(BaseModel):
    """When the app should ask the user for their next lab."""

    due_on: date
    due: bool


class DigitalTwinStateResponse(BaseModel):
    """The full personalized twin state for one user.

    This is the body persisted into ``twins.t_zero_state`` and returned to the
    client. It is a faithful mirror of the ML Engine's ``TwinStateResponse``.
    """

    as_of: date
    predictions: list[PredictionOut]
    risk: RiskOut
    rejected_records: list[RejectedRecordOut] = []
    wearable_windows: dict[str, WindowOut] = {}
    lab_prompt: LabPromptOut
    model_versions: dict[str, str] = {}
    input_hash: str


class TwinStateRead(BaseModel):
    """What the twin endpoints return: the state plus a little row metadata."""

    patient_id: str
    last_updated: str | None = None
    state: DigitalTwinStateResponse
