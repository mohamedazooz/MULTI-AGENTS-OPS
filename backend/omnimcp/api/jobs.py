"""Job routes: submit, list, get, cancel, logs, events."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import record
from ..db import get_session
from ..deps import current_user
from ..errors import Forbidden, NotFound
from ..jobs import enqueue, request_cancel
from ..models import Job, JobEvent, JobLog, User
from ..schemas import JobCreate, JobOut

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


def _out(job: Job) -> JobOut:
    return JobOut(
        id=job.id,
        kind=job.kind,
        state=job.state.value,
        payload=job.payload or {},
        priority=job.priority,
        workspace_id=job.workspace_id,
        worker_id=job.worker_id,
        required_capabilities=job.required_capabilities or [],
        min_ram_mb=job.min_ram_mb,
        min_cpu=job.min_cpu,
        timeout_s=job.timeout_s,
        attempt=job.attempt,
        max_retries=job.max_retries,
        result=job.result,
        error=job.error,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.post("", response_model=JobOut, status_code=201)
async def submit(
    body: JobCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    job, created = await enqueue(
        session,
        kind=body.kind,
        payload=body.payload,
        owner_id=user.id,
        idempotency_key=body.idempotency_key,
        workspace_id=body.workspace_id,
        required_capabilities=body.required_capabilities,
        required_os=body.required_os,
        required_arch=body.required_arch,
        min_cpu=body.min_cpu,
        min_ram_mb=body.min_ram_mb,
        required_gpu_mb=body.required_gpu_mb,
        untrusted=body.untrusted,
        timeout_s=body.timeout_s,
        priority=body.priority,
        max_retries=body.max_retries,
    )
    if created:
        await record(
            session,
            actor_type="user",
            actor_id=user.email,
            action="job.submit",
            resource_type="job",
            resource_id=job.id,
            detail={"kind": job.kind, "idempotency_key": body.idempotency_key},
        )
    await session.commit()
    await session.refresh(job)
    return _out(job)


@router.get("", response_model=list[JobOut])
async def list_jobs(
    state: str | None = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    stmt = select(Job).order_by(Job.created_at.desc()).limit(max(1, min(limit, 500)))
    if user.role.value != "admin":
        stmt = stmt.where(Job.owner_id.in_([user.id]))
    if state:
        stmt = stmt.where(Job.state == state.upper())
    jobs = (await session.execute(stmt)).scalars().all()
    return [_out(j) for j in jobs]


@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    job = await session.get(Job, job_id)
    if job is None or (user.role.value != "admin" and job.owner_id not in (None, user.id)):
        raise NotFound(f"job {job_id} not found")
    return _out(job)


@router.get("/{job_id}/logs")
async def get_logs(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    job = await session.get(Job, job_id)
    if job is None or (user.role.value != "admin" and job.owner_id not in (None, user.id)):
        raise NotFound(f"job {job_id} not found")
    logs = (
        (
            await session.execute(
                select(JobLog).where(JobLog.job_id == job_id).order_by(JobLog.id.asc()).limit(5000)
            )
        )
        .scalars()
        .all()
    )
    return {"job_id": job_id, "logs": [{"ts": e.ts, "stream": e.stream, "line": e.line} for e in logs]}


@router.get("/{job_id}/events")
async def get_events(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    job = await session.get(Job, job_id)
    if job is None or (user.role.value != "admin" and job.owner_id not in (None, user.id)):
        raise NotFound(f"job {job_id} not found")
    events = (
        (
            await session.execute(
                select(JobEvent)
                .where(JobEvent.job_id == job_id)
                .order_by(JobEvent.id.asc())
                .limit(1000)
            )
        )
        .scalars()
        .all()
    )
    return {"job_id": job_id, "events": [{"ts": e.ts, "state": e.state, "detail": e.detail} for e in events]}


@router.post("/{job_id}/cancel", response_model=JobOut)
async def cancel(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    job = await session.get(Job, job_id)
    if job is None or (user.role.value != "admin" and job.owner_id not in (None, user.id)):
        raise NotFound(f"job {job_id} not found")
    await request_cancel(session, job_id, owner_id=None)
    await record(
        session,
        actor_type="user",
        actor_id=user.email,
        action="job.cancel",
        resource_type="job",
        resource_id=job_id,
    )
    await session.commit()
    await session.refresh(job)
    return _out(job)


@router.post("/{job_id}/cancel-approval")
async def cancel_approval(
    job_id: str,
    approve: bool = True,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    """Privileged-action approval gate for long-running job cancellation."""
    job = await session.get(Job, job_id)
    if job is None or (user.role.value != "admin" and job.owner_id not in (None, user.id)):
        raise NotFound(f"job {job_id} not found")
    if user.role.value != "admin":
        raise Forbidden("approval requires admin role")
    await record(
        session,
        actor_type="user",
        actor_id=user.email,
        action="job.cancel_approval",
        resource_type="job",
        resource_id=job_id,
        approval=approve,
    )
    await session.commit()
    return {"job_id": job_id, "approved": approve}
