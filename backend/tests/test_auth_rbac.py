"""Auth & RBAC tests."""

from __future__ import annotations

import pytest
from conftest import auth, register_and_login

pytestmark = pytest.mark.asyncio


async def test_healthz(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_first_user_is_admin_second_is_user(client):
    t1 = await register_and_login(client, "first@example.com")
    r = await client.get("/api/v1/auth/me", headers=auth(t1))
    assert r.json()["role"] == "admin"

    t2 = await register_and_login(client, "second@example.com")
    r = await client.get("/api/v1/auth/me", headers=auth(t2))
    assert r.json()["role"] == "user"


async def test_login_rejects_bad_password(client):
    await register_and_login(client)
    r = await client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": "wrong-password-x"}
    )
    assert r.status_code == 401


async def test_duplicate_registration_rejected(client):
    await register_and_login(client)
    r = await client.post(
        "/api/v1/auth/register", json={"email": "admin@example.com", "password": "S3cure-passw0rd!"}
    )
    assert r.status_code == 409


async def test_me_requires_token(client):
    r = await client.get("/api/v1/auth/me")
    assert r.status_code in (401, 403)


async def test_logout_revokes_token(client):
    t = await register_and_login(client)
    r = await client.post("/api/v1/auth/logout", headers=auth(t))
    assert r.status_code == 204
    r = await client.get("/api/v1/auth/me", headers=auth(t))
    assert r.status_code == 401


async def test_rbac_audit_requires_operator(client):
    await register_and_login(client, "admin@example.com")
    t_user = await register_and_login(client, "plain@example.com")
    r = await client.get("/api/v1/audit", headers=auth(t_user))
    assert r.status_code == 403


async def test_rbac_worker_registration_requires_operator(client):
    await register_and_login(client, "admin@example.com")
    t_user = await register_and_login(client, "plain@example.com")
    r = await client.post(
        "/api/v1/workers/register",
        json={"name": "w1", "capabilities": {}},
        headers=auth(t_user),
    )
    assert r.status_code == 403


async def test_password_too_short_rejected(client):
    r = await client.post(
        "/api/v1/auth/register", json={"email": "x@example.com", "password": "short"}
    )
    assert r.status_code == 422


async def test_audit_redacts_secrets(client):
    from omnimcp.audit import _redact

    detail = _redact({"user": "a", "password": "supersecret", "nested": {"token": "abc"}})
    assert detail["password"] == "[REDACTED]"
    assert detail["nested"]["token"] == "[REDACTED]"
    assert detail["user"] == "a"
