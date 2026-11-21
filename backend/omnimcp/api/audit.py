"""Audit read routes (admin/operator only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import require_operator
from ..models import AuditEvent, User
from ..schemas import AuditOut

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


@router.get("", response_model=list[AuditOut])
async def list_events(
    action: str | None = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_operator),
):
    stmt = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(max(1, min(limit, 1000)))
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        AuditOut(
            id=e.id,
            ts=e.ts,
            actor_type=e.actor_type,
            actor_id=e.actor_id,
            action=e.action,
            resource_type=e.resource_type,
            resource_id=e.resource_id,
            detail=e.detail or {},
            approval=e.approval,
            outcome=e.outcome,
        )
        for e in rows
    ]
