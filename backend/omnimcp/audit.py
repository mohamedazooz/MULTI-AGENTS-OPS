"""Audit service — append-only trail of who did what, never logging secret values."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from .models import AuditEvent

# Keys whose values must never be persisted in audit details
_REDACT_KEYS = {"password", "token", "secret", "authorization", "api_key", "env", "credentials"}


def _redact(detail: dict) -> dict:
    out = {}
    for k, v in detail.items():
        if k.lower() in _REDACT_KEYS:
            out[k] = "[REDACTED]"
        elif isinstance(v, dict):
            out[k] = _redact(v)
        else:
            out[k] = v
    return out


async def record(
    session: AsyncSession,
    *,
    actor_type: str,
    actor_id: str,
    action: str,
    resource_type: str = "",
    resource_id: str = "",
    detail: dict | None = None,
    workflow_id: str = "",
    approval: bool = False,
    outcome: str = "success",
) -> AuditEvent:
    ev = AuditEvent(
        actor_type=actor_type,
        actor_id=actor_id[:255],
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id or "")[:255],
        detail=_redact(detail or {}),
        workflow_id=workflow_id,
        approval=approval,
        outcome=outcome,
    )
    session.add(ev)
    return ev
