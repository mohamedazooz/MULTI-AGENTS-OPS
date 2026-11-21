"""Bearer-token enforcement for the MCP endpoint (threat model #10).

Policy:
- A configured OMNIMCP_MCP_TOKEN is always accepted (constant-time compare).
- A valid user JWT (typ=user, active account, not revoked) is accepted.
- A valid agent key (hashed in the agent registry, enabled) is accepted.
- Unauthenticated requests are served only from loopback clients and only in
  non-production environments.
- In production with no OMNIMCP_MCP_TOKEN configured, unauthenticated access is
  refused unless OMNIMCP_MCP_UNAUTHENTICATED_PROXY=true explicitly declares that
  an authenticated reverse proxy fronts /mcp.
"""

from __future__ import annotations

import json

import jwt as pyjwt
from sqlalchemy import select

from .config import settings
from .security import constant_time_eq, decode_jwt, sha256_hex

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})


def _client_host(scope: dict) -> str:
    client = scope.get("client")
    if not client:
        return ""
    return str(client[0])


def _is_loopback(scope: dict) -> bool:
    return _client_host(scope) in _LOOPBACK_HOSTS


def _unauthenticated_allowed(scope: dict) -> bool:
    # Explicit operator declaration: an authenticated reverse proxy fronts /mcp.
    if settings.mcp_unauthenticated_proxy:
        return True
    # Non-production convenience: loopback clients only.
    return settings.env != "production" and _is_loopback(scope)


async def _authorize(token: str) -> bool:
    # 1) Static shared token (constant-time).
    if settings.mcp_token and constant_time_eq(token, settings.mcp_token):
        return True
    # 2) User JWT.
    try:
        payload = decode_jwt(token)
    except pyjwt.PyJWTError:
        payload = None
    if payload is not None:
        if payload.get("typ") != "user":
            return False
        from .db import get_session_factory
        from .models import User

        async with get_session_factory()() as session:
            user = await session.get(User, payload["sub"])
            if user is None or not user.is_active:
                return False
            if user.revocation_ts is not None:
                if int(payload.get("iat", 0)) < user.revocation_ts.timestamp():
                    return False
            return True
    # 3) Agent key (hashed at rest).
    from .db import get_session_factory
    from .models import Agent

    async with get_session_factory()() as session:
        res = await session.execute(
            select(Agent).where(Agent.token_hash == sha256_hex(token))
        )
        agent = res.scalar_one_or_none()
        return agent is not None and agent.enabled


async def _send_401(send, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"www-authenticate", b"Bearer"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class BearerAuthMiddleware:
    """Raw ASGI middleware enforcing the policy above on the mounted MCP app.

    Reads settings per request, so tests can monkeypatch without rebuilding apps.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers", [])
        }
        auth_header = headers.get("authorization", "")
        token = ""
        if auth_header[:7].lower() == "bearer ":
            token = auth_header[7:].strip()
        if not token:
            if _unauthenticated_allowed(scope):
                await self.app(scope, receive, send)
                return
            await _send_401(send, "missing bearer token")
            return
        if await _authorize(token):
            await self.app(scope, receive, send)
        else:
            await _send_401(send, "invalid token")
