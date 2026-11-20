"""Connector registry + audit endpoints + system report tests."""

from __future__ import annotations

import pytest
from conftest import auth, register_and_login

pytestmark = pytest.mark.asyncio


async def test_connector_crud_and_validation(client):
    t = await register_and_login(client)
    h = auth(t)

    r = await client.post(
        "/api/v1/connectors",
        json={"name": "example-api", "kind": "http", "endpoint_url": "https://example.com/"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    cid = r.json()["id"]

    r = await client.post(
        "/api/v1/connectors",
        json={"name": "bad-kind", "kind": "carrier-pigeon", "endpoint_url": ""},
        headers=h,
    )
    assert r.status_code == 422

    r = await client.post(
        "/api/v1/connectors",
        json={"name": "mcp-no-url", "kind": "mcp", "endpoint_url": ""},
        headers=h,
    )
    assert r.status_code == 422

    r = await client.post(f"/api/v1/connectors/{cid}/enable", headers=h)
    assert r.json()["enabled"] is True

    r = await client.post(f"/api/v1/connectors/{cid}/health", headers=h)
    assert r.status_code == 200

    r = await client.get("/api/v1/connectors", headers=h)
    assert len(r.json()) == 1

    r = await client.delete(f"/api/v1/connectors/{cid}", headers=h)
    assert r.status_code == 204


async def test_connector_health_unreachable(client):
    t = await register_and_login(client)
    h = auth(t)
    r = await client.post(
        "/api/v1/connectors",
        json={"name": "dead-api", "kind": "http", "endpoint_url": "http://127.0.0.1:9/health"},
        headers=h,
    )
    cid = r.json()["id"]
    r = await client.post(f"/api/v1/connectors/{cid}/health", headers=h)
    body = r.json()
    assert body["health"] == "unhealthy"


async def test_agent_crud(client):
    t = await register_and_login(client)
    h = auth(t)
    r = await client.post(
        "/api/v1/agents",
        json={"name": "claude-code-1", "client_flavor": "claude-code"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["token"].startswith("omniagent_")
    agent_id = body["id"]

    r = await client.post("/api/v1/agents", json={"name": "claude-code-1"}, headers=h)
    assert r.status_code == 409

    r = await client.get("/api/v1/agents", headers=h)
    assert len(r.json()) == 1

    r = await client.post(f"/api/v1/agents/{agent_id}/disable", headers=h)
    assert r.json()["enabled"] is False

    r = await client.post(f"/api/v1/agents/{agent_id}/enable", headers=h)
    assert r.json()["enabled"] is True


async def test_audit_trail_recorded_and_readable(client):
    t = await register_and_login(client)
    h = auth(t)
    await client.post("/api/v1/workspaces", json={"name": "audit-ws"}, headers=h)
    r = await client.get("/api/v1/audit", headers=h)
    assert r.status_code == 200
    actions = [e["action"] for e in r.json()]
    assert "auth.register" in actions
    assert "workspace.create" in actions


async def test_support_report_operator_only(client):
    t = await register_and_login(client)
    r = await client.get("/api/v1/system/support-report", headers=auth(t))
    assert r.status_code == 200
    body = r.json()
    assert body["crypto_selftest"]["jwt_roundtrip"] is True
    assert body["crypto_selftest"]["argon2"] is True
