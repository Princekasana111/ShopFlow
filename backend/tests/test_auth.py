import pytest

pytestmark = pytest.mark.django_db


def test_register_login_and_me(anon_client):
    r = anon_client.post("/api/auth/register/", {"username": "carol", "email": "carol@example.com", "password": "Sup3r-secret!"}, format="json")
    assert r.status_code == 201, r.data
    assert "password" not in r.data

    r = anon_client.post("/api/auth/login/", {"username": "carol", "password": "Sup3r-secret!"}, format="json")
    assert r.status_code == 200
    token = r.data["access"]

    anon_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    r = anon_client.get("/api/auth/me/")
    assert r.status_code == 200 and r.data["username"] == "carol" and r.data["is_staff"] is False


def test_register_rejects_weak_password_and_duplicate_email(anon_client, user):
    r = anon_client.post("/api/auth/register/", {"username": "dave", "email": "dave@example.com", "password": "12345678"}, format="json")
    assert r.status_code == 400
    r = anon_client.post("/api/auth/register/", {"username": "eve", "email": user.email.upper(), "password": "Sup3r-secret!"}, format="json")
    assert r.status_code == 400 and "email" in r.data


def test_me_requires_auth(anon_client):
    assert anon_client.get("/api/auth/me/").status_code == 401
