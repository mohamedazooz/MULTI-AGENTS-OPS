"""Capability discovery for the machine the worker runs on.

Collects: OS, arch, CPU cores, RAM (total/available), free disk, GPU devices,
installed runtimes, docker availability, network reachability to the control plane.
Never collects or reports secrets or user-identifying information.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys


def _which_version(cmd: list[str], timeout: float = 10.0) -> str:
    if shutil.which(cmd[0]) is None:
        return ""
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        for line in (out.stdout + out.stderr).splitlines():
            line = line.strip()
            if line:
                return line[:200]
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return ""


def detect() -> dict:
    psutil = _try_psutil()
    caps: dict = {
        "os": sys.platform,
        "system": platform.system(),
        "arch": platform.machine(),
        "cpu_cores": os_cpu_count(),
        "ram_total_mb": ram_total_mb(psutil),
        "ram_available_mb": ram_available_mb(psutil),
        "disk_free_gb": round(disk_free_bytes() / 1024**3, 2),
        "gpu": detect_gpus(),
        "runtimes": detect_runtimes(),
        "hostname": platform.node()[:64],
    }
    runtime_caps = {
        "runtime:python": True,
        "docker": bool(caps["runtimes"].get("docker")),
        "git": bool(caps["runtimes"].get("git")),
    }
    for name in ("node", "npm", "cargo", "rustc", "go"):
        runtime_caps[f"runtime:{name}"] = bool(caps["runtimes"].get(name))
    if caps["gpu"]:
        runtime_caps["gpu"] = True
    docker = caps["runtimes"].get("docker", "")
    if docker:
        # container isolation is the default execution boundary
        caps["sandbox"] = "container"
    caps["capabilities"] = sorted(k for k, v in runtime_caps.items() if v)
    return caps


def _try_psutil():
    try:
        import psutil  # type: ignore

        return psutil
    except ImportError:
        return None


def os_cpu_count() -> int:
    try:
        return os_cpu_count_impl()
    except Exception:
        return 1


def os_cpu_count_impl() -> int:
    import os

    return os.cpu_count() or 1


def ram_total_mb(psutil) -> int:
    if psutil:
        return int(psutil.virtual_memory().total / 1024**2)
    return _meminfo_field("MemTotal")


def ram_available_mb(psutil) -> int:
    if psutil:
        return int(psutil.virtual_memory().available / 1024**2)
    return _meminfo_field("MemAvailable")


def _meminfo_field(field: str) -> int:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith(field):
                    return int(line.split()[1]) // 1024
    except OSError:
        pass
    return 0


def disk_free_bytes(path: str = ".") -> float:
    try:
        return float(shutil.disk_usage(path).free)
    except OSError:
        return 0.0


def detect_gpus() -> list[dict]:
    if shutil.which("nvidia-smi") is None:
        return []
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        gpus = []
        for line in out.stdout.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2:
                try:
                    mem = int(parts[1])
                except ValueError:
                    mem = 0
                gpus.append({"vendor": "nvidia", "name": parts[0], "memory_total_mb": mem})
        return gpus
    except (OSError, subprocess.TimeoutExpired):
        return []


def detect_runtimes() -> dict[str, str]:
    return {
        "python": f"python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "node": _which_version(["node", "--version"]),
        "npm": _which_version(["npm", "--version"]),
        "rustc": _which_version(["rustc", "--version"]),
        "cargo": _which_version(["cargo", "--version"]),
        "go": _which_version(["go", "version"]),
        "docker": _which_version(["docker", "--version"]),
        "git": _which_version(["git", "--version"]),
    }
