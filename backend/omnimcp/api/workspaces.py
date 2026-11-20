"""Workspace routes: create, list, get, delete (approval-gated), files, clone, extract."""


import hashlib
import json
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import workspaces as wslib
from ..audit import record
from ..config import settings
from ..db import get_session
from ..deps import current_user
from ..errors import Conflict, Forbidden, NotFound, ValidationFailed
from ..models import User, Workspace, utcnow
from ..schemas import FileWriteIn, WorkspaceCreate, WorkspaceOut

router = APIRouter(prefix="/api/v1/workspaces", tags=["workspaces"])


def _out(w: Workspace) -> WorkspaceOut:
    return WorkspaceOut(
        id=w.id,
        name=w.name,
        description=w.description,
        project_type=w.project_type,
        created_at=w.created_at,
    )


async def _get(session: AsyncSession, workspace_id: str) -> Workspace:
    w = await session.get(Workspace, workspace_id)
    if w is None:
        raise NotFound("workspace not found")
    return w


def _authorize(user: User, w: Workspace) -> None:
    if user.role.value != "admin" and w.owner_id not in (None, user.id):
        raise Forbidden("not your workspace")


@router.post("", response_model=WorkspaceOut, status_code=201)
async def create(
    body: WorkspaceCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    exists = (
        await session.execute(select(Workspace).where(Workspace.name == body.name))
    ).scalar_one_or_none()
    if exists is not None:
        raise Conflict(f"workspace {body.name!r} already exists")
    ws_dir = wslib.safe_workspace_dir(body.name)
    if ws_dir.exists():
        raise Conflict(f"workspace directory {body.name!r} already exists on disk")
    ws_dir.mkdir(parents=True, exist_ok=False)
    w = Workspace(name=body.name, owner_id=user.id, description=body.description)
    session.add(w)
    detail: dict = {"name": body.name}
    if body.repo_url:
        try:
            detail.update(wslib.git_clone(ws_dir, body.repo_url, body.branch))
        except Exception:
            shutil.rmtree(ws_dir, ignore_errors=True)
            raise
    w.project_type = wslib.detect_project_type(ws_dir)
    await record(
        session,
        actor_type="user",
        actor_id=user.email,
        action="workspace.create",
        resource_type="workspace",
        resource_id=w.name,
        detail=detail,
        approval=bool(body.repo_url),
    )
    await session.commit()
    await session.refresh(w)
    return _out(w)


@router.get("", response_model=list[WorkspaceOut])
async def list_workspaces(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    stmt = select(Workspace).order_by(Workspace.created_at)
    if user.role.value != "admin":
        stmt = stmt.where(Workspace.owner_id == user.id)
    rows = (await session.execute(stmt)).scalars().all()
    return [_out(w) for w in rows]


@router.get("/{workspace_id}", response_model=WorkspaceOut)
async def get_workspace(
    workspace_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    w = await _get(session, workspace_id)
    _authorize(user, w)
    return _out(w)


@router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(
    workspace_id: str,
    approve: bool = Query(False),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    """Delete requires approve=true and elevated role; operators must confirm twice."""
    w = await _get(session, workspace_id)
    _authorize(user, w)
    if user.role.value == "user" or not approve:
        raise Forbidden("deletion requires approve=true and elevated role")
    if not w.approval_delete and user.role.value != "admin":
        w.approval_delete = True
        await session.commit()
        raise Forbidden("first approval recorded; repeat the request to confirm")
    ws_dir = wslib.safe_workspace_dir(w.name)
    if ws_dir.exists():
        shutil.rmtree(ws_dir)
    await session.delete(w)
    await record(
        session,
        actor_type="user",
        actor_id=user.email,
        action="workspace.delete",
        resource_type="workspace",
        resource_id=w.name,
        approval=True,
    )
    await session.commit()


@router.get("/{workspace_id}/files")
async def list_files(
    workspace_id: str,
    path: str = "",
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    w = await _get(session, workspace_id)
    _authorize(user, w)
    ws_dir = wslib.safe_workspace_dir(w.name)
    if not ws_dir.exists():
        raise NotFound("workspace directory missing on disk")
    base = wslib.safe_join(ws_dir, path)
    if base.is_file():
        return {"path": path, "entries": [{"path": path, "size": base.stat().st_size}]}
    entries = wslib.list_tree(base)
    return {"path": path, "entries": entries}


@router.get("/{workspace_id}/files/read")
async def read_file(
    workspace_id: str,
    path: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    w = await _get(session, workspace_id)
    _authorize(user, w)
    ws_dir = wslib.safe_workspace_dir(w.name)
    p = wslib.safe_join(ws_dir, path)
    if not p.is_file():
        raise NotFound(f"file not found: {path}")
    st = p.stat()
    if st.st_size > settings.max_workspace_bytes:
        raise ValidationFailed("file too large to read as text")
    data = p.read_bytes()[: wslib.MAX_TEXT_READ_BYTES]
    truncated = st.st_size > len(data)
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValidationFailed("binary file: use storage download") from e
    return {"path": path, "size": st.st_size, "truncated": truncated, "content": content}


@router.put("/{workspace_id}/files", status_code=201)
async def write_file(
    workspace_id: str,
    body: FileWriteIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    w = await _get(session, workspace_id)
    _authorize(user, w)
    ws_dir = wslib.safe_workspace_dir(w.name)
    p = wslib.safe_join(ws_dir, body.path)
    if p.exists() and not body.overwrite:
        raise Conflict("file exists and overwrite=false")
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = body.content.encode("utf-8")
    if len(payload) > settings.max_workspace_bytes:
        raise ValidationFailed("content exceeds workspace size limit")
    p.write_bytes(payload)
    await record(
        session,
        actor_type="user",
        actor_id=user.email,
        action="workspace.file_write",
        resource_type="workspace",
        resource_id=w.name,
        detail={"path": body.path, "bytes": len(payload)},
    )
    await session.commit()
    return {"path": body.path, "bytes": len(payload)}


@router.delete("/{workspace_id}/files", status_code=204)
async def delete_file(
    workspace_id: str,
    path: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    w = await _get(session, workspace_id)
    _authorize(user, w)
    ws_dir = wslib.safe_workspace_dir(w.name)
    p = wslib.safe_join(ws_dir, path)
    if p.is_file():
        p.unlink()
    elif p.is_dir():
        shutil.rmtree(p)
    else:
        raise NotFound(f"not found: {path}")
    await session.commit()


@router.post("/{workspace_id}/archive", status_code=201)
async def extract_archive(
    workspace_id: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    """Stream-upload an archive to a temp path, then extract it with hardening checks."""
    w = await _get(session, workspace_id)
    _authorize(user, w)
    ws_dir = wslib.safe_workspace_dir(w.name)
    tmp = Path(settings.storage_root) / "_archive_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    archive_path = tmp / f"{w.id}_{utcnow().strftime('%Y%m%d%H%M%S')}.upload"
    size = 0
    h_sha = hashlib.sha256()
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with open(archive_path, "wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > settings.max_workspace_bytes:
                raise ValidationFailed("archive exceeds workspace size limit")
            h_sha.update(chunk)
            out.write(chunk)
    try:
        result = wslib.extract_archive(archive_path, ws_dir)
    finally:
        archive_path.unlink(missing_ok=True)
    w.project_type = wslib.detect_project_type(ws_dir)
    await record(
        session,
        actor_type="user",
        actor_id=user.email,
        action="workspace.archive_extract",
        resource_type="workspace",
        resource_id=w.name,
        detail={"archive_size": size, "sha256": h_sha.hexdigest(), **result},
    )
    await session.commit()
    return result


@router.post("/{workspace_id}/clone")
async def clone(
    workspace_id: str,
    repo_url: str = Form(...),
    branch: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    w = await _get(session, workspace_id)
    _authorize(user, w)
    ws_dir = wslib.safe_workspace_dir(w.name)
    if any(ws_dir.iterdir()):
        raise Conflict("workspace not empty")
    detail = wslib.git_clone(ws_dir, repo_url, branch or None)
    w.project_type = wslib.detect_project_type(ws_dir)
    await record(
        session,
        actor_type="user",
        actor_id=user.email,
        action="workspace.clone",
        resource_type="workspace",
        resource_id=w.name,
        detail=detail,
        approval=True,
    )
    await session.commit()
    return detail


@router.get("/{workspace_id}/inspect")
async def inspect(
    workspace_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    """Project metadata: type, dependency manifests, structure summary."""
    w = await _get(session, workspace_id)
    _authorize(user, w)
    ws_dir = wslib.safe_workspace_dir(w.name)
    if not ws_dir.exists():
        raise NotFound("workspace directory missing on disk")
    files = wslib.list_tree(ws_dir, max_entries=2000)
    deps: dict = {}
    if (ws_dir / "pyproject.toml").exists():
        deps["pyproject"] = True
    pkg = ws_dir / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text()[:65536])
            deps["package_json"] = {
                "name": data.get("name"),
                "scripts": sorted((data.get("scripts") or {}).keys())[:20],
                "dependency_count": len(data.get("dependencies") or {})
                + len(data.get("devDependencies") or {}),
            }
        except Exception:
            deps["package_json"] = {"error": "unparseable"}
    req = ws_dir / "requirements.txt"
    if req.exists():
        lines = [ln.strip() for ln in req.read_text(errors="ignore").splitlines()]
        deps["requirements"] = [ln for ln in lines if ln and not ln.startswith("#")][:100]
    return {
        "id": w.id,
        "name": w.name,
        "project_type": wslib.detect_project_type(ws_dir),
        "file_count": len(files),
        "total_bytes": sum(f["size"] for f in files),
        "dependencies": deps,
    }
