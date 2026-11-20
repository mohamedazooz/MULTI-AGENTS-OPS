# Architecture

## Shape

Modular monolith control plane + independently deployed worker agents. One Python process
hosts the REST API, the MCP server (mounted ASGI app at `/mcp`), the scheduler loop and the
registries. Workers are separate processes on separate machines that **pull** work.

```
                    ┌────────────────────────────── Control Plane (2 vCPU / 4 GB) ─────────┐
 Agents ──MCP HTTP──▶ /mcp (FastMCP, 12 tools) ──┐                                       │
 Agents ──REST──────▶ /api/v1 (FastAPI routers) ─┼─▶ domain services (jobs, workspaces,  │
 Dashboard (Phase 9)                             │   storage, workers, agents, …)       │
                                                 │        │ async SQLAlchemy 2          │
 Workers ──pull/heartbeat──▶ /api/v1/workers/me/*│        ▼                             │
                                                 │   SQLite (default) / PostgreSQL      │
                                                 │   local disk: workspaces + storage   │
                                                 └───────────────────────────────────────┘
 Workers ──execute subprocess jobs locally with rlimits (containers: Phase 4)
```

## Domains (implemented → module)

| Domain | Module | Notes |
|---|---|---|
| API Gateway | `main.py` (FastAPI app) | CORS, error handler, metrics middleware |
| MCP Gateway | `mcp_server.py` | official SDK FastMCP; tool auth = bearer on API side (MCP bearer token verification is [pending](IMPLEMENTATION_STATUS.md)) |
| Agent Registry | `api/agents.py`, `models.Agent` | per-agent random keys stored as sha256, shown once |
| API Connector Registry | `api/connectors.py`, `models.Connector` | mcp/http/openapi kinds, health probe via httpx |
| Worker Registry | `api/workers.py`, `models.Worker` | JWT worker tokens (30d) hashed at rest |
| Resource Discovery | `worker/omnimcp_worker/capabilities.py` | OS/arch/CPU/RAM/disk/GPU/runtimes detected on host |
| Scheduler | `jobs.py` (`pick_worker`, `tick`) | strategies: best_fit, least_loaded, capability, data_locality, cost_aware, priority |
| Job Manager | `jobs.py`, `api/jobs.py` | state machine, idempotency, events, logs |
| Workspace Manager | `workspaces.py`, `api/workspaces.py` | containment checks, archive hardening, git clone |
| Filesystem Service | `api/workspaces.py` (`/files`) | read/write/list/delete inside workspace root |
| Process/Build/Test Manager | worker `executor.py` (Phase 4 extensions pending) | bounded subprocess today |
| Storage Router | `storage.py` | provider ABC + local/GCS/HF; chunked + resumable sessions |
| AuthN/AuthZ | `security.py`, `deps.py` | argon2, JWT, revocation, RBAC deps |
| Audit | `audit.py`, `api/audit.py` | redaction of secret-like keys |
| Observability | `logging_setup.py`, `api/system.py` | JSON logs, Prometheus, support report |

Not-yet-built domains (runtime manager UI, plugin/SDK registry, secrets manager) are listed
in [IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md) with their planned phase.

## Data model (SQLAlchemy 2, async)

`User` (role, revocation_ts) · `Agent` (key_hash, scopes) · `Worker` (token_hash,
capabilities JSON, limits JSON, health, last_heartbeat) · `Job` (state, priority,
required_capabilities, min_ram/cpu, untrusted, idempotency_key, result, error,
attempts, timeout) · `JobLog` · `JobEvent` · `Workspace` · `StorageObject` ·
`UploadSession` · `Connector` · `AuditEvent`.

`Job.state` follows the 12-state machine in [SCHEDULER_DESIGN.md](docs/SCHEDULER_DESIGN.md).
`(owner_id, idempotency_key)` is unique-enforced; enqueue returns the existing job on repeat.

## Key flows

**Job submission → execution**
1. `POST /api/v1/jobs` → validate → `QUEUED` (idempotent).
2. Scheduler `tick` (1s loop): offline workers → requeue their jobs; expired jobs →
   `RETRYING`/`FAILED`; then dispatch by priority using `pick_worker` (capability +
   resource matching against the worker's last capability report).
3. Worker claims (`POST /workers/me/claim`) → job `ASSIGNED→RUNNING`.
4. Worker reports logs/status; final report → `SUCCEEDED/FAILED` (+ retry policy).

**Worker loss**: heartbeat absence > `worker_offline_after_seconds` (45s default) ⇒
worker offline, its `RUNNING` jobs requeued with attempt accounting.

**Large upload (>10 GB)**: `POST /storage/upload-sessions` with `provider=gcs` returns a
VPS-independent resumable upload URL; the client streams directly to GCS. The control plane
never buffers the full object. Local-provider uploads stream to disk in 1 MiB chunks with
SHA-256 computed inline ([STORAGE_DESIGN.md](docs/STORAGE_DESIGN.md)).

## Deliberate design decisions

See [ADR index](adr/): modular monolith (0001), SQLite-default DB (0002), worker pull model
(0003), Alembic deferred (0004), MCP SDK pinned to 1.x (0005).
