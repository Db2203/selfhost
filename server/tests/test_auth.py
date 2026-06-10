import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app.config import get_settings
from app.security import JWT_ALGORITHM


def login(client, test_user, device_name="pytest-device"):
    username, password = test_user
    response = client.post(
        "/auth/login",
        json={"username": username, "password": password, "device_name": device_name},
    )
    assert response.status_code == 200
    return response.json()


def auth_header(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_login_returns_tokens_and_registers_device(client, test_user):
    tokens = login(client, test_user, device_name="dhruv-laptop")
    assert tokens["access_token"]
    assert tokens["refresh_token"]

    devices = client.get("/devices", headers=auth_header(tokens))
    assert devices.status_code == 200
    names = [d["name"] for d in devices.json()]
    assert "dhruv-laptop" in names


def test_login_with_wrong_password_is_rejected(client, test_user):
    username, _ = test_user
    response = client.post(
        "/auth/login",
        json={"username": username, "password": "wrong", "device_name": "x"},
    )
    assert response.status_code == 401


def test_login_with_unknown_user_is_rejected(client):
    response = client.post(
        "/auth/login",
        json={"username": "nobody", "password": "whatever", "device_name": "x"},
    )
    assert response.status_code == 401


def test_protected_route_without_token_is_401(client):
    assert client.get("/devices").status_code == 401


def test_protected_route_with_garbage_token_is_401(client):
    response = client.get("/devices", headers={"Authorization": "Bearer not.a.jwt"})
    assert response.status_code == 401


def test_expired_access_token_is_401(client, test_user):
    tokens = login(client, test_user)
    settings = get_settings()
    expired = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "dev": tokens["device_id"],
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            "type": "access",
        },
        settings.secret_key,
        algorithm=JWT_ALGORITHM,
    )
    response = client.get("/devices", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401


def test_refresh_rotates_and_old_token_dies(client, test_user):
    tokens = login(client, test_user)

    first = client.post(
        "/auth/refresh",
        json={"device_id": tokens["device_id"], "refresh_token": tokens["refresh_token"]},
    )
    assert first.status_code == 200
    rotated = first.json()
    assert rotated["refresh_token"] != tokens["refresh_token"]

    # The pre-rotation token must be single-use.
    replay = client.post(
        "/auth/refresh",
        json={"device_id": tokens["device_id"], "refresh_token": tokens["refresh_token"]},
    )
    assert replay.status_code == 401

    # The rotated token works.
    second = client.post(
        "/auth/refresh",
        json={"device_id": rotated["device_id"], "refresh_token": rotated["refresh_token"]},
    )
    assert second.status_code == 200


def test_revoked_device_loses_access_immediately(client, test_user):
    laptop = login(client, test_user, device_name="laptop")
    lost_phone = login(client, test_user, device_name="lost-phone")

    response = client.delete(
        f"/devices/{lost_phone['device_id']}", headers=auth_header(laptop)
    )
    assert response.status_code == 204

    # Its (unexpired) access token is dead on the very next request...
    assert client.get("/devices", headers=auth_header(lost_phone)).status_code == 401
    # ...and so is its refresh token.
    refresh = client.post(
        "/auth/refresh",
        json={
            "device_id": lost_phone["device_id"],
            "refresh_token": lost_phone["refresh_token"],
        },
    )
    assert refresh.status_code == 401


def test_cannot_revoke_another_users_device(client, test_user):
    tokens = login(client, test_user)
    response = client.delete(f"/devices/{uuid.uuid4()}", headers=auth_header(tokens))
    assert response.status_code == 404
