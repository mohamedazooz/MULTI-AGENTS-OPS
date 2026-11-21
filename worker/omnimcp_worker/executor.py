"""Executor: bounded subprocess execution with POSIX resource limits.

- RAM: RLIMIT_AS; CPU seconds: RLIMIT_CPU; process count: RLIMIT_NPROC
- runs in a dedicated process group; timeout/cancel kill the whole group
- logs stream through a callback for live reporting
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import resource
import signal
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field

MAX_LOG_LINE = 8000
MAX_LOG_LINES_PER_STREAM = 20000


@dataclass
class ExecResult:
    exit_code: int | None = None
    signal_name: str | None = None
    timed_out: bool = False
    cancelled: bool = False
    duration_ms: int = 0
    stdout_lines: list[str] = field(default_factory=list)
    stderr_lines: list[str] = field(default_factory=list)


def _preexec(ram_mb: int, cpu_seconds: int, max_processes: int, low_priority: bool):
    def _apply():  # pragma: no cover - runs in child process
        gb = ram_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (gb, gb))
        if cpu_seconds > 0:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 30))
        with contextlib.suppress(ValueError, OSError):
            resource.setrlimit(resource.RLIMIT_NPROC, (max_processes, max_processes))
        if low_priority:
            with contextlib.suppress(Exception):
                os.nice(10)
        os.setsid()

    return _apply


class Executor:
    def __init__(
        self,
        *,
        ram_mb: int = 2048,
        cpu_seconds: int = 3600,
        max_processes: int = 512,
        low_priority: bool = True,
    ):
        self.ram_mb = ram_mb
        self.cpu_seconds = cpu_seconds
        self.max_processes = max_processes
        self.low_priority = low_priority
        self._current: asyncio.subprocess.Process | None = None
        self._cancelled = asyncio.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    async def run(
        self,
        argv: list[str],
        *,
        cwd: str | None = None,
        env_extra: dict | None = None,
        timeout: float = 3600,
        on_line: Callable[[str, str], None] | None = None,
    ) -> ExecResult:
        if self._current is not None:
            raise RuntimeError("executor is busy")
        result = ExecResult()
        env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": cwd or ".", "TERM": "dumb"}
        if cwd:
            env["PWD"] = cwd
        env.update(env_extra or {})

        preexec = None
        start_new_session = True
        if sys.platform != "win32":
            preexec = _preexec(
                self.ram_mb, self.cpu_seconds, self.max_processes, self.low_priority
            )
            start_new_session = False

        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=cwd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=preexec,
                start_new_session=start_new_session,
            )
        except (FileNotFoundError, PermissionError, NotADirectoryError) as e:
            result.exit_code = -1
            result.stderr_lines.append(f"spawn failed: {e}")
            return result
        self._current = proc
        pgid = proc.pid

        async def pump(stream, name: str, sink: list[str]):
            counter = 0
            while True:
                raw = await stream.readline()
                if not raw:
                    break
                counter += 1
                if counter <= MAX_LOG_LINES_PER_STREAM:
                    line = raw.decode(errors="replace").rstrip()[:MAX_LOG_LINE]
                    sink.append(line)
                    if on_line is not None:
                        on_line(name, line)

        out_task = asyncio.ensure_future(pump(proc.stdout, "stdout", result.stdout_lines))
        err_task = asyncio.ensure_future(pump(proc.stderr, "stderr", result.stderr_lines))
        cancel_watch = asyncio.ensure_future(self._cancelled.wait())
        wait_task = asyncio.ensure_future(proc.wait())

        try:
            done, _pending = await asyncio.wait(
                {wait_task, cancel_watch}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            result.timed_out = wait_task not in done
            result.cancelled = cancel_watch in done
            if proc.returncode is None:
                await self._signal_group(pgid, signal.SIGTERM)
                try:
                    await asyncio.wait_for(proc.wait(), timeout=10)
                except TimeoutError:
                    await self._signal_group(pgid, signal.SIGKILL)
                    await proc.wait()
        finally:
            for t in (out_task, err_task, cancel_watch):
                t.cancel()
            await asyncio.gather(out_task, err_task, return_exceptions=True)
            result.duration_ms = int((time.monotonic() - start) * 1000)
            result.exit_code = proc.returncode
            self._current = None
        if result.exit_code is not None and result.exit_code < 0:
            sig = -result.exit_code
            try:
                result.signal_name = signal.Signals(sig).name
            except ValueError:
                result.signal_name = str(sig)
        return result

    @staticmethod
    async def _signal_group(pgid: int, sig: signal.Signals) -> None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pgid, sig)
