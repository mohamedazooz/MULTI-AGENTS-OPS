"""Storage routes: upload (multipart + resumable sessions), stat, download, delete, list."""


import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import record
from ..config import settings
from ..db import get_session
from ..deps import current_user
from ..errors import Conflict, NotFound, ValidationFailed
from ..models import StorageObject, UploadSession, User, new_id
from ..schemas import StorageObjectOut, UploadSessionCreate
from ..storage import (
    choose_provider,
    direct_upload_session,
    get_providers,
    sanitize_filename,
    sha256_stream,
)

router = APIRouter(prefix="/api/v1/storage", tags=["storage"])


def _out(o: StorageObject) -> StorageObjectOut:
    return StorageObjectOut(
        id=o.id,
        filename=o.filename,
        provider=o.provider,
        bucket_or_repository=o.bucket_or_repository,
        object_path=o.object_path,
        size_bytes=o.size_bytes,
        sha256=o.sha256,
        content_type=o.content_type,
        workspace_id=o.workspace_id,
        owner_id=o.owner_id,
        kind=o.kind,
        retention=o.retention,
        version=o.version,
        created_at=o.created_at,
    )


def _own(user: User, owner_id: str | None) -> bool:
    return user.role.value == "admin" or owner_id == user.id


@router.post("/upload", response_model=StorageObjectOut, status_code=201)
async def upload(
    file: UploadFile = File(...),
    kind: str = Form("artifact"),
    workspace_id: str | None = Form(None),
    retention: str = Form("default"),
    expected_sha256: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    """Single-request streaming upload using 1 MB chunks (no full RAM buffering)."""
    filename = sanitize_filename(file.filename or "file")
    if kind not in {"artifact", "model", "dataset", "backup", "archive", "log"}:
        raise ValidationFailed("unsupported object kind")
    provider = choose_provider(kind)
    object_path = f"{user.id}/{kind}/{filename}"

    def gen():
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            yield chunk

    result = provider.save_stream(object_path, gen())
    sha256 = result["sha256"]
    if expected_sha256 and sha256 != expected_sha256.lower():
        provider.delete(object_path)
        raise ValidationFailed("sha256 mismatch: upload rejected and deleted")
    obj = StorageObject(
        id=new_id(),
        filename=filename,
        provider=provider.name,
        bucket_or_repository=getattr(provider, "bucket", "") or getattr(provider, "repo_id", ""),
        object_path=object_path,
        size_bytes=result["size"],
        sha256=sha256,
        content_type=file.content_type or "application/octet-stream",
        workspace_id=workspace_id,
        owner_id=user.id,
        kind=kind,
        retention=retention,
    )
    session.add(obj)
    await record(
        session,
        actor_type="user",
        actor_id=user.email,
        action="storage.upload",
        resource_type="storage_object",
        resource_id=obj.id,
        detail={"filename": filename, "size": result["size"], "provider": provider.name},
    )
    await session.commit()
    await session.refresh(obj)
    return _out(obj)


@router.post("/upload-sessions", status_code=201)
async def create_session(
    body: UploadSessionCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    """Resumable upload: append chunks, then finalize with size+sha256 verification."""
    filename = sanitize_filename(body.filename)
    if body.size_bytes > settings.max_upload_bytes:
        raise ValidationFailed("size exceeds max_upload_bytes")
    us = UploadSession(
        filename=filename,
        kind=body.kind if body.kind in {"artifact", "model", "dataset", "backup", "archive", "log"} else "artifact",
        size_bytes=body.size_bytes,
        sha256=body.sha256,
        content_type=body.content_type,
        tmp_path=str(Path(settings.storage_root) / "_uploads" / f"{user.id}_{filename}.part"),
        owner_id=user.id,
    )
    if body.size_bytes > 10 * 1024**3 and "gcs" in get_providers():
        info = direct_upload_session("gcs", f"{user.id}/{us.kind}/{filename}", body.size_bytes)
        us.provider = "gcs"
        us.status = "direct"
        session.add(us)
        await session.commit()
        return {"session_id": us.id, **info}
    session.add(us)
    await session.commit()
    return {
        "session_id": us.id,
        "mode": "chunked",
        "provider": "local",
        "chunk_size_hint": 8 * 1024 * 1024,
        "method": "PUT /api/v1/storage/upload-sessions/{session_id}",
        "finalize": "POST /api/v1/storage/upload-sessions/{session_id}/finalize",
    }


@router.put("/upload-sessions/{session_id}", status_code=204)
async def put_chunk(
    session_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    us = await session.get(UploadSession, session_id)
    if us is None or us.owner_id != user.id:
        raise NotFound("upload session not found")
    if us.status != "open":
        raise Conflict(f"session is {us.status}")
    path = Path(us.tmp_path)
    written = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "ab") as out:
        async for chunk in request.stream():
            written += len(chunk)
            if us.bytes_received + written > settings.max_upload_bytes:
                raise ValidationFailed("upload exceeds max_upload_bytes")
            out.write(chunk)
    us.bytes_received += written
    if us.size_bytes and us.bytes_received > us.size_bytes:
        raise ValidationFailed("received more bytes than declared")
    await session.commit()


@router.post(
    "/upload-sessions/{session_id}/finalize",
    response_model=StorageObjectOut,
    status_code=201,
)
async def finalize_session(
    session_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    us = await session.get(UploadSession, session_id)
    if us is None or us.owner_id != user.id:
        raise NotFound("upload session not found")
    if us.status == "finalized":
        obj = await session.get(StorageObject, us.object_id)
        if obj is None:
            raise Conflict("session finalized but object missing")
        return _out(obj)
    if us.status != "open":
        raise Conflict(f"session is {us.status}")
    path = Path(us.tmp_path)
    if not path.is_file():
        raise ValidationFailed("no bytes uploaded")
    digest, size = sha256_stream(_file_iter(path))
    if us.sha256 and digest != us.sha256.lower():
        raise ValidationFailed("sha256 mismatch")
    if us.size_bytes and size != us.size_bytes:
        raise ValidationFailed(f"size mismatch: declared {us.size_bytes}, received {size}")
    provider = choose_provider(us.kind, size)
    object_path = f"{user.id}/{us.kind}/{us.filename}"
    with open(path, "rb") as f:
        provider.save_stream(object_path, f)
    obj = StorageObject(
        id=new_id(),
        filename=us.filename,
        provider=provider.name,
        bucket_or_repository=getattr(provider, "bucket", "") or getattr(provider, "repo_id", ""),
        object_path=object_path,
        size_bytes=size,
        sha256=digest,
        content_type=us.content_type,
        owner_id=user.id,
        kind=us.kind,
    )
    session.add(obj)
    us.status = "finalized"
    us.object_id = obj.id
    path.unlink(missing_ok=True)
    await record(
        session,
        actor_type="user",
        actor_id=user.email,
        action="storage.upload_finalize",
        resource_type="storage_object",
        resource_id=obj.id,
        detail={"filename": us.filename, "size": size},
    )
    await session.commit()
    await session.refresh(obj)
    return _out(obj)


def _file_iter(path: Path):
    def _iter():
        with open(path, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                yield chunk

    return _iter()


@router.get("/objects", response_model=list[StorageObjectOut])
async def list_objects(
    kind: str | None = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    stmt = (
        select(StorageObject).order_by(StorageObject.created_at.desc()).limit(max(1, min(limit, 500)))
    )
    if user.role.value != "admin":
        stmt = stmt.where(StorageObject.owner_id == user.id)
    if kind:
        stmt = stmt.where(StorageObject.kind == kind)
    rows = (await session.execute(stmt)).scalars().all()
    return [_out(o) for o in rows]


@router.get("/objects/{obj_id}", response_model=StorageObjectOut)
async def get_object(
    obj_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    obj = await session.get(StorageObject, obj_id)
    if obj is None or not _own(user, obj.owner_id):
        raise NotFound("object not found")
    return _out(obj)


@router.get("/objects/{obj_id}/download")
async def download(
    obj_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    obj = await session.get(StorageObject, obj_id)
    if obj is None or not _own(user, obj.owner_id):
        raise NotFound("object not found")
    provider = get_providers().get(obj.provider)
    if provider is None:
        raise NotFound(f"provider {obj.provider} not configured")
    stream = provider.open_stream(obj.object_path)

    def gen():
        try:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            close = getattr(stream, "close", None)
            if close:
                close()

    return StreamingResponse(
        gen(),
        media_type=obj.content_type,
        headers={"Content-Disposition": f'attachment; filename="{obj.filename}"'},
    )


@router.delete("/objects/{obj_id}", status_code=204)
async def delete_object(
    obj_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    obj = await session.get(StorageObject, obj_id)
    if obj is None or not _own(user, obj.owner_id):
        raise NotFound("object not found")
    provider = get_providers().get(obj.provider)
    if provider is not None:
        provider.delete(obj.object_path)
    await session.delete(obj)
    await record(
        session,
        actor_type="user",
        actor_id=user.email,
        action="storage.delete",
        resource_type="storage_object",
        resource_id=obj.id,
    )
    await session.commit()


@router.get("/status")
async def storage_status(_: User = Depends(current_user)):
    """Provider availability + local usage snapshot."""
    providers = get_providers()
    local = providers["local"]
    count = sum(1 for _ in local.iter_objects())
    usage = shutil.disk_usage(local.root)
    return {
        "providers_configured": sorted(providers.keys()),
        "local": {"root": str(local.root), "objects_seen": count,
                  "disk_free_gb": round(usage.free / 1024**3, 2)},
        "gcs_configured": "gcs" in providers,
        "hf_configured": "hf" in providers,
    }
