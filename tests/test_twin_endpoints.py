"""Tests for the digital twin endpoints and the sync pipeline."""

import asyncio
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

from app.models.health import RawBiomarkerLog
from app.services import twin_service


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _dob_for_age(years: int) -> str:
    """A date of birth that yields roughly `years` old today (date-stable)."""
    return date(date.today().year - years, 1, 1).isoformat()


def _ml_state() -> dict:
    """A full, valid ML Engine twin-state response."""
    today = date.today().isoformat()
    return {
        "as_of": today,
        "predictions": [
            {
                "biomarker": "hdl",
                "basis": "lab",
                "basis_label": "From your most recent lab",
                "p10": 40.0,
                "p50": 52.0,
                "p90": 65.0,
                "unit": "mg/dL",
                "as_of": today,
                "source_lab_id": "HDL-1",
            }
        ],
        "risk": {
            "status": "generated",
            "risk_basis": "mixed",
            "inputs_used": {"hdl": {"value": 52.0, "source": "measured"}},
            "results": [
                {
                    "outcome": "total_cvd",
                    "horizon_years": 10,
                    "risk_pct": 7.5,
                    "risk_low": 6.0,
                    "risk_high": 9.0,
                    "category": "borderline",
                }
            ],
            "missing_inputs": [],
            "out_of_range": [],
        },
        "rejected_records": [],
        "wearable_windows": {
            "rhr": {
                "metric": "resting_heart_rate",
                "days": 7,
                "coverage": 1.0,
                "sufficient": True,
                "mean": 60.0,
            }
        },
        "lab_prompt": {"due_on": today, "due": True},
        "model_versions": {"prior": "v1", "prevent": "v2", "activation": "v3"},
        "input_hash": "sha256:abc123",
    }


class FakeClient:
    """Stand-in for MLEngineClient that captures the payload and returns canned state."""

    captured: dict = {}
    raises: Exception | None = None

    def __init__(self, *args, **kwargs):
        pass

    async def post_twin_state(self, payload: dict) -> dict:
        FakeClient.captured = payload
        if FakeClient.raises is not None:
            raise FakeClient.raises
        return _ml_state()


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeClient.captured = {}
    FakeClient.raises = None
    yield


@pytest.fixture
def patch_engine(monkeypatch):
    """Route the service's MLEngineClient to the fake."""
    monkeypatch.setattr(twin_service, "MLEngineClient", FakeClient)
    return FakeClient


@pytest.fixture
def patient_client(auth):
    """An authenticated patient with a complete-enough profile."""
    client = auth()
    response = client.post(
        "/users/me/create-m2-account",
        json={
            "first_name": "Alex",
            "last_name": "Isak",
            "role": "patient",
            "sex": "Male",
            "dob": "1999-09-21",
        },
    )
    assert response.status_code == 201, response.text

    response = client.put(
        "/patients/me/profile",
        json={
            "race": ["Black or African American"],
            "baseline_height_cm": 192,
            "baseline_weight_kg": 77,
            "smoking": "No",
            "high_blood_pressure_history": "Yes",
            "blood_pressure_medication": "No",
            "high_cholesterol_history": "Yes",
            "cholesterol_medication": "No",
        },
    )
    assert response.status_code == 200, response.text
    return client


def _patient_id(client) -> str:
    """The authenticated patient's user_id."""
    return client.get("/patients/me/profile").json()["user"]["id"]


def _add_biomarker_log(patient_id: str, **fields) -> None:
    """Insert one RawBiomarkerLog directly, outside the extraction flow."""
    from app.core.db import SessionLocal

    async def _insert():
        async with SessionLocal() as db:
            db.add(
                RawBiomarkerLog(
                    id=uuid4(),
                    patient_id=patient_id,
                    measured_at=datetime.now(timezone.utc),
                    **fields,
                )
            )
            await db.commit()

    asyncio.run(_insert())


# --------------------------------------------------------------------------- #
# Access control
# --------------------------------------------------------------------------- #


def test_twin_requires_authentication(client):
    assert client.get("/patients/me/twin").status_code == 401
    assert client.post("/patients/me/twin/sync").status_code == 401


def test_physician_cannot_access_twin(auth):
    client = auth()
    response = client.post(
        "/users/me/create-m2-account",
        json={"first_name": "Dr", "last_name": "Who", "role": "physician"},
    )
    assert response.status_code == 201, response.text

    assert client.get("/patients/me/twin").status_code == 403
    assert client.post("/patients/me/twin/sync").status_code == 403


# --------------------------------------------------------------------------- #
# Sync: payload translation + persistence
# --------------------------------------------------------------------------- #


def test_sync_returns_full_state_including_risk(patient_client, patch_engine):
    response = patient_client.post("/patients/me/twin/sync")
    assert response.status_code == 200, response.text

    body = response.json()
    state = body["state"]
    # The risk block -- previously dropped -- is now present.
    assert state["risk"]["status"] == "generated"
    assert state["risk"]["results"][0]["outcome"] == "total_cvd"
    assert state["predictions"][0]["biomarker"] == "hdl"
    assert state["lab_prompt"]["due"] is True
    assert state["input_hash"] == "sha256:abc123"


def test_sync_translates_profile_correctly(patient_client, patch_engine):
    patient_client.post("/patients/me/twin/sync")
    profile = patch_engine.captured["profile"]

    assert profile["sex"] == "Male"
    assert profile["height_cm"] == 192
    assert profile["smoking"] == "never"
    assert profile["told_high_bp"] == 1
    assert profile["bp_meds"] == 0
    # The real fix: race is mapped to a required NHANES label, not null.
    assert profile["race_eth"] == "Non-Hispanic Black"


def test_sync_normalizes_records(patient_client, patch_engine):
    pid = _patient_id(patient_client)
    # BP logged by the vitals extractor, with the method the engine rejects.
    _add_biomarker_log(
        pid,
        biomarker_abbr="systolic_bp",
        value=128.0,
        unit="mmHg",
        measurement_method="visit_summary_upload",
    )
    # eGFR with a caret unit the engine would otherwise reject.
    _add_biomarker_log(
        pid,
        biomarker_abbr="egfr",
        value=90.0,
        unit="mL/min/1.73m^2",
        measurement_method="blood_test_lab_report_upload",
    )

    patient_client.post("/patients/me/twin/sync")
    records = {r["biomarker_abbr"]: r for r in patch_engine.captured["records"]}

    assert records["systolic_bp"]["measurement_method"] == "clinic_measurement"
    assert records["egfr"]["unit"] == "mL/min/1.73m2"


def test_get_twin_computes_on_miss_then_reads_cache(patient_client, patch_engine):
    # No twin row yet -> GET computes and persists.
    first = patient_client.get("/patients/me/twin")
    assert first.status_code == 200, first.text
    assert first.json()["state"]["risk"]["status"] == "generated"

    # Second GET (no compute flag) should read the saved row, not recompute.
    patch_engine.raises = twin_service.MLEngineError("should not be called")
    second = patient_client.get("/patients/me/twin")
    assert second.status_code == 200, second.text
    assert second.json()["state"]["input_hash"] == "sha256:abc123"


# --------------------------------------------------------------------------- #
# Age gate + error mapping
# --------------------------------------------------------------------------- #


def test_twin_rejects_unsupported_age(auth, patch_engine):
    client = auth()
    response = client.post(
        "/users/me/create-m2-account",
        json={
            "first_name": "Kid",
            "last_name": "Young",
            "role": "patient",
            "sex": "Male",
            "dob": _dob_for_age(10),
        },
    )
    assert response.status_code == 201, response.text

    response = client.post("/patients/me/twin/sync")
    assert response.status_code == 422


@pytest.mark.parametrize(
    "error,expected",
    [
        (twin_service.MLEngineTimeout("t"), 504),
        (twin_service.MLEngineUnavailable("u"), 503),
        (twin_service.MLEngineResponseError(422, "bad"), 502),
    ],
)
def test_sync_maps_engine_errors(patient_client, patch_engine, error, expected):
    patch_engine.raises = error
    response = patient_client.post("/patients/me/twin/sync")
    assert response.status_code == expected
