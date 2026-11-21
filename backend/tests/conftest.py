"""Shared test configuration: isolated env, per-module DB, auth helpers, live server."""

from __future__ import annotations

import contextlib
import os
import socket
import tempfile
import threading
import time

_TMP = tempfile.mkdtemp(prefix="omnimcp-test-")
os.environ["OMNIMCP_DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP}/unused.db"
os.environ["OMNIMCP_SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["OMNIMCP_ENV"] = "development"
os.environ["OMNIMCP_SCHEDULER_ENABLED"] = "false"
os.environ["OMNIMCP_WORKSPACE_ROOT"] = f"{_TMP}/workspaces"
os.environ["OMNIMCP_STORAGE_ROOT"] = f"{_TMP}/storage"
os.environ["OMNIMCP_METRICS_ENABLED"] = "false"

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

TEST_DB = f"{_TMP}/test.db"


def _reset_db(path: str) -> None:
    for suffix in ("", "-wal", "-shm"):
        with contextlib.suppress(FileNotFoundError):
            os.unlink(path + suffix)


@pytest_asyncio.fixture
async def client(tmp_path):
    """ASGI test client with a fresh DB per test."""
    import gc

    from omnimcp import security as _sec

    _sec._SYSTEM_FAILURES.clear()
    _reset_db(TEST_DB)
    from omnimcp.db import create_all, dispose_engine, init_engine
    from omnimcp.main import app

    init_engine(f"sqlite+aiosqlite:///{TEST_DB}")
    await create_all()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c
    await dispose_engine()
    gc.collect()


async def register_and_login(
    client: httpx.AsyncClient, email: str = "admin@example.com", password: str = "S3cure-passw0rd!"
) -> str:
    """Register (first user becomes admin) and return bearer token."""
    r = await client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert r.status_code in (201, 409), r.text
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class LiveServer:
    """Real uvicorn server in a thread (lifespan fully runs, incl. MCP mount)."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.port = free_port()
        self._thread: threading.Thread | None = None
        self._server = None

    def start(self) -> LiveServer:
        os.environ["OMNIMCP_DATABASE_URL"] = f"sqlite+aiosqlite:///{self.db_path}"
        import omnimcp.config as cfg
        from omnimcp.db import reset_engine
        from omnimcp.main import make_app

        cfg.settings.database_url = f"sqlite+aiosqlite:///{self.db_path}"
        cfg.settings.scheduler_enabled = True
        cfg.settings.scheduler_interval_seconds = 0.2
        cfg.settings.worker_offline_after_seconds = 2
        reset_engine()
        from omnimcp.mcp_server import reset_mcp_session_manager

        reset_mcp_session_manager()
        self._app = make_app()
        import uvicorn

        config = uvicorn.Config(self._app, host="127.0.0.1", port=self.port, log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        self._wait_ready()
        return self

    def _wait_ready(self, timeout: float = 30.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                r = httpx.get(f"{self.url}/healthz", timeout=2)
                if r.status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.2)
        raise RuntimeError("live server did not become ready")

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
            if self._thread is not None:
                self._thread.join(timeout=15)
        import omnimcp.config as cfg

        cfg.settings.scheduler_enabled = False
        cfg.settings.scheduler_interval_seconds = 1.0
        cfg.settings.worker_offline_after_seconds = 45
        _reset_db(self.db_path)


@pytest.fixture
def live_server():
    import gc

    _reset_db(TEST_DB)
    svc = LiveServer(TEST_DB).start()
    yield svc
    svc.stop()
    gc.collect()
