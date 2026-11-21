"""Workspace & filesystem service with strict path containment and archive hardening.

Security controls (see THREAT_MODEL.md):
- all paths resolved and required to stay inside the workspace root
- archive extraction enforces: entry count, per-entry uncompressed size,
  total uncompressed size, absolute/.. path rejection, symlink/hardlink rejection
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

from .config import settings
from .errors import ValidationFailed

MAX_TEXT_READ_BYTES = 2 * 1024 * 1024

IGNORED_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".tox"}


def workspace_root() -> Path:
    root = Path(settings.workspace_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_workspace_dir(workspace_name: str) -> Path:
    """Resolve the on-disk directory for a workspace, refusing traversal."""
    if not workspace_name or any(ch in workspace_name for ch in "/\\") or ".." in workspace_name:
        raise ValidationFailed("invalid workspace name")
    root = workspace_root()
    p = (root / workspace_name).resolve()
    if root not in p.parents:
        raise ValidationFailed("workspace path escapes root")
    return p


def safe_join(workspace_dir: Path, rel_path: str) -> Path:
    """Join a relative path inside a workspace with containment checks."""
    if rel_path in ("", "."):
        return workspace_dir
    candidate = Path(rel_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValidationFailed("path traversal rejected")
    resolved = (workspace_dir / candidate).resolve()
    if resolved != workspace_dir and workspace_dir not in resolved.parents:
        raise ValidationFailed("path escapes workspace")
    return resolved


def list_tree(ws_dir: Path, max_entries: int = 5000) -> list[dict]:
    entries: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(ws_dir):
        dirnames[:] = [d for d in sorted(dirnames) if d not in IGNORED_DIRS]
        reldir = os.path.relpath(dirpath, ws_dir)
        for name in sorted(filenames):
            p = Path(dirpath) / name
            rel = name if reldir == "." else f"{reldir}/{name}"
            try:
                size = p.stat().st_size
            except OSError:
                size = 0
            entries.append({"path": rel, "size": size})
            if len(entries) >= max_entries:
                return entries
    return entries


def detect_project_type(ws_dir: Path) -> str:
    markers = [
        ("pyproject.toml", "python"),
        ("requirements.txt", "python"),
        ("setup.py", "python"),
        ("package.json", "node"),
        ("Cargo.toml", "rust"),
        ("go.mod", "go"),
        ("Dockerfile", "docker"),
    ]
    for marker, ptype in markers:
        if (ws_dir / marker).exists():
            return ptype
    return "unknown"


# ---------------------------------------------------------------------------
# Archive extraction (zip, tar, tar.gz) — hardened against Zip Slip / tar bombs
# ---------------------------------------------------------------------------


def _check_entry_name(name: str) -> None:
    p = Path(name)
    if name.startswith("/") or name.startswith("\\") or p.is_absolute():
        raise ValidationFailed(f"absolute path in archive: {name!r}")
    if ".." in p.parts or "\\" in name:
        raise ValidationFailed(f"path traversal in archive: {name!r}")
    first = name.split(":")[0]
    if ":" in name and len(first) <= 2 and first.isalpha():  # windows drive prefix (C:\)
        raise ValidationFailed(f"windows absolute path in archive: {name!r}")


def _copy_stream(src, target: Path, max_entry: int) -> int:
    """Copy one archive member with per-entry byte enforcement."""
    written = 0
    with open(target, "wb") as out:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > max_entry:
                raise ValidationFailed(f"entry exceeded size limit while writing: {target.name}")
            out.write(chunk)
    return 1


def extract_archive(archive_path: Path, dest_dir: Path) -> dict:
    """Extract zip/tar/tar.gz with traversal, bomb and link protections."""
    dest_dir = dest_dir.resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    max_entry = settings.max_archive_entry_bytes
    max_entries = settings.max_archive_entries
    max_total = settings.max_workspace_bytes
    total_probe = 0
    count = 0

    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path) as zf:
            infos = zf.infolist()
            if len(infos) > max_entries:
                raise ValidationFailed(f"too many entries ({len(infos)})")
            for info in infos:
                _check_entry_name(info.filename)
                if info.file_size > max_entry:
                    raise ValidationFailed(f"entry too large: {info.filename}")
                total_probe += info.file_size
                if total_probe > max_total:
                    raise ValidationFailed("archive bomb: declared total exceeds limit")
                mode = info.external_attr >> 16
                if mode and (mode & 0o170000) == 0o120000:
                    raise ValidationFailed(f"symlink in archive: {info.filename}")
            for info in infos:
                if info.filename.endswith("/"):
                    continue
                target = safe_join(dest_dir, info.filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                count += _copy_stream(zf.open(info), target, max_entry)
        return {"files": count, "bytes": total_probe, "format": "zip"}

    try:
        with tarfile.open(archive_path, "r:*") as tf:
            members = tf.getmembers()
            if len(members) > max_entries:
                raise ValidationFailed(f"too many entries ({len(members)})")
            for m in members:
                if m.isdir():
                    _check_entry_name(m.name)
                    continue
                if m.issym() or m.islnk():
                    raise ValidationFailed(f"link member in archive: {m.name}")
                if not m.isfile():
                    raise ValidationFailed(f"non-regular member: {m.name}")
                _check_entry_name(m.name)
                if m.size > max_entry:
                    raise ValidationFailed(f"entry too large: {m.name}")
                total_probe += m.size
                if total_probe > max_total:
                    raise ValidationFailed("archive bomb: declared total exceeds limit")
            for m in members:
                if m.isdir():
                    safe_join(dest_dir, m.name).mkdir(parents=True, exist_ok=True)
                    continue
                if not m.isfile():
                    continue
                fsrc = tf.extractfile(m)
                if fsrc is None:
                    continue
                target = safe_join(dest_dir, m.name)
                target.parent.mkdir(parents=True, exist_ok=True)
                count += _copy_stream(fsrc, target, max_entry)
        return {"files": count, "bytes": total_probe, "format": "tar"}
    except tarfile.ReadError as e:
        raise ValidationFailed(f"unrecognized archive format: {e}") from e


def git_clone(dest_dir: Path, repo_url: str, branch: str | None = None) -> dict:
    url = repo_url.strip()
    if not url.startswith(("https://", "git@")):
        raise ValidationFailed("only https:// or git@ repository URLs are allowed")
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / ".clone_tmp"
    if target.exists():
        shutil.rmtree(target)
    cmd = ["git", "clone", "--depth", "1", url, str(target)]
    if branch:
        cmd = ["git", "clone", "--depth", "1", "--branch", branch, url, str(target)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise ValidationFailed(f"git clone failed: {proc.stderr.strip()[:500]}")
    for item in target.iterdir():
        os.replace(item, dest_dir / item.name)
    shutil.rmtree(target, ignore_errors=True)
    head = subprocess.run(
        ["git", "-C", str(dest_dir), "rev-parse", "HEAD"], capture_output=True, text=True
    )
    return {"cloned": True, "commit": head.stdout.strip()[:40]}
