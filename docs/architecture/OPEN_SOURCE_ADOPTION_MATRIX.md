# Open-Source Adoption Matrix

Classification per the charter: **Adopt (service)** / **Integrate (API)** / **Integrate (SDK)** / **Reuse code** / **Borrow architecture** / **Reject**. License, stars and activity verified via GitHub API on 2026-11-21 unless noted. Complements docs/DEPENDENCY_MATRIX.md, which already covers gateway/scheduler/secrets/storage candidates and is not duplicated here.

| Project | License (verified) | Stars | Decision | Rationale |
|---|---|---|---|---|
| MCP Python SDK (modelcontextprotocol/python-sdk) | MIT | 24.9k | Integrate (SDK, in-process) | already adopted and pinned 1.x via ADR-0005 |
| LiteLLM (BerriAI/litellm) | MIT core + proprietary enterprise/ dir | 63.6k | Integrate (SDK, in-process) | budgets, fallbacks, usage tracking; avoid the enterprise/ directory and the proxy service on a 4 GB VPS |
| OpenRouter | SaaS API | - | Integrate (API) | via LiteLLM provider or a thin httpx adapter; the platform policy layer owns free/paid rules |
| Hugging Face Hub / Inference | Apache-2.0 | - | Integrate (SDK) | already an adapter; inference stays optional and quota-aware |
| Crawl4AI (unclecode/crawl4ai) | Apache-2.0 | 87.6k | Integrate (SDK, worker) | best-fit crawler/extraction for the intelligence engine |
| Docling (docling-project/docling) | MIT | 70.8k | Integrate (SDK, worker) | document ingestion: PDF/DOCX/PPTX/XLSX/HTML |
| SearXNG (searxng/searxng) | AGPL-3.0 | 39.7k | Adopt (separate service) | run unmodified as an isolated meta-search service; never link into control-plane code |
| Firecrawl (firecrawl/firecrawl) | AGPL-3.0 | 205k | Optional (separate service or hosted API) | powerful but AGPL; isolated service boundary only |
| Qdrant (qdrant/qdrant) | Apache-2.0 | 35.6k | Defer | only if semantic retrieval is justified; PostgreSQL full-text search first |
| LangGraph (langchain-ai/langgraph) | MIT | 45.2k | Defer | job engine + scheduler cover simple orchestration |
| agentgateway (agentgateway/agentgateway) | Apache-2.0 | 6.3k | Defer to Phase 2 spike | v1.0 (Linux Foundation, 2026-03) and v1.4 support MCP spec 2026-07-28; candidate for transport auth in front of /mcp |
| ToolHive (stacklok/toolhive) | Apache-2.0 | 2.3k | Optional (Phase 8) | preferred hardened runner for MCP servers (per DEPENDENCY_MATRIX) |
| IBM ContextForge | Apache-2.0 | ~4.9k | Optional (Phase 8) | gateway provider adapter target |
| OpenHands (OpenHands/OpenHands) | MIT | 93.9k | Integrate (adapter) | org moved from All-Hands-AI; adapter + isolated worker + Docker isolation |
| OpenLinker-ai/openlinker-core | Apache-2.0 | 4 | Borrow architecture only | too immature to adopt; study its registry/token-permission contracts |
| nordinit/agent-hq | MIT | 1 | Borrow architecture only | task routing / worktree patterns only |
| Docker Engine (moby/moby) | Apache-2.0 | - | Adopt (worker-side isolation) | default container runtime; Phase 8 |
| gVisor (google/gvisor) | Apache-2.0 | - | Optional per-worker | sandbox capability flag for untrusted jobs |
| Firecracker (firecracker-microvm/firecracker) | Apache-2.0 | 38.1k | Reject (now) | microVMs not practical on the small VPS under Docker; revisit only with dedicated hosts |
| Nomad | BUSL-1.1 | - | Reject (licensing) | as in DEPENDENCY_MATRIX |
| Temporal | MIT | - | Defer | PostgreSQL-backed persistence first |
| OpenBao | MPL-2.0 | 9.1k | Optional (Phase 10+) | off the control-plane VPS |
| OpenCTI | Apache-2.0 CE / proprietary EE | 10.4k | Off-VPS, defer | dual licensing verified in LICENSE; heavy dependency footprint |
| MISP | AGPL-3.0 | 6.7k | Off-VPS, defer | separate service boundary only |
| nuclei / ProjectDiscovery tools | MIT / Apache per tool | 33.2k (nuclei) | Adopt (worker adapters) | isolated recon workers, authorized targets only |
| aiogram 3.x (aiogram/aiogram) | MIT | 5.9k | Preferred Telegram SDK | MIT license; decision finalized in Phase 3 per TSD-008 |
| python-telegram-bot | GPL-3.0 | 29.6k | Reject for import (license) | GPL-3.0 is incompatible with importing into this Apache-2.0 codebase; external reference only |

Stars are approximate at verification time; exact numbers live in the research brief this matrix was drawn from.
