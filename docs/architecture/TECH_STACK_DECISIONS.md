# Tech Stack Decisions

Incremental decisions from this research pass. Existing decisions live in docs/adr/ (ADR-0001 modular monolith, ADR-0002 SQLite-default, ADR-0003 worker pull model, ADR-0004 Alembic deferred, ADR-0005 MCP SDK pinned 1.x) and docs/DEPENDENCY_MATRIX.md.

- **TSD-001 Model gateway = LiteLLM SDK in-process.** Not the LiteLLM proxy service: the 2 vCPU/4 GB VPS cannot spare a resident proxy, and budgets/fallbacks/usage tracking are available in the SDK. Never import or depend on the proprietary enterprise/ directory.
- **TSD-002 Paid-model safety lives in our policy layer**, not in SDK defaults: free-model routing first, hard budget caps, per-agent model config, logged model+cost, explicit opt-in policy for any paid fallback.
- **TSD-003 AGPL boundary.** SearXNG (and optionally Firecrawl, MISP) run as separate unmodified services; no AGPL code is linked into the control plane or worker packages. Boundary recorded for docs/legal/THIRD_PARTY_COMPONENTS.md.
- **TSD-004 agentgateway = deferred spike, not adopted now.** The project is v1.0+ and supports MCP spec 2026-07-28, but the in-repo registry stays authoritative; re-evaluate in Phase 2 for transport-level auth in front of /mcp.
- **TSD-005 OpenHands via adapter on OpenHands/OpenHands.** The mission brief's All-Hands-AI URL is stale; integration uses its documented API on an isolated worker with Docker isolation (Phase 8).
- **TSD-006 OpenLinker-core and agent-hq are architecture references only** (4 and 1 GitHub stars): no code adoption, no service deployment.
- **TSD-007 Deterministic-first intelligence.** No LLM call for search, crawl, parse, dedup, cache or ranking; an LLM is used only for genuine synthesis/classification, per the charter's routing policy.
- **TSD-008 Telegram framework = aiogram 3.x preferred.** aiogram is MIT (verified 2026-11-21); python-telegram-bot is GPL-3.0, which is incompatible with importing into this Apache-2.0 codebase. Final confirmation in the Phase 3 PR after checking whether the charter-referenced existing Telegram implementations can be migrated.
