"""FastAPI application assembly and entrypoint."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from . import __version__
from .api import agents, audit, auth, connectors, jobs, storage, system
from .api import workers as workers_api
from .api import workspaces as workspaces_r
from .api.system import HTTP_LATENCY, HTTP_REQUESTS
from .config import settings
from .db import create_all, dispose_engine, get_session_factory, init_engine
from .errors import OmnicpError, omnicp_error_handler
from .logging_setup import setup_logging
from .mcp_auth import BearerAuthMiddleware
from .mcp_server import build_mcp_asgi_app

log = logging.getLogger("omnimcp.main")


async def bootstrap_admin() -> None:
    """Create the initial admin account from env when configured (idempotent)."""
    if not settings.bootstrap_admin_password:
        return
    from .models import Role, User
    from .security import hash_password

    factory = get_session_factory()
    async with factory() as session:
        existing = (
            await session.execute(
                select(func.count())
                .select_from(User)
                .where(User.email == settings.bootstrap_admin_email)
            )
        ).scalar_one()
        if existing:
            return
        session.add(
            User(
                email=settings.bootstrap_admin_email,
                password_hash=hash_password(settings.bootstrap_admin_password),
                role=Role.admin,
            )
        )
        await session.commit()
        log.info("bootstrap admin created for %s", settings.bootstrap_admin_email)


async def scheduler_loop() -> None:
    from .jobs import tick

    factory = get_session_factory()
    while True:
        try:
            await asyncio.sleep(settings.scheduler_interval_seconds)
            async with factory() as session:
                counts = await tick(session)
                if any(counts.values()):
                    await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("scheduler tick failed")
            await asyncio.sleep(1.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings.log_level)
    log.info("omnimcp %s starting; env=%s", __version__, settings.env)
    if settings.env == "production" and not settings.secret_key:
        raise RuntimeError("OMNIMCP_SECRET_KEY required in production")
    init_engine(settings.database_url)
    await create_all()
    await bootstrap_admin()
    task = asyncio.create_task(scheduler_loop()) if settings.scheduler_enabled else None
    app.state.scheduler_task = task
    inner_mcp = build_mcp_asgi_app()
    app.mount("/mcp", BearerAuthMiddleware(inner_mcp))
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(inner_mcp.router.lifespan_context(inner_mcp))
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            await dispose_engine()
    log.info("omnimcp stopped")


def make_app() -> FastAPI:
    app = FastAPI(title="OmniMCP Control Plane", version=__version__, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    app.add_exception_handler(OmnicpError, omnicp_error_handler)

    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):
        route = request.scope.get("route")
        path = route.path if route is not None else request.url.path
        with HTTP_LATENCY.labels(request.method, path).time():
            response = await call_next(request)
        HTTP_REQUESTS.labels(request.method, path, str(response.status_code)).inc()
        return response

    app.include_router(system.router)
    app.include_router(auth.router)
    app.include_router(agents.router)
    app.include_router(workers_api.router)
    app.include_router(jobs.router)
    app.include_router(workspaces_r.router)
    app.include_router(connectors.router)
    app.include_router(storage.router)
    app.include_router(audit.router)
    return app


app = make_app()


def run() -> None:
    import uvicorn

    uvicorn.run(
        "omnimcp.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        access_log=False,
    )


if __name__ == "__main__":
    run()
