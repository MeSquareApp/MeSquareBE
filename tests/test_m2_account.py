"""Tests for POST /users/me/create-m2-account and GET /users/me."""


def test_requires_bearer_token(client):
    """A request without an Authorization header gets a 401."""
    resp = client.get("/users/me")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Not authenticated"


def test_creates_patient_account_with_seeded_profile(auth):
    """Patient signup creates the user row and the seeded patient row."""
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
    body = resp.json()
    assert body["email"] == "janedoe@test.com"
    assert body["first_name"] == "Jane"
    assert body["last_name"] == "Doe"
    assert body["role"] == "patient"

    # The patient row exists immediately, seeded with dob + sex, and the
    # deferred onboarding attributes are still null.
    profile = auth().get("/patients/me/profile")
    assert profile.status_code == 200, profile.text
    assert profile.json()["date_of_birth"] == "2006-11-01"
    assert profile.json()["biological_sex"] == "Female"
    assert profile.json()["race"] is None
    assert profile.json()["allergies"] is None


def test_creates_physician_account_with_empty_profile(auth):
    """Physician signup creates the user row and an empty physician row."""
    resp = auth(sub="auth0|doc-1", email="doc@test.com").post(
        "/users/me/create-m2-account",
        json={
            "first_name": "Gregory",
            "last_name": "House",
            "role": "physician",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["role"] == "physician"

    profile = auth(sub="auth0|doc-1", email="doc@test.com").get(
        "/physicians/me/profile"
    )
    assert profile.status_code == 200, profile.text
    assert profile.json()["medical_license_number"] is None
    assert profile.json()["specialty"] is None


def test_admin_self_registration_is_forbidden(auth):
    resp = auth().post(
        "/users/me/create-m2-account",
        json={"first_name": "Ada", "last_name": "Admin", "role": "admin"},
    )
    assert resp.status_code == 403
    assert "cannot be self-registered" in resp.json()["detail"]


def test_patient_requires_sex_and_dob(auth):
    resp = auth().post(
        "/users/me/create-m2-account",
        json={"first_name": "Jane", "last_name": "Doe", "role": "patient"},
    )
    assert resp.status_code == 422

    resp = auth().post(
        "/users/me/create-m2-account",
        json={
            "first_name": "Jane",
            "last_name": "Doe",
            "role": "patient",
            "sex": "Female",
        },
    )
    assert resp.status_code == 422


def test_physician_rejects_sex_and_dob(auth):
    resp = auth(sub="auth0|doc-2", email="doc2@test.com").post(
        "/users/me/create-m2-account",
        json={
            "first_name": "Gregory",
            "last_name": "House",
            "role": "physician",
            "sex": "Male",
        },
    )
    assert resp.status_code == 422


def test_duplicate_identity_conflict(auth):
    payload = {
        "first_name": "Jane",
        "last_name": "Doe",
        "role": "patient",
        "sex": "Female",
        "dob": "2006-11-01",
    }
    first = auth().post("/users/me/create-m2-account", json=payload)
    assert first.status_code == 201

    second = auth().post("/users/me/create-m2-account", json=payload)
    assert second.status_code == 409
    assert "already linked" in second.json()["detail"]


def test_duplicate_email_conflict(auth):
    payload = {
        "first_name": "Jane",
        "last_name": "Doe",
        "role": "patient",
        "sex": "Female",
        "dob": "2006-11-01",
    }
    first = auth().post("/users/me/create-m2-account", json=payload)
    assert first.status_code == 201

    # Same email, different Auth0 identity.
    second = auth(sub="auth0|other-user", email="janedoe@test.com").post(
        "/users/me/create-m2-account", json=payload
    )
    assert second.status_code == 409
    assert "email already exists" in second.json()["detail"]


def test_unverified_email_is_forbidden(auth):
    resp = auth(email_verified=False).post(
        "/users/me/create-m2-account",
        json={
            "first_name": "Jane",
            "last_name": "Doe",
            "role": "patient",
            "sex": "Female",
            "dob": "2006-11-01",
        },
    )
    assert resp.status_code == 403


def test_missing_email_claim_is_forbidden(auth):
    resp = auth(email=None).post(
        "/users/me/create-m2-account",
        json={
            "first_name": "Jane",
            "last_name": "Doe",
            "role": "patient",
            "sex": "Female",
            "dob": "2006-11-01",
        },
    )
    assert resp.status_code == 403


def test_get_me_returns_created_account(auth):
    auth().post(
        "/users/me/create-m2-account",
        json={
            "first_name": "Jane",
            "last_name": "Doe",
            "role": "patient",
            "sex": "Female",
            "dob": "2006-11-01",
        },
    )
    resp = auth().get("/users/me")
    assert resp.status_code == 200
    assert resp.json()["email"] == "janedoe@test.com"


def test_get_me_404_for_unmapped_identity(auth):
    """A valid token whose identity has no MeSquared account gets a 404."""
    resp = auth().get("/users/me")
    assert resp.status_code == 404
