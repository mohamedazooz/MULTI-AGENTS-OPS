"""Worker agent loop: registration, heartbeat, claim, execute, report, reconnect.

Lifecycle:
    register -> (heartbeat loop) + (claim loop)
    claim -> execute payload in Executor -> report status -> repeat
Failure handling: exponential backoff on network errors; SIGTERM/SIGINT drain.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import time

import httpx

from . import __version__
from .capabilities import detect
from .executor import Executor

log = logging.getLogger("omnimcp.worker")


def parse_command(payload: dict, runtime_hints: dict) -> list[str] | None:
    """Build an argv from a job payload. Only structured command shapes translate
    to argv (never a raw agent-controlled shell string unless trusted)."""
    cmd = payload.get("command")
    if isinstance(cmd, dict):
        rtype = cmd.get("runtime", "python")
        script = cmd.get("script") or cmd.get("args")
        if rtype == "python" and isinstance(script, str):
            return [runtime_hints.get("python", "python3"), "-c", script]
        if rtype in ("node", "javascript") and isinstance(script, str):
            node = runtime_hints.get("node")
            if not node:
                return None
            return [node, "-e", script]
        if rtype == "shell" and isinstance(script, str):
            shell = runtime_hints.get("shell")
            if not shell:
                return None
            return [shell, "-lc", script]
        argv = cmd.get("argv")
        if isinstance(argv, list) and all(isinstance(a, str) for a in argv):
            return argv
        return None
    if isinstance(cmd, list) and all(isinstance(a, str) for a in cmd):
        return cmd
    if isinstance(cmd, str):
        shell = runtime_hints.get("shell")
        if not shell:
            return None
        return [shell, "-lc", cmd]
    return None


class WorkerAgent:
    def __init__(
        self,
        server_url: str,
        token: str,
        *,
        name: str = "worker",
        poll_interval: float = 2.0,
        heartbeat_interval: float = 10.0,
        max_ram_mb: int = 2048,
        request_timeout: float = 30.0,
        allow_shell: bool = False,
    ):
        self.server_url = server_url.rstrip("/")
        self.token = token
        self.name = name
        self.poll_interval = poll_interval
        self.heartbeat_interval = heartbeat_interval
        self.max_ram_mb = max_ram_mb
        self.request_timeout = request_timeout
        self.allow_shell = allow_shell
        self.executor = Executor(ram_mb=max_ram_mb)
        self.version = __version__
        self._stop = asyncio.Event()

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    async def stop(self) -> None:
        self._stop.set()
        self.executor.cancel()

    async def run(self) -> None:
        loops = [
            asyncio.create_task(self._heartbeat_loop()),
            asyncio.create_task(self._claim_loop()),
        ]
        try:
            await asyncio.gather(*loops, return_exceptions=True)
        finally:
            for t in loops:
                t.cancel()

    def _runtime_hints(self) -> dict:
        caps = detect()
        runtimes = caps.get("runtimes", {})
        return {
            "python": "python3",
            "node": "node" if runtimes.get("node") else None,
            "shell": "bash" if self.allow_shell else None,
        }

    async def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.server_url,
            headers=self.headers,
            timeout=self.request_timeout,
        )

    async def _heartbeat_loop(self) -> None:
        backoff = 1.0
        async with await self._client() as client:
            while not self._stop.is_set():
                caps = detect()
                try:
                    r = await client.post(
                        "/api/v1/workers/me/heartbeat",
                        json={
                            "capabilities": caps,
                            "version": self.version,
                            "active_jobs": 1 if self.executor._current else 0,
                            "ram_available_mb": caps["ram_available_mb"],
                        },
                    )
                    r.raise_for_status()
                    backoff = 1.0
                except httpx.HTTPError as e:
                    log.warning("heartbeat failed: %s; retrying in %.1fs", e, backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60)
                    continue
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=self.heartbeat_interval)

    async def _claim_loop(self) -> None:
        backoff = 1.0
        async with await self._client() as client:
            while not self._stop.is_set():
                try:
                    r = await client.post("/api/v1/workers/me/claim")
                    if r.status_code in (401, 403):
                        log.error("worker token rejected (%s); stopping", r.status_code)
                        return
                    r.raise_for_status()
                    backoff = 1.0
                except httpx.HTTPError as e:
                    log.warning("claim failed: %s; retrying in %.1fs", e, backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60)
                    continue
                data = r.json()
                if data.get("job_id"):
                    await self._execute_job(client, data)
                else:
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(self._stop.wait(), timeout=self.poll_interval)

    async def _execute_job(self, client: httpx.AsyncClient, job: dict) -> None:
        job_id = job["job_id"]
        payload = job.get("payload") or {}
        timeout = float(job.get("timeout_s") or 3600)
        log.info("executing job %s", job_id[:8])

        line_buffer: list[dict] = []

        async def flusher():
            while True:
                await asyncio.sleep(1.0)
                await self._flush_lines(client, job_id, line_buffer)

        flush_task = asyncio.create_task(flusher())

        async def cancel_watcher():
            while True:
                await asyncio.sleep(1.5)
                try:
                    r = await client.post(f"/api/v1/workers/me/jobs/{job_id}/cancel-check")
                    if r.status_code == 200 and r.json().get("cancel_requested"):
                        log.info("cancel requested for job %s", job_id[:8])
                        self.executor.cancel()
                        return
                except httpx.HTTPError:
                    continue

        def on_line(stream: str, line: str) -> None:
            line_buffer.append({"stream": stream, "line": line})

        watcher_task = asyncio.create_task(cancel_watcher())
        try:
            argv = parse_command(payload, self._runtime_hints())
            if argv is None:
                await self._report(client, job_id, success=False, error="unparseable command")
                return
            result = await self.executor.run(argv, timeout=timeout, on_line=on_line)
            success = result.exit_code == 0 and not result.timed_out
            await self._flush_lines(client, job_id, line_buffer)
            await self._report(
                client,
                job_id,
                success=success,
                result={
                    "exit_code": result.exit_code,
                    "signal": result.signal_name,
                    "timed_out": result.timed_out,
                    "duration_ms": result.duration_ms,
                },
                error=None if success else f"exit={result.exit_code} timed_out={result.timed_out}",
            )
        finally:
            flush_task.cancel()
            watcher_task.cancel()

    async def _flush_lines(self, client, job_id: str, buffer: list[dict]) -> None:
        if buffer:
            with contextlib.suppress(httpx.HTTPError):
                await client.post(f"/api/v1/workers/me/jobs/{job_id}/logs", json=buffer)
            buffer.clear()

    async def _report(self, client, job_id: str, *, success: bool, result=None, error=None) -> None:
        try:
            r = await client.post(
                f"/api/v1/workers/me/jobs/{job_id}/status",
                json={"success": success, "result": result or {}, "error": error},
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            log.error("failed to report job %s: %s", job_id[:8], e)


async def register_worker(
    server_url: str,
    user_token: str,
    name: str,
    *,
    max_active_jobs: int = 1,
    trust_level: str = "untrusted",
    request_timeout: float = 30.0,
) -> dict:
    """One-time registration: needs a user token, returns the long-lived worker token."""
    caps = detect()
    async with httpx.AsyncClient(
        base_url=server_url.rstrip("/"),
        headers={"Authorization": f"Bearer {user_token}"},
        timeout=request_timeout,
    ) as client:
        r = await client.post(
            "/api/v1/workers/register",
            json={
                "name": name,
                "version": __version__,
                "capabilities": caps,
                "max_active_jobs": max_active_jobs,
                "trust_level": trust_level,
            },
        )
        if r.status_code >= 400:
            return {"error": f"registration failed: HTTP {r.status_code}: {r.text[:300]}"}
        return r.json()


async def connectivity_latency(server_url: str, request_timeout: float = 5.0) -> float | None:
    """Seconds to reach the control plane /healthz, or None when unreachable."""
    try:
        async with httpx.AsyncClient(timeout=request_timeout) as client:
            start = time.monotonic()
            r = await client.get(server_url.rstrip("/") + "/healthz")
            if r.status_code == 200:
                return time.monotonic() - start
    except httpx.HTTPError:
        return None
    return None


_shutdown_tasks: set[asyncio.Task] = set()


def install_signal_handlers(loop: asyncio.AbstractEventLoop, agent: WorkerAgent) -> None:
    def _stop(*_a) -> None:
        _shutdown_tasks.add(asyncio.ensure_future(agent.stop()))

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:  # pragma: no cover (Windows)
            signal.signal(sig, _stop)
