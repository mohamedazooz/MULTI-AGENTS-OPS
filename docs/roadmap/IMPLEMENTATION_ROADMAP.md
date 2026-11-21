# Implementation Roadmap

Charter phases merged with the repository's own status (docs/ROADMAP.md). One branch + one PR per phase; nothing merges without owner approval. Where repo-internal phase numbers differ, the mapping is noted.

- [x] **Phase 0 - Audit and architecture** (this PR): forensic audit, target architecture, adoption matrix, tech-stack decisions, roadmap, acceptance criteria, dependency-matrix refresh. The repo's own Phase 0 work is validated and extended, not replaced.
- [ ] **Phase 1 - Core security repair** (next PR): AUD-001 bearer auth on /mcp (agent-key model first; RFC 9728/8707 metadata next), AUD-002 actor identity propagation + closing the ownerless-job hole, AUD-003 error sanitization, AUD-004 write caps, AUD-007 CI security scanning; security regression tests. Blocks everything else.
- [ ] **Phase 2 - Unified MCP registry and gateway**: tool/resource/prompt registry with two-stage discovery (names + short summaries, then lazy full schemas), per-tool permissions/risk classes/timeouts, MCP audit logs, agentgateway spike (TSD-004).
- [ ] **Phase 3 - Telegram bot**: framework decision (TSD-008), owner verification, commands (/status /agents /mcp /jobs /search /research /cancel /approve /deny /dashboard /settings), agent conversation sessions (never mixed between agents), job notifications and approvals, streaming updates.
- [ ] **Phase 4 - Telegram Mini App dashboard**: every control of charter section 5.4 over the already-shipped REST APIs; server-side initData validation; overview, agents, MCP, connectors, models, jobs, search, security, settings.
- [ ] **Phase 5 - Intelligence data gateway** (feeds into the repo's Phase 8 plugin work): deterministic hot path, parallel fan-out with per-provider limits and circuit breakers, L1/L2/L3 caches, dedup, evidence bundles with provenance, partial results, latency benchmarks (P50/P95/P99, no invented numbers).
- [ ] **Phase 6 - Model gateway and token optimization** (TSD-001/002): LiteLLM SDK, OpenRouter provider, free-model routing, budget enforcement, usage/token dashboards, zero-LLM execution counters.
- [ ] **Phase 7 - Research and knowledge engine**: Crawl4AI + Docling workers, document registry + ingestion, chunking, metadata filtering first; Qdrant only if justified (TSD-007).
- [ ] **Phase 8 - Agent runtime and worker isolation** (absorbs the repo-internal "Phase 4 runtime engine", the missing prerequisite): Docker/OCI runtime provider, git worktrees for coding agents, gVisor as opt-in capability, OpenHands adapter (TSD-005), worker recovery and execution policies.
- [ ] **Phase 9 - Cyber intelligence module**: ProjectDiscovery worker adapters, target allowlists and per-task authorization records, isolated recon workers, OpenCTI/MISP strictly off-VPS if ever.
- [ ] **Phase 10 - Production hardening**: Alembic in place (AUD-009), backups outside the VPS + restore drills, monitoring (already /metrics; Prometheus scraping and Telegram alerting), load tests, failure injection, runbooks, production acceptance report (charter scenarios A-H).

**Dependency-order changes vs the charter**: container isolation (charter Phase 8 content) may be pulled earlier if coding-agent work starts before the intelligence engine; Telegram (charter Phase 3) is safe to run before Phase 5 because the REST APIs it consumes are already shipped and tested.
