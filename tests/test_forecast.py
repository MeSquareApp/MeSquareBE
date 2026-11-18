
"""Tests for the patient cardiovascular forecast endpoint."""

from datetime import date

import pytest


@pytest.fixture
def patient_client(auth):
    """Create and authenticate a patient for forecast tests."""
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

    # Complete the relevant parts of the patient profile.
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


def test_forecast_requires_authentication(client):
    """Reject requests without authentication."""

    response = client.get("/patients/me/forecast")

    assert response.status_code == 401


def test_physician_cannot_access_patient_forecast(auth):
    """Reject physicians attempting to access the patient forecast endpoint."""

    client = auth()

    response = client.post(
        "/users/me/create-m2-account",
        json={
            "first_name": "Alex",
            "last_name": "Isak",
            "role": "physician",
        },
    )
    assert response.status_code == 201, response.text

    response = client.get("/patients/me/forecast")

    assert response.status_code == 403


@pytest.mark.parametrize(
    "dob",
    ["2006-11-19", "1946-11-17"],
)
def test_forecast_rejects_unsupported_age(auth, dob):
    """Reject patients outside the supported forecasting age range."""

    client = auth()

    response = client.post(
        "/users/me/create-m2-account",
        json={
            "first_name": "Alex",
            "last_name": "Isak",
            "role": "patient",
            "sex": "Male",
            "dob": dob,
        },
    )
    assert response.status_code == 201, response.text

    response = client.get("/patients/me/forecast")

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Forecasts are currently supported for patients aged 20–79."
    )


def test_get_forecast_success_and_ml_payload(
    patient_client, monkeypatch
):
    """Return a forecast and send the correct patient data to the ML Engine."""

    ml_response = {
        "predictions": [
            {
                "biomarker": "LDL",
                "p10": 90.0,
                "p50": 110.0,
                "p90": 130.0,
                "unit": "mg/dL",
                "as_of": date.today().isoformat(),
                "basis": "population",
                "basis_label": "Population estimate",
            }
        ],
        "wearable_windows": {
            "rhr": {"days": 7},
            "hrv": {"days": 7},
        },
        "lab_prompt": {
            "due_on": date.today().isoformat(),
            "due": True,
        },
    }

    captured = {}

    class MockResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return ml_response

    class MockAsyncClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            pass

        async def post(self, url, json):
            captured["url"] = url
            captured["payload"] = json
            return MockResponse()

    monkeypatch.setattr(
        "app.api.routes.forecast.httpx.AsyncClient",
        MockAsyncClient,
    )

    response = patient_client.get("/patients/me/forecast")

    # Verify the backend endpoint responds successfully.
    assert response.status_code == 200, response.text

    body = response.json()

    assert body["predictions"][0]["biomarker"] == "LDL"
    assert body["predictions"][0]["p10"] == 90.0
    assert body["predictions"][0]["p50"] == 110.0
    assert body["predictions"][0]["p90"] == 130.0
    assert body["wearable_windows"]["rhr"]["days"] == 7
    assert body["lab_prompt"]["due"] is True

    # Verify the ML Engine was called.
    assert captured["timeout"] == 30.0
    assert captured["url"].endswith("/v1/twin/state")

    payload = captured["payload"]
    profile = payload["profile"]

    # Verify patient information was translated correctly.
    assert profile["sex"] == "Male"
    assert profile["age"] == 27.0
    assert profile["height_cm"] == 192
    assert profile["weight_kg"] == 77
    assert profile["smoking"] == "never"
    assert profile["told_high_bp"] == 1
    assert profile["bp_meds"] == 0
    assert profile["told_high_chol"] == 1
    assert profile["chol_meds"] == 0

    # Race mapping is intentionally pending agreement on the standard.
    assert profile["race_eth"] is None

    # This patient has no biomarker records yet.
    assert payload["records"] == []


def test_forecast_ml_timeout(patient_client, monkeypatch):
    """Return 504 when the ML Engine request times out."""

    import httpx

    class MockAsyncClient:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            pass

        async def post(self, url, json):
            raise httpx.TimeoutException("Request timed out")

    monkeypatch.setattr(
        "app.api.routes.forecast.httpx.AsyncClient",
        MockAsyncClient,
    )

    response = patient_client.get("/patients/me/forecast")

    assert response.status_code == 504
    assert response.json()["detail"] == (
        "The forecasting service timed out."
    )


def test_forecast_ml_unavailable(patient_client, monkeypatch):
    """Return 503 when the ML Engine cannot be reached."""

    import httpx

    class MockAsyncClient:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            pass

        async def post(self, url, json):
            raise httpx.ConnectError("Connection failed")

    monkeypatch.setattr(
        "app.api.routes.forecast.httpx.AsyncClient",
        MockAsyncClient,
    )

    response = patient_client.get("/patients/me/forecast")

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "The forecasting service is currently unavailable."
    )


def test_forecast_ml_http_error(patient_client, monkeypatch):
    """Return 502 when the ML Engine responds with an HTTP error."""

    import httpx

    class MockResponse:
        def raise_for_status(self):
            request = httpx.Request("POST", "http://ml-engine/v1/twin/state")
            response = httpx.Response(500, request=request)
            raise httpx.HTTPStatusError(
                "Internal Server Error",
                request=request,
                response=response,
            )

    class MockAsyncClient:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            pass

        async def post(self, url, json):
            return MockResponse()

    monkeypatch.setattr(
        "app.api.routes.forecast.httpx.AsyncClient",
        MockAsyncClient,
    )

    response = patient_client.get("/patients/me/forecast")

    assert response.status_code == 502
    assert response.json()["detail"] == (
        "The forecasting service returned an error (HTTP 500)."
    )


def test_forecast_ml_invalid_response(patient_client, monkeypatch):
    """Return 502 when the ML Engine response is malformed."""

    class MockResponse:
        def raise_for_status(self):
            pass

        def json(self):
            # Missing required response fields.
            return {"predictions": []}

    class MockAsyncClient:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            pass

        async def post(self, url, json):
            return MockResponse()

    monkeypatch.setattr(
        "app.api.routes.forecast.httpx.AsyncClient",
        MockAsyncClient,
    )

    response = patient_client.get("/patients/me/forecast")

    assert response.status_code == 502
    assert response.json()["detail"] == (
        "The forecasting service returned an invalid response."
    )