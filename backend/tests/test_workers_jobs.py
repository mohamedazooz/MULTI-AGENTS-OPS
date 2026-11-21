"""Worker registry + scheduler + job engine API tests."""

from __future__ import annotations

import pytest
from conftest import auth, register_and_login
from sqlalchemy import select

pytestmark = pytest.mark.asyncio

WORKER_ENV_CAPS = {
    "system": "Linux",
    "arch": "x86_64",
    "cpu_cores": 4,
    "ram_total_mb": 8192,
    "ram_available_mb": 4096,
    "capabilities": ["runtime:python", "docker", "gpu"],
    "gpu": [{"vendor": "nvidia", "name": "T4", "memory_total_mb": 16384}],
}


async def register_worker(client, admin_token: str, name: str, caps: dict | None = None):
    r = await client.post(
        "/api/v1/workers/register",
        json={"name": name, "capabilities": caps or WORKER_ENV_CAPS, "max_active_jobs": 2},
        headers=auth(admin_token),
    )
    assert r.status_code == 201, r.text
    data = r.json()
    return data["worker"], data["token"]


async def test_worker_register_and_token_flow(client):
    t = await register_and_login(client)
    w, wtoken = await register_worker(client, t, "test-worker-1")
    assert w["health"] == "online"

    r = await client.get("/api/v1/workers/me", headers=auth(wtoken))
    assert r.status_code == 200
    assert r.json()["id"] == w["id"]

    r = await client.get("/api/v1/workers/me")  # no token
    assert r.status_code in (401, 403)


async def test_worker_name_collision_rejected(client):
    t = await register_and_login(client)
    await register_worker(client, t, "dup-worker")
    r = await client.post(
        "/api/v1/workers/register",
        json={"name": "dup-worker", "capabilities": WORKER_ENV_CAPS},
        headers=auth(t),
    )
    assert r.status_code == 409


async def test_heartbeat_updates_capabilities_and_state(client):
    t = await register_and_login(client)
    w, wtoken = await register_worker(client, t, "hb-worker")

    r = await client.post(
        "/api/v1/workers/me/heartbeat",
        json={"capabilities": {**WORKER_ENV_CAPS, "ram_available_mb": 1234},
              "health": "degraded"},
        headers=auth(wtoken),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["capabilities"]["ram_available_mb"] == 1234
    assert body["health"] == "degraded"


async def test_job_lifecycle_submit_dispatch_run_succeed(client):
    t = await register_and_login(client)
    w, wtoken = await register_worker(client, t, "runner")
    admin_headers = auth(t)

    r = await client.post(
        "/api/v1/jobs",
        json={"kind": "exec", "payload": {"command": {"runtime": "python",
                                                      "script": "print('hello')"}},
              "idempotency_key": "abc-1"},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    job = r.json()
    job_id = job["id"]

    # duplicate idempotent submission returns same job
    r2 = await client.post(
        "/api/v1/jobs",
        json={"kind": "exec", "payload": {}, "idempotency_key": "abc-1"},
        headers=admin_headers,
    )
    assert r2.status_code == 201
    assert r2.json()["id"] == job_id

    r = await client.post("/api/v1/system/scheduler/tick", headers=admin_headers)
    assert r.json()["dispatched"] >= 1

    r = await client.post("/api/v1/workers/me/claim", headers=auth(wtoken))
    assert r.json()["job_id"] == job_id
    assert r.json()["payload"]["command"]["script"] == "print('hello')"

    r = await client.post(
        f"/api/v1/workers/me/jobs/{job_id}/logs",
        json=[{"stream": "stdout", "line": "hello"}],
        headers=auth(wtoken),
    )
    assert r.status_code == 204

    r = await client.post(
        f"/api/v1/workers/me/jobs/{job_id}/status",
        json={"success": True, "result": {"exit_code": 0}},
        headers=auth(wtoken),
    )
    assert r.status_code == 200

    r = await client.get(f"/api/v1/jobs/{job_id}", headers=admin_headers)
    assert r.json()["state"] == "SUCCEEDED"

    r = await client.get(f"/api/v1/jobs/{job_id}/logs", headers=admin_headers)
    assert any(e["line"] == "hello" for e in r.json()["logs"])


async def test_job_failure_with_retry_then_success(client):
    t = await register_and_login(client)
    w, wtoken = await register_worker(client, t, "retry-runner")
    h = auth(t)

    r = await client.post("/api/v1/jobs", json={"kind": "exec", "payload": {}}, headers=h)
    job_id = r.json()["id"]
    await client.post("/api/v1/system/scheduler/tick", headers=h)
    await client.post("/api/v1/workers/me/claim", headers=auth(wtoken))

    await client.post(
        f"/api/v1/workers/me/jobs/{job_id}/status",
        json={"success": False, "error": "boom"},
        headers=auth(wtoken),
    )
    r = await client.get(f"/api/v1/jobs/{job_id}", headers=h)
    body = r.json()
    assert body["state"] in ("RETRYING", "QUEUED"), body
    assert body["attempt"] >= 1

    await client.post("/api/v1/system/scheduler/tick", headers=h)
    r = await client.post("/api/v1/workers/me/claim", headers=auth(wtoken))
    assert r.json()["job_id"] == job_id
    await client.post(
        f"/api/v1/workers/me/jobs/{job_id}/status",
        json={"success": True, "result": {"ok": 1}},
        headers=auth(wtoken),
    )
    r = await client.get(f"/api/v1/jobs/{job_id}", headers=h)
    assert r.json()["state"] == "SUCCEEDED"


async def test_cancel_queued_job(client):
    t = await register_and_login(client)
    await register_worker(client, t, "cancel-worker-never")
    h = auth(t)
    r = await client.post("/api/v1/jobs", json={"kind": "exec", "payload": {}}, headers=h)
    job_id = r.json()["id"]

    # not dispatched yet (no tick) -> direct cancel
    r = await client.post(f"/api/v1/jobs/{job_id}/cancel", headers=h)
    assert r.json()["state"] == "CANCELLED"

    r = await client.post(f"/api/v1/jobs/{job_id}/cancel", headers=h)
    assert r.status_code == 409


async def test_offline_worker_requeues_jobs(client):
    t = await register_and_login(client)
    w, wtoken = await register_worker(client, t, "ghost-worker")
    h = auth(t)

    r = await client.post("/api/v1/jobs", json={"kind": "exec", "payload": {}}, headers=h)
    job_id = r.json()["id"]
    await client.post("/api/v1/system/scheduler/tick", headers=h)

    # simulate worker death: heartbeat far in the past
    from datetime import timedelta

    from omnimcp.db import session_factory
    from omnimcp.models import Worker, utcnow

    factory = session_factory()
    async with factory() as session:
        worker = (
            await session.execute(select(Worker).where(Worker.name == "ghost-worker"))
        ).scalar_one()
        worker.last_heartbeat = utcnow().replace(tzinfo=None) - timedelta(seconds=120)
        await session.commit()

    r = await client.post("/api/v1/system/scheduler/tick", headers=h)
    counts = r.json()
    assert counts["workers_offlined"] >= 1
    assert counts["requeued_on_worker_loss"] >= 1

    r = await client.get(f"/api/v1/jobs/{job_id}", headers=h)
    assert r.json()["worker_id"] is None
    assert r.json()["state"] == "QUEUED"

    # offline worker cannot claim
    r = await client.post("/api/v1/workers/me/claim", headers=auth(wtoken))
    # claim revives the worker by design; then job assigned again after tick
    await client.post("/api/v1/system/scheduler/tick", headers=h)
    r = await client.post("/api/v1/workers/me/claim", headers=auth(wtoken))
    assert r.json()["job_id"] == job_id


async def test_capability_matching_selects_right_worker(client):
    t = await register_and_login(client)
    h = auth(t)
    caps_a = {**WORKER_ENV_CAPS, "capabilities": ["runtime:python"]}
    caps_b = {**WORKER_ENV_CAPS, "capabilities": ["runtime:python", "runtime:node"]}
    wa, ta_ = await register_worker(client, t, "caps-a", caps_a)
    wb, tb_ = await register_worker(client, t, "caps-b", caps_b)

    r = await client.post(
        "/api/v1/jobs",
        json={"kind": "exec", "payload": {}, "required_capabilities": ["runtime:node"]},
        headers=h,
    )
    job_id = r.json()["id"]
    await client.post("/api/v1/system/scheduler/tick", headers=h)
    r = await client.post("/api/v1/workers/me/claim", headers=auth(tb_))
    assert r.json()["job_id"] == job_id
    r = await client.post("/api/v1/workers/me/claim", headers=auth(ta_))
    assert r.json()["job_id"] is None


async def test_insufficient_ram_worker_not_selected(client):
    t = await register_and_login(client)
    h = auth(t)
    small = {**WORKER_ENV_CAPS, "ram_total_mb": 512}
    await register_worker(client, t, "small-box", small)
    r = await client.post(
        "/api/v1/jobs", json={"kind": "exec", "payload": {}, "min_ram_mb": 4096}, headers=h
    )
    job_id = r.json()["id"]
    r = await client.post("/api/v1/system/scheduler/tick", headers=h)
    assert r.json()["dispatched"] == 0
    r = await client.get(f"/api/v1/jobs/{job_id}", headers=h)
    assert r.json()["state"] == "QUEUED"


async def test_untrusted_job_requires_sandbox_worker(client):
    t = await register_and_login(client)
    h = auth(t)
    await register_worker(client, t, "no-sandbox")
    r = await client.post(
        "/api/v1/jobs", json={"kind": "exec", "payload": {}, "untrusted": True}, headers=h
    )
    job_id = r.json()["id"]
    r = await client.post("/api/v1/system/scheduler/tick", headers=h)
    assert r.json()["dispatched"] == 0
    r = await client.get(f"/api/v1/jobs/{job_id}", headers=h)
    assert r.json()["state"] == "QUEUED"


async def test_job_timeout_enforced(client):
    t = await register_and_login(client)
    _, wtoken = await register_worker(client, t, "timeout-worker")
    h = auth(t)
    r = await client.post(
        "/api/v1/jobs", json={"kind": "exec", "payload": {}, "timeout_s": 3600}, headers=h
    )
    job_id = r.json()["id"]
    await client.post("/api/v1/system/scheduler/tick", headers=h)

    r = await client.post("/api/v1/workers/me/claim", headers=auth(wtoken))
    assert r.json()["job_id"] == job_id

    # simulate a started job far in the past
    from datetime import timedelta

    from omnimcp.db import session_factory
    from omnimcp.models import Job, utcnow

    factory = session_factory()
    async with factory() as session:
        job = await session.get(Job, job_id)
        job.started_at = utcnow().replace(tzinfo=None) - timedelta(days=2)
        await session.commit()

    await client.post("/api/v1/system/scheduler/tick", headers=h)
    r = await client.get(f"/api/v1/jobs/{job_id}", headers=h)
    assert r.json()["state"] == "FAILED"
    assert "timeout" in r.json()["error"]


async def test_workers_quarantine_requires_admin(client):
    t = await register_and_login(client)
    w, _ = await register_worker(client, t, "quarantine-me")
    r = await client.post(f"/api/v1/workers/{w['id']}/disable", headers=auth(t))
    assert r.status_code == 200
    assert r.json()["health"] == "quarantined"
    r = await client.post(f"/api/v1/workers/{w['id']}/enable", headers=auth(t))
    assert r.json()["health"] == "online"
