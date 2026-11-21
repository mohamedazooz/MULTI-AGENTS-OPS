"""Worker registry routes: registration, heartbeat, capability report, claim, status."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import record
from ..config import settings
from ..db import get_session
from ..deps import current_user, current_worker, require_admin
from ..errors import Conflict, Forbidden, NotFound, Unauthorized
from ..jobs import add_log, claim_job, report_result
from ..models import Job, User, Worker, WorkerHealth, utcnow
from ..schemas import (
    ClaimOut,
    HeartbeatIn,
    JobStatusIn,
    WorkerOut,
    WorkerRegister,
)
from ..security import create_jwt, rate_limit_check, sha256_hex

router = APIRouter(prefix="/api/v1/workers", tags=["workers"])


def _out(w: Worker) -> WorkerOut:
    return WorkerOut(
        id=w.id,
        name=w.name,
        health=w.health.value,
        version=w.version,
        capabilities=w.capabilities or {},
        limits=w.limits or {},
        trust_level=w.trust_level,
        active_jobs=w.active_jobs,
        max_active_jobs=w.max_active_jobs,
        last_heartbeat=w.last_heartbeat,
        registered_at=w.registered_at,
    )


@router.post("/register", status_code=201)
async def register(
    body: WorkerRegister,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    """Register a worker; requires an operator/admin bearer token; returns worker JWT once."""
    if user.role.value == "user" and not settings.allow_worker_registration_by_user:
        raise Forbidden("operator/admin role required to register workers")
    if not rate_limit_check(f"worker-register:{body.name}", limit=settings.worker_register_rate_limit, window=60):
        raise Unauthorized("Too many worker registrations")
    existing = (
        await session.execute(select(Worker).where(Worker.name == body.name))
    ).scalar_one_or_none()
    if existing is not None:
        raise Conflict(f"worker name {body.name!r} already registered")
    token = create_jwt(sub="", typ="worker", ttl_seconds=1)
    w = Worker(
        name=body.name,
        token_hash=sha256_hex(token),
        owner_id=user.id,
        health=WorkerHealth.online,
        version=body.version,
        capabilities=body.capabilities or {},
        max_active_jobs=body.max_active_jobs,
        trust_level=body.trust_level,
        last_heartbeat=utcnow(),
    )
    session.add(w)
    await session.flush()
    token = create_jwt(sub=w.id, typ="worker", ttl_seconds=settings.worker_token_ttl_seconds)
    w.token_hash = sha256_hex(token)
    await record(
        session,
        actor_type="user",
        actor_id=user.email,
        action="worker.register",
        resource_type="worker",
        resource_id=w.id,
        detail={"name": w.name, "trust_level": w.trust_level},
    )
    await session.commit()
    await session.refresh(w)
    return {"worker": _out(w), "token": token}


@router.get("", response_model=list[WorkerOut])
async def list_workers(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(current_user),
):
    workers = (
        (await session.execute(select(Worker).order_by(Worker.registered_at))).scalars().all()
    )
    return [_out(w) for w in workers]


@router.get("/me", response_model=WorkerOut)
async def me(worker: Worker = Depends(current_worker)):
    return _out(worker)


@router.post("/me/heartbeat", response_model=WorkerOut)
async def heartbeat(
    body: HeartbeatIn,
    worker: Worker = Depends(current_worker),
    session: AsyncSession = Depends(get_session),
):
    if body.capabilities:
        worker.capabilities = body.capabilities
    if body.version:
        worker.version = body.version
    worker.active_jobs = body.active_jobs
    if body.ram_available_mb is not None:
        worker.capabilities = {
            **(worker.capabilities or {}),
            "ram_available_mb": body.ram_available_mb,
        }
    if body.health is not None:
        if body.health not in {h.value for h in WorkerHealth}:
            raise Unauthorized("unknown health state")
        if worker.health != WorkerHealth.quarantined:
            worker.health = WorkerHealth(body.health)
    elif worker.health == WorkerHealth.offline:
        worker.health = WorkerHealth.online
    worker.last_heartbeat = utcnow()
    await session.commit()
    await session.refresh(worker)
    return _out(worker)


@router.post("/me/claim", response_model=ClaimOut)
async def claim(
    worker: Worker = Depends(current_worker),
    session: AsyncSession = Depends(get_session),
):
    worker.last_heartbeat = utcnow()
    if worker.health == WorkerHealth.offline:
        worker.health = WorkerHealth.online
    job = await claim_job(session, worker)
    await session.commit()
    if job is None:
        return ClaimOut()
    return ClaimOut(
        job_id=job.id,
        kind=job.kind,
        payload=job.payload,
        cancel_requested=job.cancel_requested,
        timeout_s=job.timeout_s,
    )


async def _own_job(session: AsyncSession, worker: Worker, job_id: str) -> Job:
    job = (
        await session.execute(select(Job).where(Job.id == job_id, Job.worker_id == worker.id))
    ).scalar_one_or_none()
    if job is None:
        raise NotFound(f"job {job_id} not assigned to this worker")
    return job


@router.post("/me/jobs/{job_id}/logs", status_code=204)
async def push_logs(
    job_id: str,
    lines: list[dict],
    worker: Worker = Depends(current_worker),
    session: AsyncSession = Depends(get_session),
):
    job = await _own_job(session, worker, job_id)
    for item in lines[:500]:
        if not isinstance(item, dict):
            continue
        await add_log(
            session, job.id, str(item.get("stream", "stdout"))[:16], str(item.get("line", ""))
        )
    job.last_heartbeat = None
    worker.last_heartbeat = utcnow()
    await session.commit()


@router.post("/me/jobs/{job_id}/status", response_model=ClaimOut)
async def job_status(
    job_id: str,
    body: JobStatusIn,
    worker: Worker = Depends(current_worker),
    session: AsyncSession = Depends(get_session),
):
    job = await _own_job(session, worker, job_id)
    await report_result(session, job, success=body.success, result=body.result, error=body.error)
    worker.last_heartbeat = utcnow()
    await session.commit()
    return ClaimOut(job_id=job.id, cancel_requested=job.cancel_requested)


@router.post("/me/jobs/{job_id}/cancel-check", response_model=ClaimOut)
async def cancel_check(
    job_id: str,
    worker: Worker = Depends(current_worker),
    session: AsyncSession = Depends(get_session),
):
    await _own_job(session, worker, job_id)
    worker.last_heartbeat = utcnow()
    await session.commit()
    job = await session.get(Job, job_id)
    return ClaimOut(job_id=job_id, cancel_requested=job.cancel_requested)


@router.get("/{worker_id}", response_model=WorkerOut)
async def get_worker(
    worker_id: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(current_user),
):
    w = await session.get(Worker, worker_id)
    if w is None:
        raise NotFound("worker not found")
    return _out(w)


@router.post("/{worker_id}/enable", response_model=WorkerOut)
async def enable(
    worker_id: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    w = await session.get(Worker, worker_id)
    if w is None:
        raise NotFound("worker not found")
    if w.health == WorkerHealth.quarantined:
        w.health = WorkerHealth.online
    await session.commit()
    return _out(w)


@router.post("/{worker_id}/disable", response_model=WorkerOut)
async def disable(
    worker_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    w = await session.get(Worker, worker_id)
    if w is None:
        raise NotFound("worker not found")
    w.health = WorkerHealth.quarantined
    await record(
        session,
        actor_type="user",
        actor_id=user.email,
        action="worker.quarantine",
        resource_type="worker",
        resource_id=w.id,
    )
    await session.commit()
    return _out(w)
