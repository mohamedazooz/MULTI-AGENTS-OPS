# Infrastructure Topology — Measured current state and proposed target

**Status:** current state `VERIFIED`; target design `PROPOSED` (not implemented).
**Related:** `docs/INFRASTRUCTURE_BASELINE.md` (full measured evidence).

---

## 1. Measured current state

```
Internet
  :22   ──> host sshd (0.0.0.0)          password auth still offered
  :80   ──> roomote-caddy-1 (docker)      308 -> https
  :443  ──> roomote-caddy-1 (docker)      Let's Encrypt, SNI *.sslip.io (valid to 2027-02-01)
  :8080 ──> host nginx                    proxy -> https://127.0.0.1:443 (SNI sslip.io)

Tailnet (100.64.0.0/10)
  cloud-pc-tailscale container  ──> tailnet IP 100.90.28.70
  host :22 NOT reachable over tailnet (sidecar does not forward to host sshd)
  sovereign-cloud-pc container  ──> webtop desktop

Loopback only (host)
  redis-server :6379   postgresql 16-main :5432   kilo ACP :8765   arb-bot metrics :9100
Docker-internal
  roomote-docker-proxy-1 :2375 (Docker socket proxy) — never publish

Host firewall: UFW inactive. Provider/network controls + Docker publishing define exposure.
Privileges: machsol has passwordless sudo; member of sudo, docker, lxd.
Memory: 3.8 GiB total / 1.7 GiB available; 4 GiB swap with 2 GiB used.
```

### Existing container stacks (17 running)

| Stack | Contents |
|---|---|
| sovereign-cloud-pc | webtop desktop, tailscale sidecar |
| kilo-control | bot, worker, acp, redis, pgvector-pg16 |
| roomote | web, preview-proxy, bullmq, api, controller, caddy, docker-socket-proxy, redis, postgres-pg17, minio |

---

## 2. Proposed target (not deployed)

| Zone | Exposure | Intended contents |
|---|---|---|
| Internet | Public `:443` only | Existing public app behind the containerised Caddy |
| Tailnet | `100.64.0.0/10` | SSH (after approval), code-server/dashboard if capacity allows |
| Loopback | No direct network | Control-plane API, agent manager, MCP gateway, SQLite |
| Workspace | **New unprivileged user** (not `machsol`), no sudo/Docker/LXD | Separate git checkout, cargo cache, docs, logs, reports |
| External | APIs only | GitHub, remote model providers, Telegram Bot API |

Hard rules:

- Never expose the Docker socket proxy, shell API, MCP endpoint, dashboard or code-server to the
  public interface.
- Agents never run as `machsol` and never receive sudo/Docker-group privileges.
- All new control-plane services bind `127.0.0.1` and are reached via the proxy/tailnet.
- Keep the VPS repo at `/home/machsol/SOLANA_FLASHLOAN_ARBITUGE` untouched until its 184 local
  commits and untracked reports are backed up; use a separate checkout for agent work.
- `deploy-vps.yml` remains disabled/approval-gated until its `git reset --hard origin/main` is
  replaced with a non-destructive strategy.

---

## 3. Components and policy

```
Developer ── Telegram Bot API ──> control plane (loopback)
         └── Tailscale ──> [Caddy in container] ──> code-server / dashboard (loopback)

Control plane ──┬── permission engine / operation levels L1-L3
                ├── job runner (1 concurrent job; capacity decision pending)
                ├── task + audit records (SQLite, append-only redacted JSONL)
                └── MCP gateway ──> GitHub / docs / logs / build status (no Docker socket)

Workspace user ──> isolated checkout + shared cargo cache + test reports
```

- Operation levels: **L1** read-only (no approval), **L2** development inside approved repo,
  **L3** sensitive (explicit approval: packages, firewall, SSH, proxy, services, deletes, pushes,
  merges, deploys, transaction broadcast, credentials).
- Runtime default: `READ_ONLY / SIMULATION / DRY_RUN`. Mainnet broadcast disabled.
- Every task records: ID, agent, repo, branch, starting commit, changed files, commands, test
  results, errors, final commit/PR, approval status.

---

## 4. Data storage

- SQLite (WAL) for task/job/agent/audit metadata; append-only JSONL audit log with redaction.
- Git as source of record; backups exclude private keys, wallet seeds, RPC credentials and `.env`.
- Note: three PostgreSQL instances and two Redis instances already exist — reuse only after
  ownership review; prefer a dedicated SQLite file for new control-plane metadata.

---

## 5. Reverse proxy

- Caddy is containerised (`roomote-caddy-1`); host `/etc/caddy` does not exist. New public routes
  require a Level 3 change to that container's config/compose with service-owner approval.
- Host nginx is valid and has one vhost (`:8080` → Caddy). TLS 1.0/1.1 are enabled in the global
  nginx config; restrict TLS 1.2+ on any future nginx vhost.
- All new services bind loopback first; exposure is added only after approval.

---

## 6. Resource design (revised)

- One concurrent build; `CARGO_BUILD_JOBS=2` maximum on 2 vCPU.
- **No fat-LTO release build on this host as configured** — only 1.7 GiB RAM available vs ~3.5 GiB
  peak. Decide: bigger build host / cross-compile, approved container cleanup, or no local build.
- No local LLM; remote model APIs only. A desktop container already exists, so no new desktop.
- Shared cargo cache only if disk headroom (32 GiB free) is confirmed after measuring `target/`.

---

## 7. Decisions required before Phase 1 (all resolved as inputs, not blockers)

1. Admin path: tailnet-only SSH vs. public key-only with source allowlist.
2. Build-capacity option per §6.
3. Disposition of the `arb-bot` crash loop (diagnose first; no blind restart).
4. Confirmation that the 184 local commits and untracked reports on the VPS are preserved.
5. Whether the existing desktop/container stacks are in active use before any cleanup.
