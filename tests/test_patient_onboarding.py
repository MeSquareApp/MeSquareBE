"""Tests for the patient onboarding flow (PUT /patients/me/profile)."""

import pytest


@pytest.fixture
def patient_client(auth):
    """A client authenticated as a user who just created a patient account."""
    resp = auth().post(
        "/users/me/create-m2-account",
        json={
            "first_name": "Jane",
            "last_name": "Doe",
            "role": "patient",
            "sex": "Female",
            "dob": "2006-11-01",
        },
    )
    assert resp.status_code == 201, resp.text
    return auth()


def test_onboarding_form_fills_deferred_attributes(patient_client):
    resp = patient_client.put(
        "/patients/me/profile",
        json={
            "race": ["Black", "White"],
            "region": "North America",
            "allergies": "peanut",
            "baseline_height_cm": 170,
            "baseline_weight_kg": 60,
            "smoking": "Never",
            "diagnosed_conditions": ["hypertension"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["race"] == ["Black", "White"]
    assert body["allergies"] == "peanut"
    assert body["baseline_height_cm"] == 170
    assert body["smoking"] == "Never"

    # The seeded attributes from account creation are untouched.
    assert body["date_of_birth"] == "2006-11-01"
    assert body["biological_sex"] == "Female"


def test_partial_update_leaves_other_fields_alone(patient_client):
    first = patient_client.put(
        "/patients/me/profile",
        json={"race": ["Black"], "allergies": "peanut"},
    )
    assert first.status_code == 200

    second = patient_client.put(
        "/patients/me/profile",
        json={"allergies": "none"},
    )
    assert second.status_code == 200, second.text
    assert second.json()["allergies"] == "none"
    # race was not in the second payload, so it keeps its value.
    assert second.json()["race"] == ["Black"]


def test_get_profile_reflects_onboarding(patient_client):
    patient_client.put(
        "/patients/me/profile",
        json={"race": ["Asian"], "region": "Europe"},
    )
    resp = patient_client.get("/patients/me/profile")
    assert resp.status_code == 200
    assert resp.json()["race"] == ["Asian"]
    assert resp.json()["region"] == "Europe"


def test_negative_measurements_rejected(patient_client):
    resp = patient_client.put(
        "/patients/me/profile",
        json={"baseline_height_cm": -5},
    )
    assert resp.status_code == 422


def test_patient_cannot_access_physician_endpoints(patient_client):
    resp = patient_client.put(
        "/physicians/me/profile",
        json={"medical_license_number": "TX-123", "specialty": "Cardiology"},
    )
    assert resp.status_code == 403
    assert "physician account is required" in resp.json()["detail"]


def test_physician_cannot_access_patient_endpoints(auth):
    resp = auth(sub="auth0|doc-1", email="doc@test.com").post(
        "/users/me/create-m2-account",
        json={"first_name": "Gregory", "last_name": "House", "role": "physician"},
    )
    assert resp.status_code == 201

    resp = auth(sub="auth0|doc-1", email="doc@test.com").put(
        "/patients/me/profile",
        json={"race": ["Black"]},
    )
    assert resp.status_code == 403
    assert "patient account is required" in resp.json()["detail"]
