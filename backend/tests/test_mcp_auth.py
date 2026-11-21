"""Regression tests for MCP endpoint bearer-token enforcement (THREAT_MODEL #10)."""

from __future__ import annotations

import httpx
import pytest
from conftest import auth, register_and_login

pytestmark = pytest.mark.asyncio

MCP = "/mcp"


def _set_mcp_token(monkeypatch, value: str) -> None:
    import omnimcp.config as cfg

    monkeypatch.setattr(cfg.settings, "mcp_token", value)


def _set_env(monkeypatch, value: str) -> None:
    import omnimcp.config as cfg

    monkeypatch.setattr(cfg.settings, "env", value)


def _set_proxy_flag(monkeypatch, value: bool) -> None:
    import omnimcp.config as cfg

    monkeypatch.setattr(cfg.settings, "mcp_unauthenticated_proxy", value)


async def test_mcp_requires_token_when_configured(client, monkeypatch):
    _set_mcp_token(monkeypatch, "tok-123")
    r = await client.get(MCP)
    assert r.status_code == 401
    assert r.headers.get("www-authenticate") == "Bearer"
    assert r.json()["detail"] == "missing bearer token"


async def test_mcp_rejects_wrong_token(client, monkeypatch):
    _set_mcp_token(monkeypatch, "tok-123")
    r = await client.get(MCP, headers=auth("wrong-token"))
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid token"


async def test_mcp_accepts_static_token(client, monkeypatch):
    _set_mcp_token(monkeypatch, "tok-123")
    r = await client.get(MCP, headers=auth("tok-123"))
    # Auth passes; the MCP transport may still reject a bare GET (406/400/307),
    # but it must NOT be the auth middleware's 401.
    assert r.status_code != 401, r.text


async def test_mcp_accepts_user_jwt(client, monkeypatch):
    token = await register_and_login(client, "mcp-admin@example.com")
    _set_mcp_token(monkeypatch, "tok-123")
    r = await client.get(MCP, headers=auth(token))
    assert r.status_code != 401, r.text


async def test_mcp_production_requires_token(client, monkeypatch):
    _set_env(monkeypatch, "production")
    _set_mcp_token(monkeypatch, "")
    r = await client.get(MCP)
    assert r.status_code == 401


async def test_mcp_production_proxy_flag_allows(client, monkeypatch):
    _set_env(monkeypatch, "production")
    _set_proxy_flag(monkeypatch, True)
    r = await client.get(MCP)
    assert r.status_code != 401, r.text
