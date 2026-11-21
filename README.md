# OmniMCP

Unified distributed AI Agent development & execution platform. One control plane exposing
**REST APIs and MCP tools over the same domain services**, with a lightweight **Worker
Agent** that runs on any machine (Windows / Linux / macOS / VPS) to execute jobs under
enforced resource limits.

**Status: MVP foundation — see [IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md)
for an honest per-feature breakdown (Implemented / Tested / Not verified).**

## What works today (verified by automated tests)

- Control plane (FastAPI, Python 3.12, async SQLAlchemy 2, SQLite default / PostgreSQL-ready)
- User auth (argon2 + JWT, RBAC admin/operator/user), agent keys, worker JWT auth
- Worker registry: registration, heartbeats, capability reports, health, quarantine
- Resource-aware scheduler: capability matching, 6 strategies, offline detection, retries,
  timeouts, cancellation, idempotency keys
- Real job execution via the worker agent (subprocess with RLIMIT_AS / RLIMIT_CPU /
  RLIMIT_NPROC, process-group kill, streamed logs, cancel watcher)
- Workspace manager: containment-checked filesystem ops, hardened archive extraction
  (Zip Slip, symlink, bomb protection), https-only git clone
- Storage router: local provider (streamed, checksummed) + GCS / HF adapters, resumable
  chunked upload sessions, direct-to-GCS resumable URLs for >10 GB objects
- MCP server (official SDK, Streamable HTTP) mounted at `/mcp` with 12 typed tools
- Structured JSON logs, Prometheus `/metrics`, audit trail with secret redaction
- 61 automated tests (51 backend incl. 4 live-server E2E + 10 worker unit tests), ruff clean

## Not yet implemented (do not assume otherwise)

- Next.js dashboard (backend APIs ready; no UI yet)
- Alembic migrations (currently `create_all`; deferred, see ADR-0004)
- Docker/Dagger runtime providers (interface exists at scheduler level; executor runs
  host-subprocess with limits — containers are Phase 4)
- OpenBao / OPA / Temporal / Nomad / Ray integrations (evaluated, deliberately deferred —
  [DEPENDENCY_MATRIX.md](docs/DEPENDENCY_MATRIX.md))
- GCS/HF live integration tests (adapters raise `NotConfigured` without credentials;
  no real bucket was available during development)

## Quick start (control plane)

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ./backend
export OMNIMCP_SECRET_KEY="$(openssl rand -hex 32)"
uvicorn omnimcp.main:app --host 127.0.0.1 --port 8000   # or: omnimcp-server
```

- health: `GET /healthz`, `readyz`, `metrics`
- first registered user becomes admin (`POST /api/v1/auth/register`)
- MCP endpoint: `http://127.0.0.1:8000/mcp` (Streamable HTTP)

## Quick start (worker)

```bash
pip install -e ./worker
omnimcp-worker register --server http://127.0.0.1:8000 --name my-worker
omnimcp-worker run --server http://127.0.0.1:8000
```

See [WORKER_SETUP.md](docs/WORKER_SETUP.md).

## Documentation index

| Document | Purpose |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Domains, data model, request flows |
| [IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md) | Verified vs not-verified feature matrix |
| [API_REFERENCE.md](docs/API_REFERENCE.md) | REST endpoints |
| [MCP_INTEGRATION.md](docs/MCP_INTEGRATION.md) | MCP tools + client compatibility matrix |
| [WORKER_SETUP.md](docs/WORKER_SETUP.md) | Install and run workers |
| [SCHEDULER_DESIGN.md](docs/SCHEDULER_DESIGN.md) | Job state machine, strategies |
| [STORAGE_DESIGN.md](docs/STORAGE_DESIGN.md) | Providers, large-upload path |
| [SECURITY.md](docs/SECURITY.md) | Security controls |
| [THREAT_MODEL.md](docs/THREAT_MODEL.md) | Adversaries, mitigations, residual risk |
| [DEPLOYMENT.md](docs/DEPLOYMENT.md) | VPS deployment, compose, backups |
| [OPERATIONS.md](docs/OPERATIONS.md) | Runbooks |
| [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Symptom → cause → fix |
| [TESTING.md](docs/TESTING.md) | How to run/extend the suites |
| [PERFORMANCE.md](docs/PERFORMANCE.md) | Measurement policy (no invented numbers) |
| [DEPENDENCY_MATRIX.md](docs/DEPENDENCY_MATRIX.md) | Evaluated OSS deps + licenses |
| [docs/adr/](docs/adr/) | Architecture decision records |
| [INFRASTRUCTURE_BASELINE.md](docs/INFRASTRUCTURE_BASELINE.md) | Verified/unknown facts about the target VPS (Phase 0) |
| [INFRASTRUCTURE_TOPOLOGY.md](docs/INFRASTRUCTURE_TOPOLOGY.md) | Proposed host-level trust zones (not deployed) |
| [HANDOFF.md](docs/HANDOFF.md) | Continuation record for the next agent |

## Layout

```
backend/    FastAPI control plane (omnimcp package) + tests
worker/     omnimcp-worker agent package + tests
docs/       documentation + ADRs
```
