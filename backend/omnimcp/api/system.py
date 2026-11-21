"""System routes: health, ready, metrics, scheduler tick (dev), support report."""

from __future__ import annotations

import logging
import os
import sys

from fastapi import APIRouter, Depends, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import __version__
from ..config import settings
from ..db import get_session
from ..deps import require_operator
from ..models import AuditEvent, Connector, Job, JobState, User, Worker, utcnow
from ..security import create_jwt, decode_jwt, hash_password, verify_password

log = logging.getLogger("omnimcp.system")

# Shared Prometheus registry (asgi application-scoped; per-process).
REGISTRY = CollectorRegistry(auto_describe=True)
HTTP_REQUESTS = Counter(
    "omnimcp_http_requests_total", "HTTP requests", ["method", "path", "status"], registry=REGISTRY
)
HTTP_LATENCY = Histogram(
    "omnimcp_http_request_seconds", "HTTP latency", ["method", "path"], registry=REGISTRY
)
JOBS_DISPATCHED = Counter(
    "omnimcp_jobs_dispatched_total", "Jobs dispatched to workers", registry=REGISTRY
)
JOBS_FINISHED = Counter(
    "omnimcp_jobs_finished_total", "Jobs finished", ["state"], registry=REGISTRY
)
WORKERS_ONLINE = Gauge(
    "omnimcp_workers_online", "Workers currently online", registry=REGISTRY
)
QUEUE_DEPTH = Gauge("omnimcp_queue_depth", "Jobs queued", registry=REGISTRY)

router = APIRouter(tags=["system"])


@router.get("/healthz")
async def healthz():
    return {"status": "ok", "version": __version__, "time": utcnow().isoformat() + "Z"}


@router.get("/metrics")
async def metrics():
    """Prometheus exposition. Protect upstream (reverse proxy / network policy)."""
    if not settings.metrics_enabled:
        return Response(status_code=404)
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


@router.get("/readyz")
async def readyz(session: AsyncSession = Depends(get_session)):
    users = (await session.execute(select(func.count()).select_from(User))).scalar_one()
    workers = (await session.execute(select(func.count()).select_from(Worker))).scalar_one()
    jobs_queued = (
        await session.execute(
            select(func.count()).select_from(Job).where(Job.state == JobState.QUEUED)
        )
    ).scalar_one()
    jobs_running = (
        await session.execute(
            select(func.count()).select_from(Job).where(Job.state == JobState.RUNNING)
        )
    ).scalar_one()
    connectors = (await session.execute(select(func.count()).select_from(Connector))).scalar_one()
    audit_events = (await session.execute(select(func.count()).select_from(AuditEvent))).scalar_one()
    return {
        "status": "ready",
        "version": __version__,
        "env": settings.env,
        "python": sys.version.split()[0],
        "pid": os.getpid(),
        "users": users,
        "workers": workers,
        "jobs": {"queued": jobs_queued, "running": jobs_running},
        "connectors": connectors,
        "audit_events": audit_events,
    }


@router.post("/api/v1/system/scheduler/tick")
async def scheduler_tick(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_operator),
):
    """Run one scheduler pass now (ops debugging, tests). Harmless when idle."""
    import datetime as dt

    from omnimcp.db import get_session_factory
    from omnimcp.jobs import tick as scheduler_tick_once

    _ = dt, get_session_factory
    counts = await scheduler_tick_once(session)
    await session.commit()
    return counts


@router.get("/api/v1/system/support-report")
async def support_report(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_operator),
):
    """Aggregated operational snapshot for diagnostics (no secrets)."""
    rows = (
        (
            await session.execute(select(Job.state, func.count()).group_by(Job.state))
        )
        .all()
    )
    jobs_by_state = {state.value: count for state, count in rows}
    workers = (await session.execute(select(Worker))).scalars().all()
    return {
        "version": __version__,
        "env": settings.env,
        "jobs_by_state": jobs_by_state,
        "workers": [
            {
                "id": w.id,
                "health": w.health.value,
                "version": w.version,
                "capabilities_subset": {
                    k: (w.capabilities or {}).get(k)
                    for k in ("system", "arch", "cpu_cores", "ram_total_mb")
                },
                "active_jobs": w.active_jobs,
                "last_heartbeat": w.last_heartbeat.isoformat() if w.last_heartbeat else None,
            }
            for w in workers
        ],
        "audit_total": (
            await session.execute(select(func.count()).select_from(AuditEvent))
        ).scalar_one(),
        "crypto_selftest": {
            "jwt_roundtrip": bool(
                decode_jwt(
                    create_jwt("selftest", ttl_seconds=5)
                )["sub"] == "selftest"
            ),
            "argon2": verify_password(hash_password("probe-password"), "probe-password"),
        },
    }
