"""FastAPI auth dependencies and permission helpers."""

from __future__ import annotations

import jwt as pyjwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_session
from .errors import Forbidden, NotFound, Unauthorized
from .models import Agent, Role, User, Worker
from .security import decode_jwt, sha256_hex

_bearer = HTTPBearer(auto_error=True)


async def current_user(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    if creds.scheme.lower() != "bearer":
        raise Unauthorized("Bearer token required")
    try:
        payload = decode_jwt(creds.credentials)
    except pyjwt.ExpiredSignatureError as e:
        raise Unauthorized("Token expired") from e
    except pyjwt.PyJWTError as e:
        raise Unauthorized("Invalid token") from e
    if payload.get("typ") != "user":
        raise Unauthorized("Not a user token")
    user = await session.get(User, payload["sub"])
    if user is None or not user.is_active:
        raise Unauthorized("Unknown or disabled user")
    if user.revocation_ts is not None:
        iat = int(payload.get("iat", 0))
        if iat < user.revocation_ts.timestamp():
            raise Unauthorized("Token revoked")
    return user


def require_roles(*roles: Role):
    async def _check(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise Forbidden("Insufficient role")
        return user

    return _check


require_admin = require_roles(Role.admin)
require_operator = require_roles(Role.admin, Role.operator)


def owns_workspace(user: User, ws_owner_id: str | None) -> bool:
    if ws_owner_id is None:
        return True
    return ws_owner_id == user.id or user.role == Role.admin


async def current_worker(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> Worker:
    try:
        payload = decode_jwt(creds.credentials)
    except pyjwt.PyJWTError as e:
        raise Unauthorized("Invalid worker token") from e
    if payload.get("typ") != "worker":
        raise Unauthorized("Not a worker token")
    worker = await session.get(Worker, payload["sub"])
    if worker is None:
        raise NotFound("Worker not found")
    if worker.health.value == "quarantined":
        raise Forbidden("Worker quarantined")
    return worker


async def current_agent(
    request: Request, session: AsyncSession = Depends(get_session)
) -> Agent | None:
    """Resolve an agent identity from a bearer token (for MCP clients)."""
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        if settings.mcp_token:
            raise Unauthorized("Missing bearer token")
        return None
    token = auth.split(" ", 1)[1].strip()
    try:
        payload = decode_jwt(token)
        if payload.get("typ") == "user":
            return None
    except pyjwt.PyJWTError:
        pass
    res = await session.execute(select(Agent).where(Agent.token_hash == sha256_hex(token)))
    agent = res.scalar_one_or_none()
    if agent is None or not agent.enabled:
        raise Unauthorized("Invalid or disabled agent token")
    return agent
