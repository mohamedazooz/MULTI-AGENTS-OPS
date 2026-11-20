# ADR-0003: Workers pull (claim loop), control plane never dials workers

**Status:** Accepted · **Date:** 2026-11-20

## Context
Workers sit behind NAT/firewalls on heterogeneous OSes; inbound connections would need
tunnels and per-worker credentials on the control plane.

## Decision
Workers authenticate (30d JWT) and long-poll `POST /workers/me/claim`; heartbeats carry
capability updates; cancellation is worker-driven via cancel-check during execution.

## Consequences
- Only the worker needs outbound HTTPS.
- Job pickup latency = min(poll_interval, 2s default) — acceptable for MVP.
- No persistent server→worker channel (a future WebSocket is additive).
