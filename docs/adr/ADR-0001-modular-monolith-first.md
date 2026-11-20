# ADR-0001: Modular monolith first, workers isolated

**Status:** Accepted · **Date:** 2026-11-20

## Context
Target host is a 2 vCPU / 4 GB VPS. 25 domains are required but microservices would
multiply operational cost with no benefit at this scale.

## Decision
One Python process runs API + MCP + scheduler + registries with clear module boundaries
(`omnimcp/api/*` routers over `omnimcp/*` domain services). Workers are separate
deployables from day one (pull model).

## Consequences
- No inter-service latency/auth to maintain; refactor points are module edges.
- Domain extraction into services later requires only swapping module calls for transport.
- Scheduler runs in-process (asyncio task); a futuristic external scheduler would replace
  `tick()` behind the same contract (or cron-driven `/system/scheduler/tick`).
