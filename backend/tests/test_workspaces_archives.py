"""Workspace, filesystem and archive-security tests."""

from __future__ import annotations

import io
import os
import tarfile
import zipfile
from pathlib import Path

import pytest
from conftest import auth, register_and_login

pytestmark = pytest.mark.asyncio


async def make_workspace(client, t: str, name: str = "ws-test") -> dict:
    r = await client.post(
        "/api/v1/workspaces", json={"name": name, "description": "test"}, headers=auth(t)
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_workspace_crud_and_files(client):
    t = await register_and_login(client)
    ws = await make_workspace(client, t, "crud-ws")

    r = await client.put(
        f"/api/v1/workspaces/{ws['id']}/files",
        json={"path": "src/app.py", "content": "print('hi')"},
        headers=auth(t),
    )
    assert r.status_code == 201
    await client.put(
        f"/api/v1/workspaces/{ws['id']}/files",
        json={"path": "pyproject.toml", "content": "[project]\nname='x'\n"},
        headers=auth(t),
    )

    r = await client.get(
        f"/api/v1/workspaces/{ws['id']}/files/read",
        params={"path": "src/app.py"},
        headers=auth(t),
    )
    assert r.json()["content"] == "print('hi')"

    r = await client.get(f"/api/v1/workspaces/{ws['id']}/files", headers=auth(t))
    entries = [e["path"] for e in r.json()["entries"]]
    assert "src/app.py" in entries

    r = await client.get(f"/api/v1/workspaces/{ws['id']}/inspect", headers=auth(t))
    assert r.json()["project_type"] == "python"
    assert r.json()["file_count"] == 2

    r = await client.delete(
        f"/api/v1/workspaces/{ws['id']}/files", params={"path": "src/app.py"}, headers=auth(t)
    )
    assert r.status_code == 204


async def test_workspace_path_traversal_rejected(client):
    t = await register_and_login(client)
    ws = await make_workspace(client, t, "traverse-ws")
    root = Path(os.environ["OMNIMCP_WORKSPACE_ROOT"]).resolve()
    sentinel = root / "STOLEN.txt"
    sentinel.touch()

    for evil in ["../../../STOLEN.txt", "/etc/passwd", "src/../../STOLEN.txt"]:
        r = await client.put(
            f"/api/v1/workspaces/{ws['id']}/files",
            json={"path": evil, "content": "evil"},
            headers=auth(t),
        )
        assert r.status_code == 422, evil

    assert sentinel.read_bytes() == b""
    sentinel.unlink()


async def test_workspace_delete_requires_approval(client):
    t = await register_and_login(client)
    ws = await make_workspace(client, t, "delete-ws")
    r = await client.delete(f"/api/v1/workspaces/{ws['id']}", headers=auth(t))
    assert r.status_code == 403


async def test_workspace_admin_delete(client):
    t = await register_and_login(client)
    ws = await make_workspace(client, t, "admin-delete-ws")
    r = await client.delete(
        f"/api/v1/workspaces/{ws['id']}", params={"approve": "true"}, headers=auth(t)
    )
    assert r.status_code == 204
    r = await client.get(f"/api/v1/workspaces/{ws['id']}", headers=auth(t))
    assert r.status_code == 404


def _zip_bytes(entries, symlinks=()):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries:
            zf.writestr(name, data)
        for target, link in symlinks:
            zi = zipfile.ZipInfo(target)
            zi.create_system = 3
            zi.external_attr = 0o120777 << 16
            zf.writestr(zi, link)
    return buf.getvalue()


async def _upload_archive(client, t: str, ws: dict, payload: bytes, fname="evil.zip"):
    return await client.post(
        f"/api/v1/workspaces/{ws['id']}/archive",
        files={"file": (fname, io.BytesIO(payload), "application/zip")},
        headers=auth(t),
    )


async def test_zip_slip_rejected(client):
    t = await register_and_login(client)
    ws = await make_workspace(client, t, "zip-slip-ws")
    root = Path(os.environ["OMNIMCP_WORKSPACE_ROOT"]).resolve()
    evil = _zip_bytes([("../../escaped.txt", b"payload")])
    r = await _upload_archive(client, t, ws, evil)
    assert r.status_code == 422
    assert not (root / "escaped.txt").exists()


async def test_zip_absolute_path_rejected(client):
    t = await register_and_login(client)
    ws = await make_workspace(client, t, "zip-abs-ws")
    evil = _zip_bytes([("/etc/evil.txt", b"payload")])
    r = await _upload_archive(client, t, ws, evil)
    assert r.status_code == 422


async def test_zip_symlink_rejected(client):
    t = await register_and_login(client)
    ws = await make_workspace(client, t, "zip-symlink-ws")
    evil = _zip_bytes([], symlinks=[("link.txt", "/etc/passwd")])
    r = await _upload_archive(client, t, ws, evil)
    assert r.status_code == 422


async def test_zip_bomb_detected(client, monkeypatch):
    import omnimcp.config as cfg

    monkeypatch.setattr(cfg.settings, "max_workspace_bytes", 1024 * 1024)
    t = await register_and_login(client)
    ws = await make_workspace(client, t, "bomb-ws")
    big = _zip_bytes([("zeros.bin", b"\x00" * (4 * 1024 * 1024))])
    r = await _upload_archive(client, t, ws, big)
    assert r.status_code == 422


async def test_tar_bomb_detected(client, monkeypatch):
    import omnimcp.config as cfg

    monkeypatch.setattr(cfg.settings, "max_workspace_bytes", 1024 * 1024)
    t = await register_and_login(client)
    ws = await make_workspace(client, t, "tar-bomb-ws")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        data = b"\x00" * (4 * 1024 * 1024)
        info = tarfile.TarInfo("big.bin")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    r = await client.post(
        f"/api/v1/workspaces/{ws['id']}/archive",
        files={"file": ("bomb.tar.gz", io.BytesIO(buf.getvalue()), "application/gzip")},
        headers=auth(t),
    )
    assert r.status_code == 422


async def test_tar_symlink_rejected(client):
    t = await register_and_login(client)
    ws = await make_workspace(client, t, "tar-symlink-ws")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tf.addfile(info)
    r = await client.post(
        f"/api/v1/workspaces/{ws['id']}/archive",
        files={"file": ("evil.tar", io.BytesIO(buf.getvalue()), "application/x-tar")},
        headers=auth(t),
    )
    assert r.status_code == 422


async def test_valid_archive_extracts(client):
    t = await register_and_login(client)
    ws = await make_workspace(client, t, "good-zip-ws")
    good = _zip_bytes([("pyproject.toml", b"[project]\n"), ("src/main.py", b"print(1)")])
    r = await _upload_archive(client, t, ws, good)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["files"] == 2
    assert body["format"] == "zip"
    r = await client.get(f"/api/v1/workspaces/{ws['id']}/inspect", headers=auth(t))
    assert r.json()["project_type"] == "python"


async def test_workspace_ownership_enforced(client):
    t1 = await register_and_login(client, "owner@example.com")
    r = await client.post("/api/v1/workspaces", json={"name": "own-ws"}, headers=auth(t1))
    assert r.status_code == 201
    ws_id = r.json()["id"]
    t3 = await register_and_login(client, "third@example.com")
    r = await client.get(f"/api/v1/workspaces/{ws_id}", headers=auth(t3))
    assert r.status_code in (403, 404)
