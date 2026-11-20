"""Storage router tests (local provider; GCS/HF adapters require credentials)."""

from __future__ import annotations

import hashlib

import pytest
from conftest import auth, register_and_login

pytestmark = pytest.mark.asyncio


async def test_upload_download_roundtrip(client):
    t = await register_and_login(client)
    content = b"hello omnimcp storage" * 10
    expected = hashlib.sha256(content).hexdigest()

    r = await client.post(
        "/api/v1/storage/upload",
        files={"file": ("hello.bin", content, "application/octet-stream")},
        data={"kind": "artifact", "expected_sha256": expected},
        headers=auth(t),
    )
    assert r.status_code == 201, r.text
    obj = r.json()
    assert obj["provider"] == "local"
    assert obj["size_bytes"] == len(content)
    assert obj["sha256"] == expected

    r = await client.get(f"/api/v1/storage/objects/{obj['id']}/download", headers=auth(t))
    assert r.content == content

    r = await client.get("/api/v1/storage/objects", headers=auth(t))
    assert any(o["id"] == obj["id"] for o in r.json())


async def test_upload_sha256_mismatch_rejected(client):
    t = await register_and_login(client)
    r = await client.post(
        "/api/v1/storage/upload",
        files={"file": ("bad.bin", b"data", "application/octet-stream")},
        data={"kind": "artifact", "expected_sha256": "0" * 64},
        headers=auth(t),
    )
    assert r.status_code == 422


async def test_resumable_upload_session(client):
    t = await register_and_login(client)
    payload = b"chunked-body-" * 1000
    expected_sha = hashlib.sha256(payload).hexdigest()

    r = await client.post(
        "/api/v1/storage/upload-sessions",
        json={"filename": "chunky.bin", "kind": "artifact", "size_bytes": len(payload),
              "sha256": expected_sha},
        headers=auth(t),
    )
    assert r.status_code == 201
    sid = r.json()["session_id"]
    assert r.json()["mode"] == "chunked"

    for chunk in (payload[:4000], payload[4000:]):
        r = await client.put(
            f"/api/v1/storage/upload-sessions/{sid}",
            content=chunk,
            headers=auth(t),
        )
        assert r.status_code == 204

    r = await client.post(f"/api/v1/storage/upload-sessions/{sid}/finalize", headers=auth(t))
    assert r.status_code == 201, r.text
    obj = r.json()
    assert obj["size_bytes"] == len(payload)
    assert obj["sha256"] == expected_sha

    r = await client.post(f"/api/v1/storage/upload-sessions/{sid}/finalize", headers=auth(t))
    assert r.status_code == 201
    assert r.json()["id"] == obj["id"]

    r = await client.get(f"/api/v1/storage/objects/{obj['id']}/download", headers=auth(t))
    assert r.content == payload


async def test_finalize_size_mismatch_rejected(client):
    t = await register_and_login(client)
    r = await client.post(
        "/api/v1/storage/upload-sessions",
        json={"filename": "wrong-size.bin", "size_bytes": 100},
        headers=auth(t),
    )
    sid = r.json()["session_id"]
    await client.put(f"/api/v1/storage/upload-sessions/{sid}", content=b"0" * 10, headers=auth(t))
    r = await client.post(f"/api/v1/storage/upload-sessions/{sid}/finalize", headers=auth(t))
    assert r.status_code == 422


async def test_download_requires_ownership(client):
    t1 = await register_and_login(client, "owner@example.com")
    r = await client.post(
        "/api/v1/storage/upload",
        files={"file": ("secret.txt", b"top secret", "text/plain")},
        headers=auth(t1),
    )
    obj_id = r.json()["id"]
    t2 = await register_and_login(client, "intruder@example.com")
    r = await client.get(f"/api/v1/storage/objects/{obj_id}/download", headers=auth(t2))
    assert r.status_code == 404


async def test_storage_status_shows_unconfigured_providers(client):
    t = await register_and_login(client)
    r = await client.get("/api/v1/storage/status", headers=auth(t))
    body = r.json()
    assert body["providers_configured"] == ["local"]
    assert body["gcs_configured"] is False
    assert body["hf_configured"] is False


async def test_gcs_direct_upload_without_gcs_returns_501():
    from omnimcp.errors import NotConfigured
    from omnimcp.storage import direct_upload_session

    with pytest.raises(NotConfigured):
        direct_upload_session("gcs", "some/path", 11 * 1024**3)


async def test_object_delete(client):
    t = await register_and_login(client)
    r = await client.post(
        "/api/v1/storage/upload",
        files={"file": ("del.bin", b"bye", "application/octet-stream")},
        headers=auth(t),
    )
    obj_id = r.json()["id"]
    r = await client.delete(f"/api/v1/storage/objects/{obj_id}", headers=auth(t))
    assert r.status_code == 204
    r = await client.get(f"/api/v1/storage/objects/{obj_id}", headers=auth(t))
    assert r.status_code == 404
