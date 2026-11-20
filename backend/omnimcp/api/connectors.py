"""API Connector registry routes: register, validate, enable/disable, health, diagnostics."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import record
from ..db import get_session
from ..deps import current_user, require_operator
from ..errors import NotFound, ValidationFailed
from ..models import Connector, ConnectorKind, User, utcnow
from ..schemas import ConnectorCreate, ConnectorOut

router = APIRouter(prefix="/api/v1/connectors", tags=["connectors"])


def _out(c: Connector) -> ConnectorOut:
    return ConnectorOut(
        id=c.id,
        name=c.name,
        kind=c.kind.value,
        endpoint_url=c.endpoint_url,
        enabled=c.enabled,
        health=c.health,
        health_detail=c.health_detail,
        spec=c.spec or {},
        last_check=c.last_check,
        created_at=c.created_at,
    )


async def _get(session: AsyncSession, connector_id: str) -> Connector:
    c = await session.get(Connector, connector_id)
    if c is None:
        raise NotFound("connector not found")
    return c


@router.post("", response_model=ConnectorOut, status_code=201)
async def create(
    body: ConnectorCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    kind = ConnectorKind(body.kind)
    connector = Connector(
        name=body.name, kind=kind, endpoint_url=body.endpoint_url, spec=body.spec,
        enabled=body.enabled,
    )
    if kind in (ConnectorKind.mcp, ConnectorKind.http, ConnectorKind.openapi) and not body.endpoint_url.startswith(
        ("http://", "https://")
    ):
        raise ValidationFailed(f"{kind.value} connectors require an http(s) endpoint_url")
    session.add(connector)
    await record(
        session,
        actor_type="user",
        actor_id=user.email,
        action="connector.create",
        resource_type="connector",
        resource_id=connector.name,
        detail={"kind": body.kind},
    )
    await session.commit()
    await session.refresh(connector)
    return _out(connector)


@router.get("", response_model=list[ConnectorOut])
async def list_connectors(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(current_user),
):
    rows = (
        (await session.execute(select(Connector).order_by(Connector.created_at)))
        .scalars()
        .all()
    )
    return [_out(c) for c in rows]


@router.get("/{connector_id}", response_model=ConnectorOut)
async def get_connector(
    connector_id: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(current_user),
):
    return _out(await _get(session, connector_id))


@router.post("/{connector_id}/enable", response_model=ConnectorOut)
async def enable(
    connector_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    c = await _get(session, connector_id)
    c.enabled = True
    await record(
        session, actor_type="user", actor_id=user.email,
        action="connector.enable", resource_type="connector", resource_id=c.id,
    )
    await session.commit()
    return _out(c)


@router.post("/{connector_id}/disable", response_model=ConnectorOut)
async def disable(
    connector_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    c = await _get(session, connector_id)
    c.enabled = False
    await record(
        session, actor_type="user", actor_id=user.email,
        action="connector.disable", resource_type="connector", resource_id=c.id,
    )
    await session.commit()
    return _out(c)


@router.post("/{connector_id}/health")
async def health_check(
    connector_id: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(current_user),
):
    c = await _get(session, connector_id)
    ok, detail = await diagnose(c)
    c.health = "healthy" if ok else "unhealthy"
    c.health_detail = detail
    c.last_check = utcnow()
    await session.commit()
    return {"id": c.id, "health": c.health, "detail": detail}


async def diagnose(c: Connector) -> tuple[bool, str]:
    """Connection diagnostics. Only http-based connectors are checked live here."""
    if c.kind == ConnectorKind.internal:
        return True, "internal connector: no remote check"
    if c.kind == ConnectorKind.webhook:
        return True, "webhook accepted for registration; check fires on delivery"
    if c.kind == ConnectorKind.grpc:
        return False, "gRPC diagnostics not implemented yet"
    if c.kind not in (ConnectorKind.mcp, ConnectorKind.http, ConnectorKind.openapi):
        return False, f"unsupported kind {c.kind}"
    if not c.endpoint_url:
        return False, "no endpoint_url configured"
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            if c.kind == ConnectorKind.mcp:
                r = await client.post(
                    c.endpoint_url,
                    json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                    headers={"Accept": "application/json, text/event-stream"},
                )
                return r.status_code < 500, f"initialize -> HTTP {r.status_code}"
            r = await client.get(c.endpoint_url)
            return r.status_code < 500, f"GET -> HTTP {r.status_code}"
    except httpx.HTTPError as e:
        return False, f"connection failed: {type(e).__name__}"


@router.delete("/{connector_id}", status_code=204)
async def delete(
    connector_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    c = await _get(session, connector_id)
    await session.delete(c)
    await record(
        session, actor_type="user", actor_id=user.email,
        action="connector.delete", resource_type="connector", resource_id=connector_id,
    )
    await session.commit()
