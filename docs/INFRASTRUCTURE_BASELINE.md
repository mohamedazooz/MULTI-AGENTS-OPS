# Infrastructure Baseline — Phase 0

**Status:** `VERIFIED` — host-internal read-only audit executed successfully
**Audit window:** 2026-11-21 ~13:59–14:10 UTC
**Auditor:** OpenCode agent (read-only mode)
**Target:** Existing Ubuntu VPS `102.206.132.212` (Tailscale `100.90.28.70`, `sovereign-pc`)
**Access:** New Ed25519 key `machsol@102.206.132.212-ed25519`, fingerprint `SHA256:l0VaUrLdmnoe34vd5STIhEhlu5V5Wf+ZypDsN7fqM8I`
**Raw evidence:** `%TEMP%\opencode\phase0-raw-real2\` (`01-identity` … `13-sudo-check`, `remaining.txt`), plus TLS probe output

> **No system-level change was made.** No package installed, no service restarted, no
> firewall/SSH/proxy/Docker configuration changed, no repository file on the VPS modified.
> The only exception is the intended local side effect of key generation on Windows (new key
> pair under `D:\MY SSH KEY\machsol_102.206.132.212\`) and the local documentation in this PR.

---

## 0. Executive summary

Phase 0 is complete. The previously blocked host audit ran after a fresh Ed25519 key was
generated on Windows and installed on the VPS. Every previously unknown host fact is now
measured and recorded below.

Headline results:

1. **The host is a 2 vCPU / 3.8 GiB RAM Azure VM** (Ubuntu 24.04.4 LTS, Hyper-V). Disk has
   32 GiB free of 67 GiB. Swap (4 GiB file, 2 GiB already used) indicates the host is already
   under memory pressure.
2. **Only 1.7 GiB RAM is available.** A fat-LTO release build of `arb-bot` (peak ~3.5 GiB) cannot
   run on this host alongside the 17 existing containers without OOM/swap thrashing. This is the
   single most important planning constraint.
3. **`arb-bot.service` is enabled but crash-looping** (core dump, `ABRT`) due to a pre-existing
   SQLite migration error: `no such column: provenance` in `idx_outcomes_pnl`. `ExecStopPost`
   also fails (`status=203/EXEC`). This was **not caused by the audit** — it was in progress
   before the read-only checks ran. It was not restarted or modified.
4. **The on-VPS repo is 184 commits ahead and 2 behind its origin** with six untracked paths
   (including four forensic reports). The existing `deploy-vps.yml` runs
   `git reset --hard origin/main`, which would destroy that work. It must remain approval-gated.
5. **UFW is inactive**, passwordless `sudo` is enabled, and `machsol` is in `sudo`, `docker` and
   `lxd` groups. Public SSH offers password auth. The host relies on provider-level/network
   controls and Docker port publishing rather than a host firewall.
6. **Caddy runs inside Docker** (`roomote-caddy-1`, `caddy:2.10-alpine`), not on the host — which
   explains the earlier "no `/etc/caddy`" result and the TLS handshake anomaly. The certificate
   is valid; clients must use SNI `102.206.132.212.sslip.io`.
7. **Rust/Solana/Anchor toolchains are not installed on the host**; Node is v20.20.2 while the
   repo's web build requires Node 22. No build was attempted.

---

## 1. Method and constraints

### 1.1 Performed

| Action | Result |
|---|---|
| Local key inventory + new Ed25519 key verification | New key fingerprint `SHA256:l0VaUrL…` confirmed |
| Key-only SSH (BatchMode) | **Success** — `date`, `hostname`, `id`, `uptime -p` captured |
| Read-only audit script (`infrastructure/scripts/phase0-audit.ps1`) | 13 sections captured |
| Single-session fallback for remaining checks | tools, services, processes, nginx, Caddy, git, sudo, UFW, Docker |
| TLS handshake with correct SNI (`102.206.132.212.sslip.io`) | **Success** — valid Let's Encrypt cert |
| Secret redaction on config dumps | `password|passwd|secret|token|api_key|credential|authorization|private_key|seed|mnemonic|bearer` patterns redacted |

### 1.2 Two tooling defects found and fixed in the audit script

1. `-Host` collided with PowerShell's read-only automatic `$Host` variable → renamed to
   `-RemoteHost`.
2. Here-strings were sent to remote `bash` with CRLF endings, corrupting commands
   (`$'nproc\r': command not found`, `date: invalid argument 's\r'`) → commands are now
   normalized to LF before `ssh`. The first run was discarded; all facts below come from the
   corrected second run.

State: both script copies parse cleanly (385 tokens each). The rapid-connect attempts in the
second run caused temporary `Connection reset` on some sections; those were re-collected in one
SSH session in `remaining.txt`. No fact below is taken from the corrupted first run.

### 1.3 Explicitly not performed

- No `sudo` command that changes state; `sudo -n` was used only for read-only queries
  (`ss`, `ufw status`, `nginx -T`, `caddy validate`, `ls`, `cat`, `true`).
- No package installation, no `cargo`, no `systemctl` start/stop/restart, no Docker mutation,
  no `git fetch/reset/pull` on the VPS.
- No private key material was read, copied or logged. The new key lives only at
  `D:\MY SSH KEY\machsol_102.206.132.212\` on Windows; only its public half was installed.

---

## 2. Verified host facts

### 2.1 Identity and virtualization

| Field | Measured value |
|---|---|
| Hostname | `Mohamedibrahemazooz-1928` |
| OS | Ubuntu 24.04.4 LTS (`noble`) |
| Kernel | `Linux 7.0.0-1014-azure #14~24.04.1-Ubuntu SMP PREEMPT Fri Aug 14 17:35:51 UTC 2026 x86_64` |
| Virtualization | `microsoft` (Hyper-V), chassis `vm`, hardware model `Virtual Machine` |
| Firmware | Hyper-V UEFI Release v4.1 (2025-10-24) |
| `systemd-detect-virt` | `microsoft` |
| Machine ID | `22385f687a684758a480a0b1f2b432eb` |
| Uptime | ~55 days, 14 hours (`up 7 weeks, 6 days, 14 hours, 47 minutes`) |
| Load average | `0.58, 0.58, 0.56` |
| User | `uid=1000(machsol)` groups `sudo, docker, lxd, adm, cdrom, dip, plugdev, systemd-journal` |
| Passwordless sudo | **YES** (`sudo -n true` succeeded) |

### 2.2 CPU and memory

| Field | Measured value |
|---|---|
| CPU count | `nproc` = **2** |
| CPU model | Intel(R) Xeon(R) Gold 6138 CPU @ 2.00GHz |
| Topology | 1 socket, 1 core/socket, 2 threads/core; scaling 135%; max 2000 MHz |
| Cache | L1d 32 KiB, L1i 32 KiB, L2 1 MiB, L3 27.5 MiB |
| Hypervisor vendor | Microsoft; virtualization type `full` |
| RAM total | **3.8 GiB** |
| RAM used / free | 2.1 GiB / 254 MiB |
| Buff/cache / available | 1.8 GiB / **1.7 GiB available** |
| Swap | 4.0 GiB total, **2.0 GiB used** (`/swapfile`, priority -1) |
| zram | none |
| cgroup v1/v2 limits | `n/a` (no cgroup-level CPU/memory cap visible; limits are the VM's own) |

### 2.3 Disk and filesystems

| Mount | Type | Size | Used | Avail | Use% |
|---|---|---|---|---|---|
| `/` (`/dev/mapper/ubuntu--vg-ubuntu--lv`) | ext4 | 67G | 33G | **32G** | 51% |
| `/boot` (`/dev/sda2`) | ext4 | 1.7G | 311M | 1.3G | 20% |
| `/boot/efi` (`/dev/sda1`) | vfat | 952M | 6.2M | 945M | 1% |
| `/dev/shm` | tmpfs | 2.0G | 1.1M | 2.0G | 1% |
| `/run` | tmpfs | 392M | 5.8M | 386M | 2% |

- Physical disk `sda` = 70G; `sda3` (67.3G) is an LVM PV for `ubuntu--vg-ubuntu--lv`.
- Inodes on `/`: 4,415,488 total, 580,400 used, **14%**.
- 15 Docker network namespaces mounted under `/run/docker/netns/`.

### 2.4 Network, listening sockets and firewall

- `eth0`: `102.206.132.212/25`, default gateway `102.206.132.129` (public IP directly on VM).
- Docker bridges: `docker0` (172.17.0.1/16, **DOWN**), plus `br-*` on 172.18–172.22.0.0/16
  (all UP), with many veth pairs.
- **Tailscale CLI is not installed on the host** (`tailscale: command not found`); tailnet
  connectivity is provided by the `cloud-pc-tailscale` container.
- **UFW: `Status: inactive`.** There is no host-level firewall; exposure is controlled by the
  provider/network and by Docker port publishing.
- Key listeners (`sudo -n ss -lntup`, redacted):

| Port | Bind | Owner | Note |
|---|---|---|---|
| 22 | `0.0.0.0` + `[::]` | `sshd` | public SSH, password auth still offered |
| 80, 443 | `0.0.0.0` + `[::]` | `docker-proxy` | `roomote-caddy-1` publishes both |
| 8080 | `0.0.0.0` + `[::]` | host `nginx` | vhost `roomote-8080` → `https://127.0.0.1:443` with SNI `102.206.132.212.sslip.io` |
| 8765 | `127.0.0.1` | `docker-proxy` | `kilo-control-acp-1` (kilo ACP, loopback only) |
| 6379 | `127.0.0.1` / `[::1]` | `redis-server` | host Redis, loopback |
| 5432 | `127.0.0.1` | `postgres` | host PostgreSQL 16, loopback |
| 9100 | `127.0.0.1` | `arb-bot` | metrics endpoint, loopback |
| 35107 | `127.0.0.1` | `containerd` | internal |

- Earlier external probes observed no public 3000/3001; the current `ss` output shows no
  host-level 3000/3001 listener — those nginx fingerprints were on the tailnet side/container
  networking and remain best explained by the container stack.

### 2.5 TLS (resolved)

| SNI used | Result |
|---|---|
| `102.206.132.212.sslip.io` | **Success** — subject `CN=102.206.132.212.sslip.io`, issuer `CN=YE1, O=Let's Encrypt, C=US`, expires 2027-02-01 |
| `102.206.132.212` (IP) | Fail — certificate is SNI-specific; expected |

The earlier Windows SChannel error was a secondary client-side issue; the substantive cause was
connecting with the wrong SNI. Caddy is hosted in `roomote-caddy-1`; `caddy validate` and
`/etc/caddy/Caddyfile` do not exist on the host and are not required there.

### 2.6 Docker (17 running containers)

Docker Engine **29.1.3**, API 1.52, containerd 2.2.1, runc 1.3.4, Compose **2.40.3**.

| Stack | Containers |
|---|---|
| `sovereign-cloud-pc` | `webtop:ubuntu-xfce` (desktop in container), `cloud-pc-tailscale` (healthy) |
| `kilo-control` | `bot`, `worker`, `acp` (loopback :8765), `redis`, `pgvector:pg16` |
| `roomote` | `web`, `preview-proxy`, `bullmq`, `api`, `controller` (all `ghcr.io/roocodeinc/roomote-app:v1.19.7`), `caddy:2.10-alpine` (publishes 80/443), `docker-socket-proxy:v0.4.2` (internal 2375), `redis`, `postgresql:pgvector-0.8.1-pg17`, `minio` |

Security notes:
- A graphical desktop already exists **inside** `sovereign-cloud-pc` — the earlier
  "no desktop unless needed" assumption is outdated; it is already present.
- `roomote-docker-proxy-1` (tecnativa/docker-socket-proxy) exposes the Docker API internally;
  it must never be published to the public interface or made reachable by agents.
- Three different PostgreSQL instances exist (host 16-main, kilo pg16, roomote pg17) and two
  Redis instances — new services must not collide on ports or data directories.

### 2.7 Host services and tools

Running systemd services (30 loaded): `docker`, `containerd`, `nginx`, `ssh`, `fail2ban`,
`postgresql@16-main`, `redis-server`, `pm2-machsol`, `NetworkManager`, `systemd-*`, Hyper-V
daemons (`hv-kvp-daemon`, `hv-vss-daemon`), `cron`, `unattended-upgrades`, `udisks2`, etc.

`arb-bot.service` is **loaded/enabled but `activating (auto-restart)` with core dumps**:

- `ExecStart=/home/machsol/SOLANA_FLASHLOAN_ARBITUGE/target/release/arb-bot` → `code=dumped, signal=ABRT`
- Root cause in logs: `durable store unavailable; refusing to start (fail-closed: no in-memory
  fallback): SQLite store from DATABASE_URL unavailable … Failed to run migration: no such
  column: provenance` in `CREATE INDEX idx_outcomes_pnl ON outcomes(status, provenance, created_at)`
- `ExecStopPost=/home/machsol/SOLANA_FLASHLOAN_ARBITUGE/scripts/arb_bot_failure_alert.sh` → `status=203/EXEC`
- It is effectively a crash loop (repeated every few seconds). **Not restarted, not fixed,
  not stopped during this audit.** Remediation requires explicit approval.

Installed tool versions on the **host**:

| Tool | Version | Required by repo | Gap |
|---|---|---|---|
| rustc / cargo / rustfmt / clippy / rust-analyzer | **NOT INSTALLED** | Rust **1.99.1** (pinned), edition 2024 | Blocking |
| solana / anchor | **NOT INSTALLED** | Solana/Anchor programs | Blocking |
| node | v20.20.2 | Node **22** for `web/` build | Mismatch (nvm present under `sovereign-cloud-pc/cloud_pc_data/.nvm`) |
| npm | 10.8.2 | — | — |
| python3 | 3.12.3 | — | compatible with control plane |
| git | 2.43.0 | — | ok |
| curl | 8.5.0 (OpenSSL 3.0.13) | — | ok |
| jq | 1.7 | — | ok |

Top memory consumers (RSS): `next-server` 275 MB, `systemd-journald` 167 MB, three `node
dist/index.js` processes 140/129/114 MB, `dockerd` 92 MB, `minio` 76 MB, kilo ACP 68 MB.

### 2.8 Proxy configuration (redacted)

- Host nginx config is valid (`nginx -T` test successful). Only one extra vhost:
  `sites-enabled/roomote-8080`, listening on 8080 and proxying to
  `https://127.0.0.1:443` with `proxy_ssl_server_name on`,
  `proxy_ssl_name 102.206.132.212.sslip.io`, forwarding headers and WebSocket upgrade.
- `ssl_protocols TLSv1 TLSv1.1 TLSv1.2 TLSv1.3;` is the nginx default — TLS 1.0/1.1 are enabled
  in nginx (no vhost currently terminates TLS there; Caddy does).
- No `/etc/caddy` on host — Caddy config lives in `roomote-caddy-1`; host-side validation is not
  applicable. Container Caddy config was not read in this phase.

---

## 3. Repository state on the VPS (critical)

Scanned `find $HOME -maxdepth 4 -name .git`:

| Repo | State |
|---|---|
| `/home/machsol/SOLANA_FLASHLOAN_ARBITUGE` | branch `feat/meteora-dlmm-swap2-atomic-cpi`, **ahead 184 / behind 2** vs origin; HEAD `a8b8c4bb95fef505ae7a3e4ce6c551230ab042e7` |
| `/home/machsol/sovereign-cloud-pc/cloud_pc_data/.nvm` | detached HEAD `179d45050be0a71fd57591b0ed8aedf9b177ba10` |

Untracked files in the Solana repo (must be preserved):

```
.kilo/
reports/FINAL_FORENSIC_AUDIT.md
reports/FINAL_PRODUCTION_READINESS.md
reports/audit_fix_report_2026-11-13.md
reports/findings.json
target-docker/
```

**Do not run `deploy-vps.yml`.** Its `git reset --hard origin/main` would discard 184 local
commits and all six untracked paths. The repo is also on a feature branch, not `main`, and its
HEAD does not match the upstream `main` commit `a5f0c206…` observed earlier. Any future workspace
must use a separate checkout with explicit backup/approval.

### 3.1 Reported code-audit findings (from the separate audit stream, not re-verified here)

The independent audit stream reported, from `scripts/audit_codebase.py`:

- **70** hardcoded WSS endpoints (mostly tests/simulation in `arb-ingest`: Helius, Bitquery, Solami).
- **16** hardcoded localhost/port references (including metrics ports 9100, 9101, 8080, 9090).
- **56** unique public keys outside `arb-constants`.

These are recorded for completeness and were **not** independently reproduced by this
read-only host audit. Treat as leads for the next code-review phase.

---

## 4. Resource budget — now measured

Previously this was a planning envelope. Measured values replace it:

| Component | Measured / allowed | Consequence |
|---|---|---|
| CPU | 2 vCPU (Xeon Gold 6138, 135% scaling) | `CARGO_BUILD_JOBS=2` maximum; one build at a time |
| RAM total / available | 3.8 GiB / **1.7 GiB available** | No fat-LTO release build on this host as-is |
| Swap | 4 GiB, 2 GiB already used | Memory pressure is pre-existing; adding builds will worsen it |
| Disk free | 32 GiB on `/`, 14% inode use | Enough for docs/small caches; measure `target/` size before any build |
| Existing load | 17 containers, several Node processes, desktop in container | Baseline already consumes ~2.1 GiB |

**Decision required before any build:** choose one of —
(a) add RAM / use a larger build host and cross-compile the `arb-bot` binary,
(b) stop/decommission selected existing containers to free memory (explicit approval, service
owner confirmation required), or
(c) do not build on this host; use it only as a control-plane/light workspace host.

Do not assume the earlier ~3.5 GiB release-build envelope fits. It does not, with only
1.7 GiB available.

---

## 5. Security findings (updated with measured facts)

| # | Finding | Severity | Recommendation (approval where state-changing) |
|---|---|---|---|
| S1 | Disclosed key compromised; local `azoozz-vps` key rejected | Resolved | New key `SHA256:l0VaUrL…` installed and verified; old key must not be reused |
| S2 | Passwordless `sudo` for `machsol` | High | Confirm intended; audit `sudoers`; agents must never run as this user |
| S3 | `machsol` in `docker` + `lxd` groups | Critical | Docker group ≈ root; create a separate unprivileged workspace user |
| S4 | Public SSH offers password auth, UFW inactive | High | After fallback console confirmed: key-only auth, fail2ban already present; restrict source or move to tailnet |
| S5 | `roomote-docker-proxy-1` has Docker socket access | Critical | Never publish; never expose to agents/MCP |
| S6 | `arb-bot.service` crash-looping with core dumps | High | Root-cause the SQLite schema mismatch; do not restart blindly; approval needed |
| S7 | On-VPS repo 184 ahead / 2 behind with untracked reports | High | Never run `deploy-vps.yml`; back up before any git operation |
| S8 | nginx default config allows TLSv1/1.1 | Medium | Restrict to TLS 1.2+ on any new vhost (Caddy already modern) |
| S9 | Multiple Postgres/Redis instances and a desktop container | Medium | Inventory ownership before adding services; avoid port collisions |
| S10 | Only 1.7 GiB RAM available, 2 GiB swap used | High | No heavy build until capacity decision (§4) |
| S11 | Rust/Solana/Anchor absent; Node 20 vs required 22 | Medium | Toolchain installation is Level 3; use nvm if approved |
| S12 | Forensic reports and config templates untracked in repo | Medium | Secret-scan and back up before any workspace copy |

---

## 6. Deployment architecture — revised to measured reality

```
Internet           :443 (roomote-caddy-1, Let's Encrypt for *.sslip.io)
                    :80  (Caddy 308 -> HTTPS)
                    :22  (host sshd — candidate for restriction)
                    :8080 (host nginx -> Caddy, SNI sslip.io)
Tailnet             cloud-pc-tailscale container; host :22 currently NOT reachable via tailnet
                    (sovereign-cloud-pc desktop container)
Loopback only        host Redis :6379, Postgres :5432, kilo ACP :8765, arb-bot metrics :9100
Docker internal      docker-socket-proxy :2375 (NEVER publish)
Workspace (target)   new unprivileged user; separate checkout; shared cargo cache if approved
```

Adjustments from the earlier proposal:
- Caddy is **containerised**; new public routes mean editing the `roomote` Caddy config/compose,
  a Level 3 change with service-owner approval.
- A desktop already exists in a container; no new desktop is needed.
- SSH-over-tailnet currently fails because the tailscale sidecar does not forward to host
  `sshd` on :22 — a container networking decision, not a host firewall rule (UFW is inactive).

---

## 7. Phase 0 status

| Deliverable | Status |
|---|---|
| Read-only VPS audit | ✅ `VERIFIED` — 13 sections + single-session fallback |
| Virtualization / OS / kernel | ✅ Hyper-V VM, Ubuntu 24.04.4 LTS, Azure kernel |
| CPU / RAM / disk / swap / cgroups | ✅ measured (§2.2–2.3) |
| Listening sockets / firewall | ✅ measured; UFW inactive |
| Services / containers / processes | ✅ measured (§2.6–2.7) |
| Proxy config | ✅ host nginx read; Caddy located in container |
| Installed tool versions | ✅ measured (§2.7) |
| On-host repo state | ✅ measured, critical divergence found |
| TLS endpoint | ✅ verified with correct SNI |
| Access path | ✅ new key verified |
| Resource budget | ✅ measured, with build decision required |
| No existing service disrupted | ✅ no state-changing command executed |
| No configuration modified | ✅ no VPS file changed |

**Overall project status:** `NOT STARTED` (discovery only)
**Phase 0:** `VERIFIED` — ready for Phase 1 decisions, pending approval.

---

## 8. Phase 1 plan — awaiting explicit approval

No item below has been executed.

1. **Access hygiene (human + agent).**
   - Confirm the old key is retired from `authorized_keys` (human action).
   - Decide admin path: (A) restrict SSH to tailnet via the tailscale sidecar, or (B) keep public
     22 with key-only auth + source allowlist. Keep provider console available during changes.
2. **Preserve existing work (approval before git operations).**
   - Back up `/home/machsol/SOLANA_FLASHLOAN_ARBITUGE` including untracked reports.
   - Never invoke `deploy-vps.yml`; replace its `git reset --hard` with a non-destructive
     checkout strategy before any deployment is allowed.
3. **Triage `arb-bot` crash loop (diagnosis first).**
   - Read the migration source and DB schema to locate the `provenance` mismatch; propose a
     fix as a patch/PR. No service restart, no DB mutation without approval.
4. **Capacity decision (§4).** Select build host / memory strategy before installing toolchains.
5. **Only after 1–4:** install pinned Rust 1.99.1 and Node 22 via approved mechanism, create the
   unprivileged workspace user, and define minimal control-plane services on loopback.
6. **Document recovery/rollback in `docs/OPERATIONS.md`** before any SSH/firewall/service edit.
