# Implementation Status

Honest breakdown required by the engineering charter. "Tested" means an automated test in
this repository passes against a real component — not a mock.

Legend: ✅ Implemented+Tested · 🟡 Partially implemented · 🔴 Not implemented · ⛔ Blocked

## Phase 0-1 — Foundation

| Feature | Status | Evidence |
|---|---|---|
| FastAPI app, config, structured JSON logs, health/ready/metrics | ✅ | boots; `api/system.py`; covered by all tests |
| Auth (argon2 + JWT, 12h user / 30d worker tokens, revocation) | ✅ | `tests/test_auth_rbac.py` (10 tests) |
| RBAC admin/operator/user + ownership checks | ✅ | `tests/test_auth_rbac.py` |
| Rate limiting (register/login/worker-register) | ✅ | in-memory sliding window, tested |
| Alembic migrations | 🔴 (ADR-0004: deferred; `create_all` used) | — |
| CI pipeline | ✅ | `.github/workflows/ci.yml` (ruff + both test suites) |

## Phase 2 — Control plane

| Feature | Status | Evidence |
|---|---|---|
| Agent registry (keys hashed, shown once, enable/disable) | ✅ | `tests/test_connectors_agents_audit.py` |
| Worker registry (register, heartbeat, caps, enable/disable, quarantine) | ✅ | `tests/test_workers_jobs.py` (12 tests) |
| Connector registry (mcp/http/openapi, health probe) | ✅ CRUD+validation+health tested; external diagnose hits are 🟡 (only reachability probed) |
| Audit trail with secret redaction | ✅ | tested incl. redaction |
| MCP server, 12 typed tools at `/mcp` | ✅ | E2E `test_mcp_client_discovery_and_call` (real `streamablehttp_client`) |
| MCP bearer-token enforcement | 🔴 pending | tools currently run server-side unauthenticated (see [MCP_INTEGRATION.md](MCP_INTEGRATION.md)) |

## Phase 3 — Worker agent

| Feature | Status | Evidence |
|---|---|---|
| Registration, unique identity, capability discovery | ✅ | `worker/tests` + backend tests |
| Heartbeat, reconnection with backoff | ✅ (backoff unit-level; E2E reconnect not simulated) |
| Pull-based claim loop, log streaming, cancellation | ✅ | E2E `test_worker_executes_real_job_live`, `test_job_cancellation_running` |
| Worker-loss offline detection + requeue | ✅ | E2E `test_worker_loss_requeue_live` and unit test |
| Resource limits (RLIMIT_AS/CPU/NPROC, process-group kill) | ✅ | timeout + memory-limit worker tests |
| Cross-platform (Windows/macOS) | 🟡 | POSIX paths; rlimits are POSIX; Windows guarded but untested on Windows |
| Docker/Dagger runtime detection | 🟡 | detection only; not used as execution backend |

## Phase 4 — Runtime engine

| Feature | Status | Evidence |
|---|---|---|
| Python/shell subprocess execution with limits | ✅ | worker unit + E2E tests |
| Node.js execution | ✅ (same executor; requires node on host) | executor tests generically |
| Rust build job | 🔴 not verified (no cargo job run on a worker in CI) |
| Docker / OCI / gVisor isolation | 🔴 Phase 4 (interface planned in scheduler adapter) |
| Dagger integration | 🔴 deferred (license+maintenance verified in [DEPENDENCY_MATRIX.md](DEPENDENCY_MATRIX.md)) |
| Untrusted ⇒ sandbox requirement enforced server-side | ✅ | `test_untrusted_requires_sandbox` |

## Phase 5 — Workspace & storage

| Feature | Status | Evidence |
|---|---|---|
| Workspace CRUD, file read/write/list/delete, project detection | ✅ | `tests/test_workspaces_archives.py` (12 tests) |
| Zip/tar hardening (Zip Slip, absolute paths, symlinks, entry caps, total-bomb cap) | ✅ | dedicated attack tests |
| git clone (https/git@ only) | ✅ URL-policy tested; real-clone network test 🟡 not in CI |
| Local storage provider (streaming, SHA-256) | ✅ | `tests/test_storage.py` (9 tests) |
| Chunked resumable upload sessions + integrity mismatch handling | ✅ | tested |
| GCS provider | 🟡 implemented adapter; live integration ⛔ no credentials in dev sandbox |
| HF provider | 🟡 same as GCS |
| Direct-to-GCS resumable URL for >10 GB (no VPS buffering) | ✅ session logic implemented + tested for NotConfigured; live GCS ⛔ unverified |

## Phase 6-7 — Scheduling & reliability

| Feature | Status | Evidence |
|---|---|---|
| Capability/resource matching, 6 scheduling strategies | ✅ | unit-tested (`pick_worker`) |
| Idempotency keys, safe retry (max_retries), timeout→retry | ✅ | tested |
| Cancellation incl. RUNNING via cancel-check | ✅ | unit + E2E |
| Temporal workflows | 🔴 deferred (PostgreSQL-backed persistence first) |
| Nomad / Ray adapters | 🔴 deferred (Nomad BUSL-1.1 ⇒ Reject for now) |

## Phase 8-9 — Plugins, dashboard

| Feature | Status | Evidence |
|---|---|---|
| Plugin/SDK registry, gateway adapter (ContextForge/ToolHive) | 🔴 Phase 8 |
| Next.js dashboard | 🔴 Phase 9 (REST APIs it will consume are shipped and tested) |

## Phase 10 — Hardening

| Feature | Status | Evidence |
|---|---|---|
| Threat model, security docs, ADRs | ✅ documents |
| Load tests / failure injection / chaos | 🔴 not run (policy in [PERFORMANCE.md](PERFORMANCE.md)) |
| Production deployment | ⛔ requires user authorization — never executed |

## Test totals (as of this writing)

- backend: **51 passed** (`pytest tests` incl. 4 live-server E2E)
- worker: **10 passed**
- lint: `ruff check backend worker` — clean
