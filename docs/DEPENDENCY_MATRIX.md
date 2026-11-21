# Dependency Matrix — `docs/DEPENDENCY_MATRIX.md`

Evaluation of open-source candidates for OmniMCP. Data verified via GitHub API on 2026-11-20
(license, archived status, last push). Resource figures are documented upstream requirements or
reasonable estimates from official sizing guidance; all "Adopt" recommendations are installed in
this repository, everything heavier is explicitly deferred.

Legend: **Adopt** = used now · **Optional** = supported via adapter, off by default ·
**Defer** = revisit later phase · **Reject** = not suitable.

## MCP and API Integration

### IBM ContextForge (`IBM/mcp-context-forge`)
- Purpose: MCP Gateway/registry aggregating MCP + REST servers behind one endpoint.
- Architecture: FastAPI service, registry-backed, heartbeat/health federation.
- Language/SDKs: Python; REST + MCP (streamable HTTP, SSE, stdio).
- License: Apache-2.0 (verified). Maintenance: active (pushed 2026-11-20, ~4.9k★).
- Security model: auth to gateway, per-server enable/disable, keycloak-optional.
- RAM/CPU: ~512 MB–1 GB. Deployment complexity: moderate (needs DB).
- Integration: wrap behind `McpGatewayProvider` adapter.
- Limitations: another always-on service on the 4 GB VPS.
- Alternatives: ToolHive, Docker MCP Gateway, built-in registry.
- **Recommendation: Optional.** OmniMCP ships its own registry + gateway core (MVP must stay
  small); ContextForge is the primary target for the gateway provider adapter in Phase 8.

### Docker MCP Gateway (`docker/mcp-gateway`)
- Purpose: CLI/Docker-desktop centric MCP gateway with container isolation of MCP servers.
- License: MIT (verified). Active (~1.6k★).
- Security model: containerized MCP servers, catalogue allowlisting.
- Limitation: tied to Docker CLI plugin distribution; static catalogues.
- **Recommendation: Reject for control plane; Optional for local worker use.**

### ToolHive (`stacklok/toolhive`)
- Purpose: run MCP servers in hardened containers, proxy with auth.
- Architecture: Go binary/operator; registry support.
- License: Apache-2.0 (verified). Very active (~2.3k★).
- Security model: strong — containers, least-privilege profiles, RBAC.
- Integration: container runtime for MCP servers on worker nodes.
- **Recommendation: Optional (Phase 8) — preferred hardened runner for MCP servers.**

### Agentgateway (`agentgateway/agentgateway`)
- Purpose: L7 agent gateway (MCP + A2A), xDS/Dockerless, Rust + Go control plane.
- License: Apache-2.0 (verified). Active (~6.3k★).
- Limitation: newer project; richer networking features than the MVP needs.
- **Recommendation: Defer.** Re-evaluate when A2A or multi-tenant north-south gateway needs arise.

### Official MCP Servers (`modelcontextprotocol/servers`)
- Purpose: reference MCP servers (filesystem, git, fetch, ...).
- License: repo license detection = NOASSERTION (mixed per-package); treat per-package.
- **Recommendation: Adopt as agent-installable servers, not platform infrastructure.**

## Execution and Build Infrastructure

### Dagger (`dagger/dagger`)
- Purpose: reproducible pipeline-as-code build/test engine on containers.
- License: Apache-2.0 (verified). Very active (~16.6k★).
- RAM/CPU: engine ~1 GB; runs on workers, never on control plane.
- Integration: `BuildProvider` adapter (dagger python SDK), Phase 4.
- **Recommendation: Optional.** Worker builds via Docker exporter first; Dagger adapter next.

### OpenHands Sandbox Server (`OpenHands/sandbox-server`)
- Purpose: HTTP sandbox for executing agent code in_browser/docker.
- License: GitHub reports NOASSERTION (~9★, low activity).
- Limitation: tiny adoption, unverified license text.
- **Recommendation: Defer pending license verification.**

### Docker Engine (`moby/moby`)
- Purpose: default container isolation boundary for all execution.
- License: Apache-2.0 (verified). Extremely active.
- **Recommendation: Adopt** as the default isolation provider (worker-side).

### gVisor (`google/gvisor`)
- Purpose: userspace kernel sandbox for untrusted code.
- License: Apache-2.0 (verified). Active.
- Limitation: per-node kernel-level install; must be opt-in per worker.
- **Recommendation: Optional.** Declared per-worker capability `sandbox: gvisor`, enforced by
  scheduler for `untrusted=True` jobs.

## Distributed Scheduling and Compute

### Nomad (`hashicorp/nomad`)
- Purpose: cluster scheduler/orchestrator.
- License: **BUSL-1.1** (GitHub license = NOASSERTION; HashiCorp BSL since 1.14; converts to
  MPL for each version after 4 years). Not OSI open source.
- Security/limits: server + client agents ~256–512 MB each.
- **Recommendation: Defer.** Interface defined (`scheduler.providers.nomad`) but not adopted
  while the built-in scheduler suffices, also to keep licensing simple.

### Ray (`ray-project/ray`)
- Purpose: distributed Python compute (GCS + raylets), ML workloads.
- License: Apache-2.0 (verified). Very active.
- RAM/CPU: head node ≥ 1–2 GB; heavy for the 4 GB VPS.
- **Recommendation: Optional.** Run Ray head on dedicated worker nodes only; adapter in
  `scheduler.providers.ray`.

### Docker Swarm (`moby/moby` swarm mode)
- Purpose: simple multi-host container orchestration.
- License: Apache-2.0.
- Limitation: in maintenance-minimal mode; coarse resource model.
- **Recommendation: Reject** — our worker agent + built-in scheduler cover this with less waste.

## Workflow Orchestration

### Temporal (`temporalio/temporal`)
- Purpose: durable workflow execution.
- License: MIT (verified). Very active.
- RAM/CPU: 1+ dedicated GB (plus DB) — too heavy for the MVP VPS.
- **Recommendation: Defer.** PostgreSQL-backed job persistence implemented now; workflow
  checkpoints modeled so Temporal can slot in via `workflow.providers.temporal` later.

## Security and Secrets

### OpenBao (`openbao/openbao`)
- Purpose: Vault-compatible secrets management.
- License: MPL-2.0 (verified). Active (~9.1k★).
- Integration: `SecretsProvider` adapter; MVP ships encrypted-at-rest DB-backed provider.
- **Recommendation: Optional** (Phase 10+). Do not run OpenBao on the 4 GB control plane.

### Open Policy Agent (`open-policy-agent/opa`)
- Purpose: policy-as-code authorization (Rego sidecar).
- License: Apache-2.0 (verified). Very active.
- **Recommendation: Optional.** MVP uses built-in RBAC with policy-decision hook point.

## Networking and Observability

### Tailscale / WireGuard
- Purpose: private mesh connectivity control plane ↔ workers.
- License: Tailscale BSD-3 (client) / WireGuard kernel GPLv2.
- **Recommendation: Optional** — documented in DEPLOYMENT.md; mTLS tokens work without it.

### OpenTelemetry Collector (`open-telemetry/opentelemetry-collector`)
- License: Apache-2.0. **Recommendation: Optional.** Structured JSON logs + Prometheus metrics
  first (stdlib-based, zero extra RAM); OTLP export behind env flag.

### Prometheus
- License: Apache-2.0 (verified). **Recommendation: Optional** — we expose `/metrics`; scraping
  Prometheus is a deployment choice. Scrape ~64 MB, deployable off-VPS or small.

### Grafana
- License: **AGPL-3.0** (verified). Self-hosting allowed; avoid shipping Grafana-embedded
  derivative works.
- **Recommendation: Defer.** Dashboards provisioned later, deployed off control-plane VPS.

## Storage

### Google Cloud Storage SDK (`google-cloud-storage`)
- License: Apache-2.0. **Recommendation: Adopt** as provider adapter; NOT installed until
  credentials exist (import guarded), per no-heavy-unneeded-deps principle.

### Hugging Face Hub (`huggingface/huggingface_hub`)
- License: Apache-2.0 (verified). Xet-backed chunked uploads.
- **Recommendation: Adopt** as provider adapter for ML artifacts only (import guarded).

### Xet (`huggingface.co/docs/hub/xet`)
- Content-addressed chunk dedup backend behind `huggingface_hub`; no direct dependency.
- **Recommendation: Adopt transitively** via HF SDK; not interfaced directly.

## Summary decision table

| Project | License | RAM cost | Decision |
|---|---|---|---|
| Docker Engine | Apache-2.0 | worker-only | Adopt (workers) |
| MCP Python SDK | MIT | in-process | Adopt |
| FastAPI/SQLAlchemy/Alembic/Pydantic | MIT/BSD | in-process | Adopt |
| Dagger | Apache-2.0 | worker-only engine | Optional (Phase 4+) |
| ToolHive | Apache-2.0 | worker/host | Optional (Phase 8) |
| IBM ContextForge | Apache-2.0 | ~512 MB–1 GB | Optional adapter |
| Ray | Apache-2.0 | ≥1.5 GB | Optional, off-VPS |
| Nomad | **BUSL-1.1** | ≥512 MB | Defer (licensing) |
| Temporal | MIT | ≥1 GB | Defer |
| OpenBao | MPL-2.0 | ~512 MB | Optional |
| OPA | Apache-2.0 | ~64–256 MB | Optional |
| Prometheus | Apache-2.0 | ~64 MB | Optional (off-VPS ok) |
| Grafana | **AGPL-3.0** | ~256 MB | Defer |
| gVisor | Apache-2.0 | kernel-level | Optional per-worker |
| OpenHands sandbox-server | unverified | unknown | Defer |
| GCS / HF SDKs | Apache-2.0 | in-process | Adopt (guarded import) |
