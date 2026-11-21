"""Worker agent unit tests: capabilities, executor limits, command parsing."""

from __future__ import annotations

import sys

import pytest
from omnimcp_worker.agent import parse_command
from omnimcp_worker.capabilities import detect
from omnimcp_worker.executor import Executor

HINTS_NONE = {"python": "python3", "node": None, "shell": None}


def test_detect_reports_machine_capabilities():
    caps = detect()
    assert caps["system"] in ("Linux", "Darwin", "Windows")
    assert caps["arch"]
    assert caps["cpu_cores"] >= 1
    assert caps["ram_total_mb"] > 0
    assert isinstance(caps["gpu"], list)
    assert "runtime:python" in caps["capabilities"]
    assert caps["runtimes"]["python"]


def test_parse_command_python():
    argv = parse_command({"command": {"runtime": "python", "script": "print(1)"}}, HINTS_NONE)
    assert argv == ["python3", "-c", "print(1)"]


def test_parse_command_argv_list():
    argv = parse_command({"command": {"argv": ["echo", "hi"]}}, HINTS_NONE)
    assert argv == ["echo", "hi"]


def test_parse_command_without_shell_runtime():
    assert parse_command({"command": "echo hi"}, HINTS_NONE) is None
    assert parse_command({"command": {"runtime": "shell", "script": "ls"}}, HINTS_NONE) is None


def test_parse_command_node_unavailable():
    assert parse_command({"command": {"runtime": "node", "script": "1+1"}}, HINTS_NONE) is None


@pytest.mark.asyncio
async def test_executor_runs_and_captures():
    ex = Executor(ram_mb=512)
    result = await ex.run([sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)"])
    assert result.exit_code == 0
    assert result.stdout_lines == ["out"]
    assert result.stderr_lines == ["err"]


@pytest.mark.asyncio
async def test_executor_timeout_kills():
    ex = Executor(ram_mb=512, cpu_seconds=10)
    result = await ex.run(
        [sys.executable, "-c", "import time; time.sleep(30)"], timeout=1.0
    )
    assert result.timed_out is True
    assert result.exit_code != 0 or result.signal_name is not None
    assert result.duration_ms < 20000


@pytest.mark.asyncio
async def test_executor_memory_limit_blocks_alloc():
    ex = Executor(ram_mb=128)
    result = await ex.run(
        [sys.executable, "-c", "x = bytearray(512 * 1024 * 1024)"]
    )
    assert result.exit_code != 0  # MemoryError -> non-zero


@pytest.mark.asyncio
async def test_executor_missing_binary():
    ex = Executor(ram_mb=128)
    result = await ex.run(["definitely-not-a-real-binary-xyz"])
    assert result.exit_code == -1
    assert "spawn failed" in result.stderr_lines[0]


@pytest.mark.asyncio
async def test_executor_on_line_callback():
    lines = []
    ex = Executor(ram_mb=128)
    await ex.run(
        [sys.executable, "-c", "for i in range(3): print(i)"],
        on_line=lambda stream, line: lines.append((stream, line)),
    )
    assert lines == [("stdout", "0"), ("stdout", "1"), ("stdout", "2")]
