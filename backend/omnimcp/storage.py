"""Storage Router: provider-independent object storage.

Adapters: local filesystem (implemented), GCS (adapter, requires credentials),
Hugging Face Hub (adapter, requires credentials). Selection policy documented in
docs/STORAGE_DESIGN.md. >10GB uploads must use direct client->provider resumable
sessions; the local provider streams to disk so the control plane never buffers
a full copy in memory.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from .config import settings
from .errors import NotConfigured, NotFound, ValidationFailed


def sanitize_filename(name: str) -> str:
    name = os.path.basename(name or "file").strip()
    if not name or not name.strip("."):
        raise ValidationFailed("invalid filename")
    if any(ch in name for ch in "/\\") or ".." in name:
        raise ValidationFailed("invalid filename")
    if len(name) > 255:
        stem, dot, ext = name.rpartition(".")
        name = ((stem[:180] if stem else name[:200]) + (dot + ext if dot else ""))[:255]
    return name


def sha256_stream(chunks: Iterator[bytes]) -> tuple[str, int]:
    h = hashlib.sha256()
    total = 0
    for chunk in chunks:
        h.update(chunk)
        total += len(chunk)
    return h.hexdigest(), total


class StorageProvider(ABC):
    name: str = "abstract"

    @abstractmethod
    def save_stream(self, object_path: str, stream: BinaryIO, *, chunk_hook=None) -> dict:
        """Persist a stream; returns {'size', 'sha256'}. chunk_hook(chunk: bytes)."""

    @abstractmethod
    def open_stream(self, object_path: str, start: int = 0) -> BinaryIO: ...

    @abstractmethod
    def stat(self, object_path: str) -> dict: ...

    @abstractmethod
    def delete(self, object_path: str) -> None: ...

    @abstractmethod
    def iter_objects(self) -> Iterator[str]: ...


class LocalStorageProvider(StorageProvider):
    name = "local"

    def __init__(self, root: Path | None = None):
        self.root = Path(root or settings.storage_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _full(self, object_path: str) -> Path:
        p = (Path(self.root) / object_path).resolve()
        if self.root not in p.parents and p != self.root:
            raise ValidationFailed("object path escapes storage root")
        return p

    def save_stream(self, object_path, stream, *, chunk_hook=None) -> dict:
        target = self._full(object_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        size = 0
        tmp = target.with_suffix(target.suffix + ".part")
        chunks = (
            iter(lambda: stream.read(1024 * 1024), b"")
            if hasattr(stream, "read")
            else stream
        )
        with open(tmp, "wb") as out:
            for chunk in chunks:
                if not chunk:
                    break
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise ValidationFailed("object exceeds max_upload_bytes")
                h.update(chunk)
                out.write(chunk)
                if chunk_hook:
                    chunk_hook(chunk)
            os.replace(tmp, target)
        return {"size": size, "sha256": h.hexdigest()}

    def open_stream(self, object_path: str, start: int = 0):
        p = self._full(object_path)
        if not p.is_file():
            raise NotFound(f"object not found: {object_path}")
        f = open(p, "rb")  # noqa: SIM115 - caller owns the stream lifecycle
        if start:
            f.seek(start)
        return f

    def stat(self, object_path: str) -> dict:
        p = self._full(object_path)
        if not p.is_file():
            raise NotFound(f"object not found: {object_path}")
        st = p.stat()
        return {"size": st.st_size, "mtime": st.st_mtime, "path": str(p.relative_to(self.root))}

    def delete(self, object_path: str) -> None:
        p = self._full(object_path)
        if p.is_file():
            p.unlink()

    def iter_objects(self):
        for dirpath, _dirnames, filenames in os.walk(self.root):
            for fn in filenames:
                yield str(Path(dirpath, fn).relative_to(self.root))


class GCSStorageProvider(StorageProvider):
    """Google Cloud Storage adapter. Not enabled until bucket + credentials exist."""

    name = "gcs"

    def __init__(self, bucket: str | None = None):
        self.bucket = bucket or os.environ.get("OMNIMCP_GCS_BUCKET", "")
        try:
            from google.cloud import storage  # type: ignore

            self._storage_mod = storage
        except ImportError as e:
            raise NotConfigured(
                "GCS provider requires 'pip install omnimcp-backend[gcs]' "
                "plus GOOGLE_APPLICATION_CREDENTIALS; switch off until configured"
            ) from e
        self._client = storage.Client()

    def _blob(self, object_path: str):
        return self._client.bucket(self.bucket).blob(object_path)

    def save_stream(self, object_path, stream, *, chunk_hook=None) -> dict:
        h = hashlib.sha256()
        size = 0
        blob = self._blob(object_path)
        chunks = (
            iter(lambda: stream.read(1024 * 1024), b"")
            if hasattr(stream, "read")
            else stream
        )
        with blob.open("wb") as out:
            for chunk in chunks:
                if not chunk:
                    break
                size += len(chunk)
                h.update(chunk)
                out.write(chunk)
                if chunk_hook:
                    chunk_hook(chunk)
        return {"size": size, "sha256": h.hexdigest()}

    def open_stream(self, object_path: str, start: int = 0):
        return self._blob(object_path).open("rb")

    def stat(self, object_path: str) -> dict:
        blob = self._client.bucket(self.bucket).get_blob(object_path)
        if blob is None:
            raise NotFound(f"gs://{self.bucket}/{object_path}")
        return {"size": blob.size, "mtime": blob.updated, "path": object_path}

    def delete(self, object_path: str) -> None:
        self._blob(object_path).delete()

    def iter_objects(self):
        for blob in self._client.list_blobs(self.bucket):
            yield blob.name


class HFStorageProvider(StorageProvider):
    """Hugging Face Hub adapter for model/dataset artifacts only (not general backup)."""

    name = "hf"

    def __init__(self, repo_id: str | None = None, repo_type: str = "model"):
        self.repo_id = repo_id or os.environ.get("OMNIMCP_HF_REPO", "")
        self.repo_type = repo_type
        if not self.repo_id:
            raise NotConfigured("HF provider requires OMNIMCP_HF_REPO (owner/repo)")
        try:
            import huggingface_hub

            self._hub = huggingface_hub
        except ImportError as e:
            raise NotConfigured(
                "HF provider requires 'pip install omnimcp-backend[hf]' and OMNIMCP_HF_TOKEN"
            ) from e

    def save_stream(self, object_path, stream, *, chunk_hook=None) -> dict:
        data = b"".join(
            stream
            if not hasattr(stream, "read")
            else iter(lambda: stream.read(1024 * 1024), b"")
        )
        path = self._hub.HfApi().upload_file(
            path_or_fileobj=data,
            path_in_repo=object_path,
            repo_id=self.repo_id,
            repo_type=self.repo_type,
        )
        return {"size": len(data), "sha256": "", "url": path}

    def open_stream(self, object_path: str, start: int = 0):
        local = self._hub.hf_hub_download(
            self.repo_id, object_path, repo_type=self.repo_type
        )
        f = open(local, "rb")  # noqa: SIM115 - caller owns the stream lifecycle
        if start:
            f.seek(start)
        return f

    def stat(self, object_path: str) -> dict:
        info = self._hub.HfApi().get_paths_info(
            self.repo_id, object_path, repo_type=self.repo_type
        )
        return {"size": info.size, "mtime": info.last_commit, "path": object_path}

    def delete(self, object_path: str) -> None:
        self._hub.HfApi().delete_file(object_path, self.repo_id, repo_type=self.repo_type)

    def iter_objects(self):
        yield from self._hub.HfApi().list_repo_files(self.repo_id, repo_type=self.repo_type)


_providers: dict[str, StorageProvider] | None = None


def reset_providers() -> None:
    global _providers
    _providers = None


def get_providers() -> dict[str, StorageProvider]:
    """Instantiate configured providers. Local always available; gcs/hf lazily."""
    global _providers
    if _providers is None:
        _providers = {"local": LocalStorageProvider()}
        for name, cls, env in (
            ("gcs", GCSStorageProvider, "OMNIMCP_GCS_BUCKET"),
            ("hf", HFStorageProvider, "OMNIMCP_HF_REPO"),
        ):
            if os.environ.get(env):
                with contextlib.suppress(NotConfigured):
                    _providers[name] = cls()
    return _providers


def choose_provider(obj_kind: str, size_hint: int = 0) -> StorageProvider:
    """Routing policy (docs/STORAGE_DESIGN.md):
    - model/dataset -> Hugging Face Hub when configured
    - backups/archives -> GCS when configured
    - everything else -> local filesystem
    """
    providers = get_providers()
    if obj_kind in ("model", "dataset") and "hf" in providers:
        return providers["hf"]
    if obj_kind in ("backup", "archive") and "gcs" in providers:
        return providers["gcs"]
    return providers["local"]


def direct_upload_session(provider: str, object_path: str, size_bytes: int) -> dict:
    """Large (>10 GB) uploads must bypass the control plane.

    - gcs: returns a resumable-session initiation URL for direct client->GCS upload
    - local: rejected; the local provider streams through the API instead
    """
    if provider == "gcs":
        providers = get_providers()
        if "gcs" not in providers:
            raise NotConfigured("GCS not configured")
        gcs = providers["gcs"]
        blob = gcs._client.bucket(gcs.bucket).blob(object_path)
        url = blob.create_resumable_upload_session(size=size_bytes)
        return {"mode": "direct", "provider": "gcs", "upload_url": url}
    raise NotConfigured(
        "direct-upload sessions require the GCS provider; local provider streams via the API"
    )
