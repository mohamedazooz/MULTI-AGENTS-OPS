"""Job engine: validation, enqueue, state transitions, retries, timeouts, cancellation.

Job states (per spec):
CREATED -> VALIDATING -> QUEUED -> SCHEDULING -> ASSIGNED -> RUNNING ->
CANCELLING -> CANCELLED | SUCCEEDED | FAILED | RETRYING | EXPIRED
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from .errors import Conflict, NotFound, ValidationFailed
from .models import Job, JobEvent, JobLog, JobState, Worker, WorkerHealth, utcnow

log = logging.getLogger("omnimcp.jobs")

_ASSIGNED_STATES = [JobState.ASSIGNED, JobState.RUNNING, JobState.CANCELLING]
_TERMINAL_STATES = [
    JobState.CANCELLED,
    JobState.SUCCEEDED,
    JobState.FAILED,
    JobState.EXPIRED,
]


def transition(session: Session, job: Job, new_state: JobState, detail: str = "") -> None:
    job.state = new_state
    session.add(JobEvent(job_id=job.id, state=new_state.value, detail=detail[:2000]))
    log.info("job %s -> %s %s", job.id[:8], new_state.value, detail)


async def add_log(session: AsyncSession, job_id: str, stream: str, line: str) -> None:
    session.add(JobLog(job_id=job_id, stream=stream, line=line[:8000]))


async def enqueue(
    session: AsyncSession,
    *,
    kind: str,
    payload: dict,
    owner_id: str | None,
    idempotency_key: str | None = None,
    workspace_id: str | None = None,
    required_capabilities: list[str] | None = None,
    required_os: str | None = None,
    required_arch: str | None = None,
    min_cpu: int = 1,
    min_ram_mb: int = 256,
    required_gpu_mb: int = 0,
    untrusted: bool = False,
    timeout_s: int | None = None,
    priority: int = 5,
    max_retries: int | None = None,
) -> tuple[Job, bool]:
    """Create + queue a job. Returns (job, created). Idempotent on idempotency_key."""
    from .config import settings

    if not kind or not kind.strip():
        raise ValidationFailed("kind is required")
    if not isinstance(payload, dict):
        raise ValidationFailed("payload must be an object")
    min_cpu = max(1, min(int(min_cpu), 1024))
    min_ram_mb = max(64, min(int(min_ram_mb), 1024 * 1024))
    priority = max(0, min(int(priority), 9))
    if max_retries is None:
        max_retries = settings.max_retries
    timeout_s = int(timeout_s or settings.default_job_timeout_seconds)
    if timeout_s < 1 or timeout_s > 7 * 86400:
        raise ValidationFailed("timeout_s must be between 1 and 7 days")

    if idempotency_key:
        stmt = select(Job).where(Job.owner_id == owner_id, Job.idempotency_key == idempotency_key)
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            return existing, False

    job = Job(
        kind=kind.strip(),
        payload=payload,
        owner_id=owner_id,
        idempotency_key=idempotency_key,
        workspace_id=workspace_id,
        required_capabilities=required_capabilities or [],
        required_os=required_os,
        required_arch=required_arch,
        min_cpu=min_cpu,
        min_ram_mb=min_ram_mb,
        required_gpu_mb=required_gpu_mb,
        untrusted=untrusted,
        timeout_s=timeout_s,
        priority=priority,
        max_retries=max(0, int(max_retries)),
    )
    session.add(job)
    await session.flush()
    transition(session, job, JobState.QUEUED)
    return job, True


async def request_cancel(session: AsyncSession, job_id: str, owner_id: str | None) -> Job:
    job = await session.get(Job, job_id)
    if job is None:
        raise NotFound(f"job {job_id} not found")
    if owner_id is not None and job.owner_id not in (None, owner_id):
        raise NotFound(f"job {job_id} not found")
    if job.state in _TERMINAL_STATES:
        raise Conflict(f"job {job_id} already finished ({job.state.value})")
    if job.state in (JobState.CREATED, JobState.VALIDATING, JobState.QUEUED, JobState.SCHEDULING):
        transition(session, job, JobState.CANCELLED, "cancelled before dispatch")
    elif job.state in _ASSIGNED_STATES:
        job.cancel_requested = True
        transition(session, job, JobState.CANCELLING, "cancel requested; terminating on worker")
    return job


def worker_compatible(worker: Worker, job: Job) -> tuple[bool, str]:
    if worker.health != WorkerHealth.online:
        return False, f"health={worker.health.value}"
    if worker.active_jobs >= worker.max_active_jobs:
        return False, "at max_active_jobs"
    caps = worker.capabilities or {}
    if job.untrusted and caps.get("sandbox") not in (True, "gvisor", "container"):
        return False, "job requires sandboxed worker"
    if job.required_os and str(caps.get("system", "")).lower() != job.required_os.lower():
        return False, "OS mismatch"
    if job.required_arch and str(caps.get("arch", "")).lower() != job.required_arch.lower():
        return False, "arch mismatch"
    if job.min_cpu > int(caps.get("cpu_cores", 0)):
        return False, f"needs {job.min_cpu} cores"
    if job.min_ram_mb > int(caps.get("ram_total_mb", 0) or 0):
        return False, f"needs {job.min_ram_mb} MB RAM"
    gpus = caps.get("gpu") or []
    gpu_mb = sum(int(g.get("memory_total_mb", 0)) for g in gpus if isinstance(g, dict))
    if job.required_gpu_mb > 0 and gpu_mb < job.required_gpu_mb:
        return False, f"needs {job.required_gpu_mb} MB GPU"
    have = set(caps.get("capabilities") or [])
    for cap in job.required_capabilities or []:
        if cap and cap not in have:
            return False, f"missing capability {cap}"
    return True, "ok"


def pick_worker(strategy: str, candidates: list[Worker], job: Job) -> Worker:
    """Scheduling strategies. A job's RAM requirement must fit on a single worker."""
    if strategy == "least_loaded":
        return min(candidates, key=lambda w: (w.active_jobs, w.registered_at))
    if strategy == "capability":

        def cap_score(w: Worker) -> int:
            return len(
                set(w.capabilities.get("capabilities") or [])
                & set(job.required_capabilities or [])
            )

        return max(candidates, key=cap_score)
    if strategy == "priority":
        return candidates[0]
    if strategy == "data_locality":

        def local_score(w: Worker):
            cached = job.workspace_id in (w.capabilities.get("cached_workspaces") or [])
            return (0 if cached else 1, w.registered_at)

        return min(candidates, key=local_score)
    if strategy == "cost_aware":

        def cost(w: Worker) -> float:
            try:
                return float((w.capabilities or {}).get("cost_per_hour", 0.0))
            except (TypeError, ValueError):
                return 0.0

        return min(candidates, key=cost)
    # best_fit (default): smallest sufficient RAM, then most available RAM
    def fit(w: Worker) -> tuple[int, int]:
        caps = w.capabilities or {}
        total = int(caps.get("ram_total_mb", 0) or 0)
        avail = int(caps.get("ram_available_mb", 0) or 0)
        return (total, -avail)

    return min(candidates, key=fit)


async def tick(
    session: AsyncSession,
    *,
    offline_after_seconds: int | None = None,
    strategy: str = "best_fit",
    now=None,
) -> dict:
    """One scheduler pass: worker expiry, timeouts, retries, dispatch."""
    from .config import settings

    now = now or utcnow()
    offline_after = offline_after_seconds or settings.worker_offline_after_seconds
    counts = {
        "workers_offlined": 0,
        "requeued_on_worker_loss": 0,
        "requeued_on_timeout": 0,
        "retried": 0,
        "dispatched": 0,
    }

    # 1. Offline stale workers; requeue their in-flight jobs
    cutoff_ts = now.timestamp() - offline_after
    workers = (await session.execute(select(Worker))).scalars().all()
    for w in workers:
        if w.health in (WorkerHealth.online, WorkerHealth.busy, WorkerHealth.degraded):
            hb = w.last_heartbeat
            if hb is None or hb.timestamp() < cutoff_ts:
                w.health = WorkerHealth.offline
                counts["workers_offlined"] += 1
                in_flight = (
                    (await session.execute(
                        select(Job).where(Job.worker_id == w.id, Job.state.in_(_ASSIGNED_STATES))
                    ))
                    .scalars()
                    .all()
                )
                for job in in_flight:
                    job.worker_id = None
                    job.cancel_requested = False
                    job.attempt += 1
                    if job.attempt <= job.max_retries + 1:
                        transition(session, job, JobState.RETRYING, f"worker {w.name} lost")
                        transition(session, job, JobState.QUEUED, "requeued after worker loss")
                        counts["requeued_on_worker_loss"] += 1
                    else:
                        job.finished_at = now
                        job.error = "worker lost and retries exhausted"
                        transition(session, job, JobState.FAILED, job.error)
                w.active_jobs = 0

    # 2. Timeout enforcement (RUNNING and CANCELLING)
    in_flight = (
        (
            await session.execute(
                select(Job).where(Job.state.in_([JobState.RUNNING, JobState.CANCELLING]))
            )
        )
        .scalars()
        .all()
    )
    for job in in_flight:
        started = job.started_at
        if started is not None and started.timestamp() + job.timeout_s < now.timestamp():
            job.finished_at = now
            job.error = f"timeout after {job.timeout_s}s"
            transition(session, job, JobState.FAILED, job.error)
            if job.worker_id:
                worker = await session.get(Worker, job.worker_id)
                if worker is not None:
                    worker.active_jobs = max(0, worker.active_jobs - 1)
                    if (
                        worker.health == WorkerHealth.busy
                        and worker.active_jobs < worker.max_active_jobs
                    ):
                        worker.health = WorkerHealth.online
            counts["requeued_on_timeout"] += 1

    # 3. Retry pass: RETRYING -> QUEUED
    retrying = (
        (await session.execute(select(Job).where(Job.state == JobState.RETRYING))).scalars().all()
    )
    for job in retrying:
        transition(session, job, JobState.QUEUED, "retry scheduled")
        counts["retried"] += 1

    # 4. Dispatch QUEUED jobs (priority asc, creation asc)
    queued = (
        (
            await session.execute(
                select(Job)
                .where(Job.state == JobState.QUEUED)
                .order_by(Job.priority.asc(), Job.created_at.asc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    for job in queued:
        candidates = [w for w in workers if worker_compatible(w, job)[0]]
        if not candidates:
            continue
        worker = pick_worker(strategy, candidates, job)
        transition(session, job, JobState.ASSIGNED, f"dispatched to {worker.name}")
        job.worker_id = worker.id
        worker.active_jobs += 1
        if worker.active_jobs >= worker.max_active_jobs:
            worker.health = WorkerHealth.busy
        counts["dispatched"] += 1

    return counts


async def claim_job(session: AsyncSession, worker: Worker) -> Job | None:
    """Worker claims its next ASSIGNED job -> RUNNING."""
    stmt = (
        select(Job)
        .where(Job.worker_id == worker.id, Job.state == JobState.ASSIGNED)
        .order_by(Job.priority.asc(), Job.created_at.asc())
        .limit(1)
    )
    job = (await session.execute(stmt)).scalar_one_or_none()
    if job is None:
        return None
    transition(session, job, JobState.RUNNING, f"claimed by {worker.name}")
    job.started_at = utcnow()
    return job


async def report_result(
    session: AsyncSession,
    job: Job,
    *,
    success: bool,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    now = utcnow()
    if job.cancel_requested and not success:
        job.finished_at = now
        transition(session, job, JobState.CANCELLED, "worker confirmed cancellation")
    elif success:
        job.result = result or {}
        job.error = None
        job.finished_at = now
        transition(session, job, JobState.SUCCEEDED)
    else:
        job.error = (error or "worker reported failure")[:8000]
        job.finished_at = now
        job.attempt += 1
        if job.attempt > job.max_retries + 1:
            transition(session, job, JobState.FAILED, "retries exhausted")
        else:
            job.worker_id = None
            job.cancel_requested = False
            transition(session, job, JobState.RETRYING, "retrying after failure")
    if job.worker_id:
        worker = await session.get(Worker, job.worker_id)
        if worker is not None:
            worker.active_jobs = max(0, worker.active_jobs - 1)
            if worker.health == WorkerHealth.busy and worker.active_jobs < worker.max_active_jobs:
                worker.health = WorkerHealth.online
