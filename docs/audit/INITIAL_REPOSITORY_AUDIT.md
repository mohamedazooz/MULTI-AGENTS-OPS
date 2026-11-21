# Initial Repository Forensic Audit

Audited commit: ```1375f5ee07e519aac190fdfafd52be6e611a0539``` (default branch ```vibe/omnimcp-foundation-5d6ade```).
Method: GitHub API inspection of source, tests, CI, Docker config and docs on 2026-11-21. No code was executed in the audit pass; test claims are checked against the repo's CI configuration (ruff + both suites) and test inventory, not re-run.

Companion documents: [ARCHITECTURE.md](../ARCHITECTURE.md) (current architecture, verified accurate), [DEPENDENCY_MATRIX.md](../DEPENDENCY_MATRIX.md), [TARGET_ARCHITECTURE.md](../architecture/TARGET_ARCHITECTURE.md), [OPEN_SOURCE_ADOPTION_MATRIX.md](../architecture/OPEN_SOURCE_ADOPTION_MATRIX.md), [TECH_STACK_DECISIONS.md](../architecture/TECH_STACK_DECISIONS.md), [IMPLEMENTATION_ROADMAP.md](../roadmap/IMPLEMENTATION_ROADMAP.md), [PHASE_ACCEPTANCE_CRITERIA.md](../roadmap/PHASE_ACCEPTANCE_CRITERIA.md).

## 1. Inventory (verified)

- **Layout**: ```backend/omnimcp``` control plane (16 modules: auth, registries, jobs engine, MCP server, storage router, workspaces, audit), ```worker/omnimcp_worker``` (agent, capabilities, executor, CLI), 16 docs + 5 ADRs, GitHub Actions CI (ruff + backend + worker suites).
- **Stack**: Python 3.12, FastAPI, async SQLAlchemy 2, Pydantic v2, argon2-cffi, PyJWT, official ```mcp``` SDK 1.x (FastMCP, Streamable HTTP at /mcp), prometheus-client; SQLite default / PostgreSQL optional extra. Worker deps: httpx + psutil only.
- **Tests declared**: 51 backend (incl. 4 live-server E2E) + 10 worker; present in ```backend/tests``` (7 files) and ```worker/tests``` (1 file), wired into CI.
- **Verified strengths**: argon2id + JWT with revocation; RBAC with ownership checks; rate limits on register/login/worker-register; audit trail with secret redaction; hardened archive extraction (Zip Slip, symlinks, entry/size caps, streamed); https-only git clone policy; server-side untrusted-requires-sandbox gate (```jobs.worker_compatible```); process-group kill + RLIMIT executor; >10 GB direct-to-GCS resumable upload path; honest NOT-verified sections in IMPLEMENTATION_STATUS.md.

## 2. Findings

Each finding lists: severity, evidence, affected files, root cause, proposed solution, tests required, dependencies, and whether it blocks production.

### AUD-001 - MCP endpoint has no authentication - Critical - BLOCKS PRODUCTION

- **Evidence**: all 12 tools in ```backend/omnimcp/mcp_server.py``` execute with no caller identity and call services with privileged defaults (```owner_id=None```); ```docs/THREAT_MODEL.md``` row 10 marks the mitigation "Pending"; ```docs/IMPLEMENTATION_STATUS.md``` marks MCP bearer-token enforcement red.
- **Affected files**: ```backend/omnimcp/mcp_server.py```, ```backend/omnimcp/main.py``` (mount point), ```backend/omnimcp/deps.py```.
- **Root cause**: FastMCP ASGI app mounted without any auth middleware; the only mitigation today is "deploy behind authenticated proxy/VPN", which the code does not enforce.
- **Proposed solution**: bearer-token verification on /mcp (reuse the Agent key model: hashed keys, enable/disable, audit), then RFC 9728 + RFC 8707 resource-server metadata per the MCP authorization spec revision 2026-07-28.
- **Tests required**: unauthenticated tool call rejected; invalid key rejected; valid agent key allowed and audited with caller identity.
- **Dependencies**: none. **Blocks production**: yes.

### AUD-002 - MCP tool calls bypass owner identity - High - BLOCKS PRODUCTION

- **Evidence**: ```mcp_server.job_submit``` calls ```jobs.enqueue(owner_id=None, ...)``` and ```job_cancel``` calls ```jobs.request_cancel(..., owner_id=None)```. In ```jobs.request_cancel``` the guard ```job.owner_id not in (None, owner_id)``` treats ownerless jobs as cancellable by any caller; jobs created via MCP have no owner at all, so RBAC/tenant protection never applies to them.
- **Affected files**: ```backend/omnimcp/mcp_server.py```, ```backend/omnimcp/jobs.py```.
- **Root cause**: no actor-identity propagation from the MCP transport into domain services; tools were written as internal trusted calls.
- **Proposed solution**: resolve the authenticated caller (user or agent) at the transport layer, thread it through every tool call, and refuse ownerless mutations except explicit system-internal paths.
- **Tests required**: agent A cannot cancel or inspect a job owned by agent B; MCP-submitted jobs persist ```owner_id```; unowned-job cancellation denied through the API.
- **Dependencies**: AUD-001. **Blocks production**: yes.

### AUD-003 - Internal exception details leak to MCP clients - Medium

- **Evidence**: ```_err()``` in ```mcp_server.py``` returns ```internal_error: {ExceptionType}: {message}``` for unexpected exceptions.
- **Affected files**: ```backend/omnimcp/mcp_server.py```.
- **Root cause**: blanket except used to serialize every error as a tool result.
- **Proposed solution**: log full details server-side with a correlation id; return a generic code to clients; keep structured ```OmnicpError``` codes.
- **Tests required**: unexpected exception produces no internal type/message in the tool response.
- **Dependencies**: none. **Blocks production**: no.

### AUD-004 - ```filesystem_write``` MCP tool has no size cap - Medium

- **Evidence**: ```mcp_server.filesystem_write``` calls ```p.write_text(content)``` unbounded, while the read path caps at 8 MiB and archives have explicit bomb caps.
- **Affected files**: ```backend/omnimcp/mcp_server.py```.
- **Root cause**: write path never received the same exhaustion treatment as ingestion paths.
- **Proposed solution**: enforce a maximum content size consistent with workspace limits before writing.
- **Tests required**: oversized write rejected without allocating the workspace.
- **Dependencies**: none. **Blocks production**: no.

### AUD-005 - Production compose runs SQLite and persists the DB at /app - Medium

- **Evidence**: ```docker-compose.yml``` sets ```OMNIMCP_ENV: production``` with no postgres service (config default stays SQLite) and mounts ```omnimcp-db:/app```, overlapping the application directory.
- **Affected files**: ```docker-compose.yml```.
- **Root cause**: compose written for the single-container MVP; THREAT_MODEL residual risk 4 documents the SQLite limitation.
- **Proposed solution**: add a resource-tested postgres service + ```OMNIMCP_DATABASE_URL```; move DB persistence to its own volume outside /app.
- **Tests required**: compose brings up the control plane against postgres; restart preserves data.
- **Dependencies**: AUD-009 for a clean upgrade path. **Blocks production**: no.

### AUD-006 - Rate limiting is per-process, in-memory - Medium

- **Evidence**: IMPLEMENTATION_STATUS describes the limiter as an "in-memory sliding window"; it resets on restart and does not survive multi-process deployments.
- **Affected files**: rate-limit implementation used by auth/worker-register endpoints.
- **Proposed solution**: Redis-backed limiter behind a small interface, or document the single-process constraint in THREAT_MODEL.
- **Tests required**: limit enforced across restart (if Redis-backed).
- **Dependencies**: Redis deployment decision. **Blocks production**: no.

### AUD-007 - No dependency vulnerability or secret scanning in CI - Medium

- **Evidence**: ```.github/workflows/ci.yml``` runs ruff + both test suites only.
- **Affected files**: ```.github/workflows/ci.yml```.
- **Proposed solution**: add pip-audit, secret scanning (gitleaks), and a license-inventory job feeding docs/legal/THIRD_PARTY_COMPONENTS.md.
- **Tests required**: CI red on a known-vulnerable pin and on a planted fake secret.
- **Dependencies**: none. **Blocks production**: no.

### AUD-008 - GCS / Hugging Face storage providers never verified live - Medium

- **Evidence**: IMPLEMENTATION_STATUS marks both adapters implemented but live integration blocked on credentials; adapters raise NotConfigured without configuration.
- **Proposed solution**: integration test against a real bucket before artifacts become load-bearing; keep the local provider as default.
- **Blocks production**: no (local provider tested).

### AUD-009 - No migrations (create_all only) - Medium

- **Evidence**: ADR-0004 defers Alembic; IMPLEMENTATION_STATUS marks it red.
- **Root cause**: acceptable in greenfield; a risk as soon as real data exists and schema churn begins.
- **Proposed solution**: introduce Alembic with a baseline migration in the next schema-changing PR (before Phase 3 adds Telegram/agent-session tables).
- **Blocks production**: no, but blocks long-lived deployments.

### AUD-010 - Worker capability reports are trust-on-registration - Low (accepted residual)

- **Evidence**: THREAT_MODEL residual risk 2: a compromised worker can overstate resources.
- **Proposed solution (later)**: scheduler-side admission probe when a job is claimed.
- **Blocks production**: no.

## 3. Disposition

- The charter's CURRENT_ARCHITECTURE deliverable already exists (docs/ARCHITECTURE.md, checked against source and found accurate), as do THREAT_MODEL and SECURITY docs. This PR adds the missing mandatory deliverables (TARGET_ARCHITECTURE, OPEN_SOURCE_ADOPTION_MATRIX, TECH_STACK_DECISIONS, IMPLEMENTATION_ROADMAP, PHASE_ACCEPTANCE_CRITERIA, this audit).
- All Critical/High findings (AUD-001, AUD-002) are scoped to the Phase 1 security PR; no other implementation work starts before they land.
- The charter-referenced prior projects (Kilo Telegram Orchestrator, Telegram AI Engineer MVP, Kilo Multi-Agent V2, GitHub Publisher) are not present in this repository; their location remains an open question before the Telegram layer is built (see roadmap Phase 3 notes).
