"""MCP server: typed tools over the same domain services.

Mounted via Streamable HTTP at /mcp. Tool set deliberately excludes unrestricted
shell execution: any execution is bounded by workspace, worker, policy, resource limits.
"""

from __future__ import annotations

import shutil

from mcp.server.fastmcp import FastMCP

from . import __version__
from .db import get_session_factory
from .errors import OmnicpError
from .workspaces import MAX_TEXT_READ_BYTES, detect_project_type, git_clone, safe_join, safe_workspace_dir

mcp = FastMCP(
    "omnimcp",
    streamable_http_path="/",  # mounted at /mcp by main.make_app; avoid /mcp/mcp
    instructions=(
        "OmniMCP unified agent development & execution platform. "
        f"Server version {__version__}. Tools are scoped by workspace and auth token."
    ),
)


def _err(e: Exception) -> str:
    if isinstance(e, OmnicpError):
        return f"{e.code}: {e.message}"
    return f"internal_error: {type(e).__name__}: {e}"


@mcp.tool()
async def system_status() -> dict:
    """Control-plane health: version, queue depth, online workers."""
    from sqlalchemy import func, select

    from .models import Job, JobState, Worker, WorkerHealth

    factory = get_session_factory()
    async with factory() as session:
        queued = (
            await session.execute(
                select(func.count()).select_from(Job).where(Job.state == JobState.QUEUED)
            )
        ).scalar_one()
        running = (
            await session.execute(
                select(func.count()).select_from(Job).where(Job.state == JobState.RUNNING)
            )
        ).scalar_one()
        online = (
            await session.execute(
                select(func.count()).select_from(Worker).where(Worker.health == WorkerHealth.online)
            )
        ).scalar_one()
        return {
            "version": __version__,
            "queued": queued,
            "running": running,
            "workers_online": online,
        }


@mcp.tool()
async def workspace_create(name: str, description: str = "", repo_url: str = "", branch: str = "") -> dict:
    """Create a workspace, optionally cloning an https git repository into it."""
    target = None
    try:
        target = safe_workspace_dir(name)
        if target.exists():
            return {"error": "workspace_exists"}
        target.mkdir(parents=True, exist_ok=False)
        detail: dict = {}
        if repo_url:
            detail.update(git_clone(target, repo_url, branch or None))
        factory = get_session_factory()
        async with factory() as session:
            from .models import Workspace

            w = Workspace(name=name, description=description, project_type=detect_project_type(target))
            session.add(w)
            await session.commit()
            return {"id": w.id, "name": name, **detail}
    except Exception as e:
        if target is not None:
            shutil.rmtree(target, ignore_errors=True)
        return {"error": _err(e)}


@mcp.tool()
async def workspace_list() -> list[dict]:
    """List workspaces."""
    from sqlalchemy import select

    from .models import Workspace

    async with get_session_factory()() as session:
        rows = (
            (await session.execute(select(Workspace).order_by(Workspace.created_at)))
            .scalars()
            .all()
        )
        return [{"id": w.id, "name": w.name, "project_type": w.project_type} for w in rows]


@mcp.tool()
async def filesystem_read(workspace_name: str, path: str) -> str:
    """Read a UTF-8 text file from a workspace."""
    try:
        p = safe_join(safe_workspace_dir(workspace_name), path)
        if not p.is_file():
            return f"not_found: {path}"
        st = p.stat()
        if st.st_size > 8 * 1024 * 1024:
            return "too_large: use storage APIs"
        return p.read_text()[:MAX_TEXT_READ_BYTES]
    except Exception as e:
        return _err(e)


@mcp.tool()
async def filesystem_write(workspace_name: str, path: str, content: str) -> str:
    """Write a UTF-8 text file inside a workspace."""
    try:
        root = safe_workspace_dir(workspace_name)
        if not root.is_dir():
            return f"error: workspace_not_found: {workspace_name}"
        p = safe_join(root, path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"wrote {len(content)} bytes to {path}"
    except Exception as e:
        return _err(e)


@mcp.tool()
async def job_submit(
    kind: str,
    payload: dict,
    priority: int = 5,
    required_capabilities: list[str] | None = None,
    min_ram_mb: int = 256,
    min_cpu: int = 1,
    untrusted: bool = False,
    idempotency_key: str = "",
) -> dict:
    """Submit a job for scheduling (payload schema: docs/API_REFERENCE.md)."""
    from .jobs import enqueue

    try:
        async with get_session_factory()() as session:
            job, created = await enqueue(
                session,
                kind=kind,
                payload=payload,
                owner_id=None,
                idempotency_key=idempotency_key or None,
                required_capabilities=required_capabilities or [],
                min_ram_mb=min_ram_mb,
                min_cpu=min_cpu,
                untrusted=untrusted,
                priority=priority,
            )
            await session.commit()
            return {"job_id": job.id, "state": job.state.value, "created": created}
    except Exception as e:
        return {"error": _err(e)}


@mcp.tool()
async def job_status(job_id: str) -> dict:
    """Fetch job state, result and error."""
    from .models import Job

    try:
        async with get_session_factory()() as session:
            job = await session.get(Job, job_id)
            if job is None:
                return {"error": "not_found"}
            return {
                "job_id": job.id,
                "state": job.state.value,
                "worker_id": job.worker_id,
                "result": job.result,
                "error": job.error,
            }
    except Exception as e:
        return {"error": _err(e)}


@mcp.tool()
async def job_cancel(job_id: str) -> dict:
    """Request cancellation of a job."""
    from .jobs import request_cancel

    try:
        async with get_session_factory()() as session:
            job = await request_cancel(session, job_id, owner_id=None)
            await session.commit()
            return {"job_id": job.id, "state": job.state.value}
    except OmnicpError as e:
        return {"error": _err(e)}


@mcp.tool()
async def worker_list() -> list[dict]:
    """List registered workers with health and capability summary."""
    from sqlalchemy import select

    from .models import Worker

    async with get_session_factory()() as session:
        rows = (await session.execute(select(Worker))).scalars().all()
        return [
            {
                "id": w.id,
                "name": w.name,
                "health": w.health.value,
                "version": w.version,
                "system": (w.capabilities or {}).get("system"),
                "arch": (w.capabilities or {}).get("arch"),
                "cpu_cores": (w.capabilities or {}).get("cpu_cores"),
                "ram_total_mb": (w.capabilities or {}).get("ram_total_mb"),
                "active_jobs": w.active_jobs,
            }
            for w in rows
        ]


@mcp.tool()
async def worker_capabilities(worker_id: str) -> dict:
    """Full capability report for one worker."""
    from .models import Worker

    async with get_session_factory()() as session:
        w = await session.get(Worker, worker_id)
        if w is None:
            return {"error": "not_found"}
        return {
            "id": w.id,
            "name": w.name,
            "capabilities": w.capabilities or {},
            "limits": w.limits or {},
        }


@mcp.tool()
async def connector_list() -> list[dict]:
    """List registered MCP/API connectors with health."""
    from sqlalchemy import select

    from .models import Connector

    async with get_session_factory()() as session:
        rows = (await session.execute(select(Connector))).scalars().all()
        return [
            {
                "id": c.id,
                "name": c.name,
                "kind": c.kind.value,
                "enabled": c.enabled,
                "health": c.health,
            }
            for c in rows
        ]


@mcp.tool()
async def artifact_list(limit: int = 50) -> list[dict]:
    """List storage objects (artifacts) visible to the caller."""
    from sqlalchemy import select

    from .models import StorageObject

    async with get_session_factory()() as session:
        rows = (
            (
                await session.execute(
                    select(StorageObject)
                    .order_by(StorageObject.created_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": o.id,
                "filename": o.filename,
                "kind": o.kind,
                "size_bytes": o.size_bytes,
                "sha256": o.sha256,
                "provider": o.provider,
            }
            for o in rows
        ]


def build_mcp_asgi_app():
    """Return the Streamable-HTTP ASGI app (mounted at /mcp by main.make_app)."""
    return mcp.streamable_http_app()


def reset_mcp_session_manager() -> None:
    """Allow a fresh StreamableHTTPSessionManager per app instance (tests/dev reloads).

    The manager deliberately refuses .run() twice; tests and hot reloads build new
    apps against the same FastMCP instance.
    """
    mcp._session_manager = None
