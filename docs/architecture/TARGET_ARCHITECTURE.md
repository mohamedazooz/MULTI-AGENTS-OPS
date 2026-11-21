# Target Architecture

Maps the verified current state to the mission's logical layers. The current column reflects source inspection at commit 1375f5ee; see [INITIAL_REPOSITORY_AUDIT.md](../audit/INITIAL_REPOSITORY_AUDIT.md) for findings.

| Layer (mission) | Current state | Target state |
|---|---|---|
| 1. User interfaces | REST /api/v1 (tested), MCP at /mcp (12 tools, auth pending), worker CLI; no Telegram, no dashboard, no SSE | + Telegram Bot, Telegram Mini App dashboard (both on the same authenticated REST APIs), SSE/streaming for job progress; external MCP clients with OAuth per spec 2026-07-28 |
| 2. API/Agent gateway | In-app FastAPI middleware (CORS, errors, metrics), DNS-rebinding protection from MCP SDK | agentgateway integration spike in front of /mcp for transport auth (v1.4 is spec-current); keep the in-repo registry authoritative |
| 3. Core control plane | Modular monolith: registries (users/agents/workers/connectors), job engine with a 12-state machine, 6 scheduling strategies, audit, RBAC | Extend in place: approvals, policies, schedules, tool registry, evidence store; add Alembic migrations before Telegram tables land |
| 4. Intelligence gateway | Does not exist | New engine: request normalization, deterministic source discovery, bounded parallel fan-out (httpx + asyncio), L1 in-process / L2 Redis / L3 persistent caches, dedup (canonical URL + content hash + source), evidence bundles in compact/standard/detailed/raw modes; zero LLM calls on the deterministic path |
| 5. AI runtime | Worker subprocess executor only | Runtime adapter contract; OpenHands adapter on an isolated worker via Docker; custom lightweight agents; LangGraph only if stateful workflows are justified |
| 6. Model gateway | Does not exist | LiteLLM as an in-process SDK (not the proxy service) over OpenRouter/HF providers; policy layer enforces free-vs-paid routing, hard budget caps, per-agent model config, usage/token tracking; never a silent paid fallback |
| 7. Data & storage | SQLite default / PostgreSQL optional; local + GCS + HF adapters (GCS/HF unverified live); workspaces on disk | PostgreSQL as system of record in production; Redis for cache/coordination; Qdrant only if semantic retrieval is justified; S3-compatible object storage retained |

## Rationale notes

- **Reuse first**: Layers 1-3 are extensions of tested code, not rewrites (charter rule: do not rewrite working code without evidence).
- **Zero-LLM default** in Layer 4 keeps token consumption minimal and matches the charter's hot-path targets (cache-hit < 100 ms local, dispatch < 100 ms after validation; measured P50/P95/P99 later, no invented numbers).
- **Telegram layer** reuses the shipped REST APIs; the bot framework choice is recorded in TECH_STACK_DECISIONS.md (TSD-008) and decided in the Phase 3 PR.
- **Resource encumbrances**: the control plane stays within 2 vCPU/4 GB; SearXNG, OpenCTI, MISP, Firecrawl and Qdrant (if adopted) run as separate services, off-VPS when measurements demand it.
