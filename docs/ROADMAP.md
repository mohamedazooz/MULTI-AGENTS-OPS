# Roadmap

Phases follow the master engineering prompt. Status markers reflect reality — see
[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md).

- [x] **Phase 0 — Discovery & research**: dependency matrix (20 projects evaluated with
      verified licenses, [DEPENDENCY_MATRIX.md](DEPENDENCY_MATRIX.md)); architecture + plan.
- [x] **Phase 1 — Foundation**: app boots, DB schema, auth+RBAC, logging, health, CI.
- [x] **Phase 2 — Control plane**: registries (agents, workers, connectors), job metadata,
      MCP server with 12 tools, permissions enforced.
- [x] **Phase 3 — Worker agent**: registration, heartbeat, capability discovery, pull
      execution, logs, cancellation, reconnection backoff, offline detection.
- [ ] **Phase 4 — Runtime engine**: Docker/OCI provider behind a runtime adapter, Dagger
      for reproducible builds, gVisor evaluation for untrusted code. *Next up.*
- [x] **Phase 5 — Workspace & storage**: completed for the local provider; GCS/HF adapters
      implemented but live verification blocked on credentials (see status doc).
- [x] **Phase 6 — Distributed scheduling (built-in)**: strategies, capability matching,
      decisions observable via job events. Nomad/Ray adapters deferred.
- [x] **Phase 7 — Workflow reliability**: idempotency, retry, cancellation, recovery tested.
- [ ] **Phase 8 — Plugins & external services**: connector gateway adapters, plugin
      lifecycle, client compatibility matrix (started in [MCP_INTEGRATION.md](MCP_INTEGRATION.md)).
- [ ] **Phase 9 — Dashboard**: Next.js over the shipped REST APIs; every control wired.
- [ ] **Phase 10 — Production hardening**: load tests, failure injection, backup/restore
      drills, production readiness report.
