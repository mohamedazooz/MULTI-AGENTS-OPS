# Architecture — Proposed Design

**Status:** `PROPOSED` — not implemented. This document describes the target design, not the current state.
**Related:** `docs/INFRASTRUCTURE_BASELINE.md` (verified external facts and unknowns).

---

## 1. Trust zones

| Zone | Exposure | Contents |
|---|---|---|
| Internet | Public `:443` only | Existing public web app behind Caddy |
| Tailnet | `100.64.0.0/10` | SSH (after approval), code-server, dashboard, nginx `:3000/:3001` |
| Loopback | No direct network | Control-plane API, agent manager, MCP gateway, SQLite |
| Workspace | Dedicated Unix user, no sudo | Git checkouts, cargo cache, docs, logs, reports |
| External | APIs only | GitHub, remote model providers, Telegram Bot API |

No Docker socket, shell API, MCP endpoint, dashboard, or code-server port is exposed to the public internet.

## 2. Components

```
Developer ──┬── Telegram Bot API ──> Telegram control plane (loopback)
            └── Tailscale ──> Caddy ──┬──> code-server (loopback)
                                      ├──> dashboard (loopback)
                                      └──> restricted file manager (loopback)

Telegram control plane ──> control-plane API ──┬──> permission engine
                                               ├──> job runner (1 concurrent build)
                                               ├──> agent registry / task history
                                               ├──> audit log (append-only, redacted)
                                               └──> MCP gateway ──> GitHub / filesystem / build / docs / logs

Workspace user ──> git checkout + shared cargo target cache + test reports
```

## 3. Boundaries and policy

- Agents run as a non-root workspace user inside authorized project directories only.
- Every task record contains: task ID, agent, repository, branch, starting commit, modified files, commands, test results, errors, final commit/PR, approval status.
- Operation levels:
  - **L1 Read-only** — no approval: inspect files, git status, logs, metrics.
  - **L2 Development** — within approved repo: edit, branch, build, test, local commit, reports.
  - **L3 Sensitive** — explicit human approval: packages, firewall, SSH, proxy, service restarts, deletes, pushes, merges, deploys, transaction broadcast, credential changes.
- Runtime default: `READ_ONLY / SIMULATION / DRY_RUN`. Mainnet broadcast remains disabled.

## 4. Data storage

- **SQLite** for task/job/agent/audit metadata; WAL mode; local backups.
- **Append-only JSONL** audit log with secret redaction and rotation.
- **Git** as source of record; configuration backups; documentation backups.
- Backups exclude private keys, wallet seeds, RPC credentials and `.env` files.

## 5. Reverse proxy

- Existing Caddy remains the single HTTPS terminator for public traffic.
- Existing nginx `:3000/:3001` remain tailnet-only until inspected; no config edits in Phase 0.
- All new services bind `127.0.0.1`; Caddy adds private routes only after host audit and approval.

## 6. Resource design

- One concurrent build job; `CARGO_BUILD_JOBS` capped after measuring CPU.
- Shared cargo registry/target cache; job timeouts; log rotation.
- No local LLM; remote model APIs only.
- No graphical desktop unless a measured need is demonstrated.

## 7. Open decisions (blocked by Phase 0)

1. VM vs. container host — affects zram/swap, Docker support and backup strategy.
2. Actual CPU/RAM/disk — determines whether code-server, dashboard and worker coexist.
3. Admin path — tailnet-only SSH vs. public key-only with allowlist.
4. On-VPS repository location and its uncommitted state.
5. Whether `arb-bot.service` is currently active and must be preserved.
