"""End-to-end integration test: real HTTP server, real worker agent, real MCP client.

Covers acceptance criteria: worker registers over the network, capabilities get
reported, a real Python job executes, logs are returned, cancellation works,
an MCP client discovers tools and calls one.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from conftest import auth

pytestmark = pytest.mark.asyncio

ADMIN = {"email": "admin@example.com", "password": "S3cure-passw0rd!"}
SLOW_TIMEOUT = 30


async def _setup(server, worker_name="e2e-worker-1"):
    async with httpx.AsyncClient(base_url=server.url, timeout=10) as c:
        r = await c.post("/api/v1/auth/register", json=ADMIN)
        assert r.status_code in (201, 409)
        r = await c.post("/api/v1/auth/login", json=ADMIN)
        token = r.json()["access_token"]

        from omnimcp_worker.agent import register_worker

        reg = await register_worker(
            server.url, token, worker_name, max_active_jobs=2
        )
        assert "error" not in reg, reg
        return token, reg


async def _wait_job_state(base_url, token, job_id, want, timeout=30):
    from time import monotonic

    deadline = monotonic() + timeout
    async with httpx.AsyncClient(base_url=base_url, timeout=10) as client:
        while monotonic() < deadline:
            r = await client.get(f"/api/v1/jobs/{job_id}", headers=auth(token))
            state = r.json()["state"]
            if state == want:
                return r.json()
            await asyncio.sleep(0.3)
    raise AssertionError(f"job {job_id} did not reach {want} in {timeout}s (last={state})")


async def test_worker_registers_executes_reports(live_server):
    from omnimcp_worker.agent import WorkerAgent

    token, reg = await _setup(live_server)
    async with httpx.AsyncClient(base_url=live_server.url, timeout=10) as c:
        r = await c.get("/api/v1/workers", headers=auth(token))
        assert any(w["health"] == "online" for w in r.json())
        worker = r.json()[0]
        caps = worker["capabilities"]
        assert caps["system"] and caps["cpu_cores"] >= 1 and "runtimes" in caps

    agent = WorkerAgent(
        live_server.url,
        reg["token"],
        name="e2e",
        poll_interval=0.2,
        heartbeat_interval=0.5,
    )
    task = asyncio.create_task(agent.run())

    async with httpx.AsyncClient(base_url=live_server.url, timeout=10) as c:
        r = await c.post(
            "/api/v1/jobs",
            json={
                "kind": "exec",
                "payload": {"command": {"runtime": "python",
                                        "script": "print('omnimcp-e2e-ok')"}},
                "timeout_s": 60,
            },
            headers=auth(token),
        )
        assert r.status_code == 201, r.text
        job_id = r.json()["id"]
        done = await _wait_job_state(live_server.url, token, job_id, "SUCCEEDED", timeout=SLOW_TIMEOUT)
        assert done["result"]["exit_code"] == 0

        r = await c.get(f"/api/v1/jobs/{job_id}/logs", headers=auth(token))
        lines = [line["line"] for line in r.json()["logs"]]
        assert any("omnimcp-e2e-ok" in ln for ln in lines)

    await agent.stop()
    task.cancel()


async def test_job_cancellation_running(live_server):
    from omnimcp_worker.agent import WorkerAgent

    token, reg = await _setup(live_server, "e2e-worker-cancel")
    agent = WorkerAgent(
        live_server.url,
        reg["token"],
        name="cancel",
        poll_interval=0.2,
        heartbeat_interval=0.5,
    )
    task = asyncio.create_task(agent.run())

    async with httpx.AsyncClient(base_url=live_server.url, timeout=10) as c:
        r = await c.post(
            "/api/v1/jobs",
            json={
                "kind": "exec",
                "payload": {"command": {"runtime": "python",
                                        "script": "import time; time.sleep(120)"}},
                "timeout_s": 300,
            },
            headers=auth(token),
        )
        job_id = r.json()["id"]
        await _wait_job_state(live_server.url, token, job_id, "RUNNING", timeout=30)

        r = await c.post(f"/api/v1/jobs/{job_id}/cancel", headers=auth(token))
        assert r.status_code == 200

        done = await _wait_job_state(live_server.url, token, job_id, "CANCELLED", timeout=30)
        assert done["state"] == "CANCELLED"

    await agent.stop()
    task.cancel()


async def test_mcp_client_discovery_and_call(live_server):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    token, reg = await _setup(live_server, "e2e-worker-mcp-never")
    mcp_url = live_server.url + "/mcp"

    async with (
        streamablehttp_client(mcp_url) as (read, write, _get_session_id),
        ClientSession(read, write) as session,
    ):
            init = await session.initialize()
            assert init.serverInfo.name == "omnimcp"

            tools = await session.list_tools()
            tool_names = {t.name for t in tools.tools}
            expected = {
                "system_status",
                "workspace_create",
                "workspace_list",
                "filesystem_read",
                "filesystem_write",
                "job_submit",
                "job_status",
                "job_cancel",
                "worker_list",
                "worker_capabilities",
                "connector_list",
                "artifact_list",
            }
            assert expected <= tool_names, tool_names

            result = await session.call_tool("system_status", {})
            payload = json.loads(result.content[0].text)
            assert payload["version"]
            assert "queued" in payload

            result = await session.call_tool(
                "filesystem_write",
                {"workspace_name": "no-such-ws", "path": "x.py", "content": "1"},
            )
            assert "error" in result.content[0].text


async def test_worker_loss_requeue_live(live_server):
    """Worker registered but never runs -> scheduler detects loss and requeues."""
    token, reg = await _setup(live_server, "e2e-worker-ghost")
    async with httpx.AsyncClient(base_url=live_server.url, timeout=10) as c:
        r = await c.post("/api/v1/jobs", json={"kind": "exec", "payload": {}}, headers=auth(token))
        job_id = r.json()["id"]
        await _wait_job_state(live_server.url, token, job_id, "ASSIGNED", timeout=15)
        # scheduler interval 0.2s, offline threshold 2s: agent never heartbeats
        from time import monotonic

        deadline = monotonic() + 20
        last = None
        while monotonic() < deadline:
            r = await c.get(f"/api/v1/jobs/{job_id}", headers=auth(token))
            last = r.json()
            if last["state"] in ("FAILED",):
                break
            await asyncio.sleep(0.5)
        assert last["state"] in ("QUEUED", "RETRYING", "FAILED")
        assert last["worker_id"] is None
