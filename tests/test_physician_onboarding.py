"""Tests for the physician onboarding flow (PUT /physicians/me/profile)."""

import pytest


@pytest.fixture
def physician_client(auth):
    """A client authenticated as a user who just created a physician account."""
    resp = auth(sub="auth0|doc-1", email="doc@test.com").post(
        "/users/me/create-m2-account",
        json={"first_name": "Gregory", "last_name": "House", "role": "physician"},
    )
    assert resp.status_code == 201, resp.text
    return auth(sub="auth0|doc-1", email="doc@test.com")


def test_onboarding_fills_license_and_specialty(physician_client):
    resp = physician_client.put(
        "/physicians/me/profile",
        json={"medical_license_number": "TX-123456", "specialty": "Cardiology"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["medical_license_number"] == "TX-123456"
    assert resp.json()["specialty"] == "Cardiology"

    profile = physician_client.get("/physicians/me/profile")
    assert profile.status_code == 200
    assert profile.json()["specialty"] == "Cardiology"


def test_resubmitting_own_license_is_allowed(physician_client):
    first = physician_client.put(
        "/physicians/me/profile",
        json={"medical_license_number": "TX-123456", "specialty": "Cardiology"},
    )
    assert first.status_code == 200

    # The onboarding form resubmits the same license: no conflict with self.
    second = physician_client.put(
        "/physicians/me/profile",
        json={"medical_license_number": "TX-123456", "specialty": "Cardiology"},
    )
    assert second.status_code == 200


def test_blank_license_rejected(physician_client):
    resp = physician_client.put(
        "/physicians/me/profile",
        json={"medical_license_number": ""},
    )
    assert resp.status_code == 422


def test_duplicate_license_across_physicians_conflict(auth):
    doc = auth(sub="auth0|doc-1", email="doc1@test.com")
    doc.post(
        "/users/me/create-m2-account",
        json={"first_name": "A", "last_name": "Doc", "role": "physician"},
    )
    doc.put(
        "/physicians/me/profile",
        json={"medical_license_number": "TX-SHARED", "specialty": "Neurology"},
    )

    other = auth(sub="auth0|doc-2", email="doc2@test.com")
    other.post(
        "/users/me/create-m2-account",
        json={"first_name": "B", "last_name": "Doc", "role": "physician"},
    )
    resp = other.put(
        "/physicians/me/profile",
        json={"medical_license_number": "TX-SHARED", "specialty": "Oncology"},
    )
    assert resp.status_code == 409
    assert "license number" in resp.json()["detail"]
