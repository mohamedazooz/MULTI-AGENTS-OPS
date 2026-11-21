# Infrastructure Baseline — Phase 0

**Status:** `BLOCKED` (host-internal audit not executed — no authorized SSH credential)
**Audit window:** 2026-11-21 ~13:24–13:35 UTC (local client clock)
**Auditor:** OpenCode agent (read-only mode)
**Scope:** Existing Ubuntu VPS at `102.206.132.212` / Tailscale `100.90.28.70` (`sovereign-pc`)

---

## 0. Executive summary

Phase 0 was started as specified: read-only only, no packages installed, no firewall/SSH/proxy/Docker changes, no service restarts.

**The host-internal audit could not be performed.** Every command in the required audit list requires an authenticated shell, and authentication failed:

```
machsol@102.206.132.212: Permission denied (publickey,password).
```

The only SSH key available on the Windows client (`~/.ssh/id_ed25519`, comment `azoozz-vps`,
fingerprint `SHA256:OQGOTxTYwIhqLlx+LvErnWZz49oubxAPlXxo/uVP1IE`) is **not authorized** for `machsol`.
Its status relative to the key disclosed in the earlier conversation is **unconfirmed** — it must be
treated as potentially compromised and must not be reused as the long-term administrative key.

Consequently this document contains:

- ✅ **Verified externally** facts (reachability, ports, protocol fingerprints, repository state).
- ⚠️ **Unverified** facts (virtualization, CPU, RAM, disk, services, proxy config, toolchain, containers).
- ❌ **Blocked** items requiring credentials or provider-console access.

No claim in this document should be read as a completed host audit.

---

## 1. Method and constraints

### 1.1 Performed (read-only, no VPS mutation)

| Action | Result |
|---|---|
| Local tool discovery | OpenSSH 9.5p2 (Windows), `scp`, Tailscale CLI 1.104.7, PowerShell 7.7 |
| Tailnet status | Client `100.122.50.51`; target `sovereign-pc` `100.90.28.70` **online** |
| TCP reachability probes | Public and tailnet addresses, ports 22/80/443/3000/3001 |
| Unauthenticated HTTP header probes | Caddy redirect, nginx `401`/`400` fingerprints |
| TLS handshake attempts | Failed locally (Windows SChannel/LSA + server-side `InternalError`) |
| SSH auth attempt (BatchMode, key only) | **Permission denied** — no shell obtained |
| GitHub public API / raw file reads | Repository metadata, branch list, toolchain, CI workflows |
| Local filesystem key search | No other SSH private key found (only TLS/test certs, unrelated) |

### 1.2 Explicitly not performed

- No `sudo` command on the VPS (audit script was prepared but never executed against the host).
- No package installation, no `apt`, no `cargo`, no `systemctl`, no `ufw`, no Docker commands.
- No reverse-proxy config read or validation.
- No firewall, SSH, or service configuration change.
- No private key material was read, copied, or logged.

### 1.3 Evidence handling

Config dumps in the prepared audit script are passed through a `sed` redaction filter for
`password|passwd|secret|token|api_key|credential|authorization|private_key|seed|mnemonic|bearer`
before being written to local files. No secret-bearing output was produced in this phase.

---

## 2. Verified external observations

### 2.1 Port / service map

| Address | Port | State | Fingerprint |
|---|---|---|---|
| `102.206.132.212` | 22 | OPEN | SSH offering `publickey,password`; auth rejected |
| `102.206.132.212` | 80 | OPEN | `Server: Caddy`; `HTTP/1.1 308` → `https://102.206.132.212/` |
| `102.206.132.212` | 443 | OPEN (TCP) | TLS handshake failed from this client (see §2.3) |
| `102.206.132.212` | 3000 | CLOSED / FILTERED | was previously reported nginx+Basic Auth |
| `102.206.132.212` | 3001 | CLOSED / FILTERED | was previously reported nginx 400 |
| `100.90.28.70` | 22 | CLOSED / FILTERED (timeout) | **Tailnet SSH unreachable** |
| `100.90.28.70` | 80 | CLOSED / FILTERED | no HTTP |
| `100.90.28.70` | 443 | OPEN (TCP) | TLS handshake failed from this client |
| `100.90.28.70` | 3000 | OPEN | `nginx/1.28.3 (Ubuntu)`, `401 Unauthorized`, `WWW-Authenticate: Basic realm="Login"` |
| `100.90.28.70` | 3001 | OPEN | `nginx/1.28.3 (Ubuntu)`, `400 Bad Request` |

**Interpretation (requires host confirmation):** the port sets differ by interface. A likely
explanation is a host firewall permitting `22/80/443` on the public interface and `443/3000/3001`
only on the tailnet interface, or services bound selectively to the Tailscale IP. This must be
verified with `sudo ss -lntup`, `ip -brief address` and `sudo ufw status verbose` in the next
authorized session.

### 2.2 Previous observations vs. current

| Item | Earlier report | Current probe |
|---|---|---|
| Public SSH | OpenSSH 9.6p1 Ubuntu | Port open; version not re-verified (requires auth) |
| Caddy :80 | Present | Confirmed (`308` → HTTPS) |
| :3000 nginx Basic Auth | Public | Now tailnet-only (public filtered, tailnet `401`) |
| :3001 nginx 400 | Public | Now tailnet-only (public filtered, tailnet `400`) |
| Tailscale peer | Reachable | Reachable on tailnet; port 22 not reachable |

The change in public exposure of `3000/3001` is a **positive** hardening signal but is unverified.

### 2.3 TLS anomaly

Both `:443` endpoints accept TCP but the TLS handshake fails:

- Windows `curl`: `schannel: next InitializeSecurityContext failed: SEC_E_INTERNAL_ERROR (0x80090304)`
- .NET `SslStream`: remote party sent TLS alert `InternalError`
- SNI variants tried: IP, `sovereign-pc`, `localhost`; TLS 1.2 and 1.3 both failed.

This is may be a **client-side** Windows trust/SChannel defect, a **server-side** Caddy TLS policy
(e.g. client-cert requirement or unsupported signature algorithm), or an intervening TLS-inspection
layer. Reverse DNS for the public IP does not resolve (`PTR` NXDOMAIN), so no expected hostname
could be used for SNI. **Server TLS configuration remains unverified.**

### 2.4 Client-side environment

- Tailscale connected; client tailnet IP `100.122.50.51`.
- Other tailnet peers present (`aperture*`, `desktop-i66mlf7`, `iphone-12-pro`, etc.) — not relevant to this project but noted for access-control review.
- `known_hosts` contains only public-IP entries for the VPS and `github.com`.

---

## 3. Repository findings (public GitHub, read-only)

| Field | Value |
|---|---|
| Repository | `https://github.com/mohamedazooz/SOLANA_FLASHLOAN_ARBITUGE` (public, MIT) |
| Default branch | `main` |
| Latest observed commit | `a5f0c2068ddc1f76273bda7f4785fa26d88b4f30` (2026-11-21T13:29:57Z, verified merge of PR #112) |
| Earlier HEAD during session | `0fb477090831d9fbfdbc9ce2304745f94de9a8f1` — indicates active concurrent pushes |
| Remote size | ~8.3 MB reported by GitHub; large Rust workspace with many crates |
| Local git state | **Not inspected** — no authenticated shell, no local clone performed |

### 3.1 Toolchain constraints discovered from source

From `Cargo.toml`, `rust-toolchain.toml` and `.github/workflows/rust-ci.yml`:

- Rust **1.99.1** pinned exactly (`channel = "1.99.1"`, `profile = "minimal"`, components `rustfmt`, `clippy`).
- Edition **2024**, `rust-version = "1.99"` — cannot use a moving `stable` channel.
- Workspace members: `crates/*`, `programs/*`; `fuzz` excluded.
- CI gates (adapt commands, do not blindly use `--all-features`):
  - `cargo fmt --all --check`
  - `cargo check --workspace --all-targets`
  - `cargo check --workspace --all-targets --features arb-bot/extra-ingest,arb-ingest/extra-ingest,arb-bot/split-routing,arb-engine/split-routing,arb-sim/litesvm`
  - `cargo test --workspace --all-targets`
  - `cargo clippy --workspace --all-targets --features <same> -- -D warnings`
  - `cargo deny` (advisories/bans/sources/licenses) and `gitleaks` (full history)
  - Web app: Node **22**, `npm ci`, `npm run build` in `web/`
- CI explicitly warns that `--all-features` promotes quarantined, non-compiling legacy feature gates; do not use it as a blanket gate.

### 3.2 Deployment workflow risk (read from source, not executed)

`.github/workflows/deploy-vps.yml` is `workflow_dispatch` only and:

- Connects over SSH using `VPS_SSH_KEY` from GitHub Actions secrets.
- Runs `git fetch origin main && git reset --hard origin/main` in `$HOME/SOLANA_FLASHLOAN_ARBITUGE`.
- Builds `arb-bot --release --locked` (fat LTO, `codegen-units = 1`), then restarts `arb-bot.service` or starts it with `nohup`.

**Risk:** the hard reset discards uncommitted local changes and conflicts with the project rule
"never silently reset branches / never delete uncommitted user changes". Until the workspace design
separates the deploy checkout from the developer workspace, this workflow must be treated as
Level 3 (explicit approval only) and must not be triggered by agents.

- No secrets, `.env` contents, wallet keys or seed phrases were read from the repository.
- Repository already contains `config.toml`, `.env.example`, `artifacts/forensics/*` and audit docs;
  these require secret scanning before any workspace copy.

---

## 4. Unverified host facts (blocked)

Every item below is **UNKNOWN** because no shell was obtained. These are exactly the commands queued
in `infrastructure/scripts/phase0-audit.ps1` for the first authorized session.

| Requirement | Status | Command queued |
|---|---|---|
| Virtualization type | UNKNOWN | `systemd-detect-virt`, `ps -p 1`, `hostnamectl` |
| OS version | UNKNOWN (reported Ubuntu) | `/etc/os-release`, `uname -a` |
| CPU count / model / limits | UNKNOWN (reported 2 vCPU) | `nproc`, `lscpu`, `cat /sys/fs/cgroup/cpu.max` |
| RAM total / available | UNKNOWN (reported 4 GB) | `free -h`, `cat /sys/fs/cgroup/memory.max` |
| Disk size / filesystem / free | UNKNOWN (reported ~40 GB) | `df -hT`, `lsblk`, `/proc/mounts` |
| Swap / zram | UNKNOWN | `swapon --show`, `zramctl` |
| Network interfaces / routes | UNKNOWN | `ip -brief address`, `ip route` |
| Listening sockets / owners | UNKNOWN | `sudo ss -lntup` |
| Firewall rules | UNKNOWN | `sudo ufw status verbose` |
| Running services | UNKNOWN | `systemctl --type=service --state=running` |
| Docker availability / containers | UNKNOWN | `docker version`, `docker ps -a`, `docker compose version` |
| Caddy / Nginx configuration | UNKNOWN (only external fingerprints) | `sudo nginx -T`, `sudo caddy validate`, redacted config dump |
| Installed tool versions | UNKNOWN | `rustc/cargo/solana/anchor/node/python/git --version` |
| Existing repos on host | UNKNOWN | `find ~ -maxdepth 4 -type d -name .git` |
| Passwordless sudo | UNKNOWN | `sudo -n true` |

---

## 5. Resource budget (planning envelope — NOT measured)

**Do not treat these numbers as measured capacity.** They are conservative allocation targets for a
reported 2 vCPU / 4 GB / 40 GB host, pending the audit.

| Component | Envelope | Notes |
|---|---|---|
| OS + existing Caddy/nginx/SSH/Tailscale | unknown baseline | must be measured first |
| Cargo `check`/`test` | 2 vCPU, 1.5–3 GB peak | set `CARGO_BUILD_JOBS=2` |
| Cargo release build with fat LTO + `codegen-units=1` | up to ~3.5 GB peak | highest-risk operation; serialize jobs |
| code-server + rust-analyzer | 300–700 MB | launch only when needed; no desktop |
| Control-plane API + SQLite + dashboard | 200–400 MB | single small service |
| Telegram bot | <100 MB | |
| Agent/MCP workers | 200–500 MB | one concurrent job initially |
| Local LLM | **excluded** | use remote model APIs |

**Controls to apply after measurement:** cargo job limit, one build at a time, job timeouts,
log rotation, shared cargo target/cache directory, zram only if the host type permits it, swap only
after storage/provider review.

---

## 6. Security findings and recommendations

| # | Finding | Severity | Recommendation (requires approval where Level 3) |
|---|---|---|---|
| S1 | Disclosed private key considered compromised | Critical | Rotate; generate a fresh Ed25519 key on Windows; install only its **public** key on the VPS |
| S2 | Only local key is not authorized; no working admin path from this session | Critical | Install the new public key via provider console before any change; keep console session open |
| S3 | Public SSH exposes password authentication | High | After verifying new key login, disable password auth; add rate limiting/fail2ban; restrict source IPs |
| S4 | Tailnet port 22 unreachable | Medium | Decide intended admin path; if SSH should be tailnet-only, change firewall with approval and keep public fallback until verified |
| S5 | nginx `401` Basic Auth on tailnet :3000 | Medium | Confirm credential strength, enforce HTTPS, restrict to tailnet; never reuse SSH credentials |
| S6 | nginx :3001 returns `400` | Medium | Inspect vhost; likely missing/incorrect server_name or TLS termination mismatch |
| S7 | Caddy TLS handshake failure | Medium | Inspect Caddy config from host; verify certificate chain and TLS policy |
| S8 | `deploy-vps.yml` uses `git reset --hard` | High | Gate behind approval; isolate deploy checkout from developer workspace |
| S9 | Repo contains live/forensic artifacts and config templates | Medium | Run gitleaks locally before workspace copy; never place wallet secrets in workspace |
| S10 | Resource headroom unmeasured | Medium | No installs until `free -h`, `df -hT`, cgroup limits are known |
| S11 | Docker socket / unrestricted terminal APIs | Critical (design) | Never expose; bind control-plane APIs to loopback/tailnet only |

---

## 7. Recommended deployment architecture (proposed, not implemented)

```
Internet                 Tailnet (100.64.0.0/10)
   |                              |
   | 443 (Caddy, public app only) | 22 SSH*, 443, 3000, 3001
   |                              |
   +------------+-----------------+
                |
          [ Existing VPS ]
                |
   +------------+-------------+
   |                          |
CONTROL PLANE (loopback)   WORKSPACE (dedicated user, no sudo)
 API + SQLite              code-server (127.0.0.1/tailnet via Caddy)
 Agent manager             file manager restricted to /workspace
 Job runner (1 at a time)  git checkout + cargo target cache
 MCP gateway               docs / test-reports / logs
 Telegram bot              READ_ONLY|SIMULATION|DRY_RUN default
   |                          |
   +------------+-------------+
                |
        Audit log (append-only, redacted)
```

**Exposure rules**

- No Docker socket, shell API, code-server, dashboard, or MCP endpoint on the public interface.
- Admin UIs reachable only over Tailscale; public `:443` only for the existing public web app.
- Single reverse proxy (existing Caddy) terminates HTTPS; nginx :3000/:3001 stay tailnet-only.
- All control-plane services bind `127.0.0.1` and are reached through the proxy/tailnet.
- Least-privilege Unix user for agents; no root, no Docker group, no wallet keys.

**Data:** SQLite initially; append-only JSONL audit log; Git as source-of-record; backups exclude secrets.

---

## 8. Phase 1 implementation plan (awaiting approval)

> No system-level change is authorized in Phase 1 until the human confirms the items below.

1. **Key establishment (human action).**
   - Generate a **new** Ed25519 key on Windows, e.g. `ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_solana_hft -C "solana-hft-admin-2026-11-21"`.
   - Do **not** reuse `azoozz-vps` key or any key previously pasted into a conversation.
   - Via provider console, append **only the public key** to `~machsol/.ssh/authorized_keys` (mode `600`, dir `700`).
   - Keep the existing console/root session open throughout.

2. **Verify access (read-only).**
   - `ssh -i <new key> -o BatchMode=yes machsol@102.206.132.212 'date -Is; hostnamectl; id'`.
   - Re-test tailnet SSH once the firewall decision is made.
   - Only then run `infrastructure/scripts/phase0-audit.ps1` against the host and publish the completed baseline.

3. **Decide the admin path.**
   - Option A (recommended): SSH restricted to Tailscale, public 22 closed after verification.
   - Option B: public 22 retained with key-only auth + source-IP allowlist + fail2ban.
   - No SSH config or firewall edit until a working key session **and** a fallback console session are both confirmed.

4. **Hardening (Level 3, explicit approval each).**
   - Disable password authentication only after key login is proven.
   - Restrict nginx :3000/:3001 to tailnet, fix :3001, verify Caddy TLS.
   - Rotate any credential that may have been exposed with the old key.

5. **Recovery procedure to document before changes.**
   - Provider console/root session remains open during all SSH/firewall edits.
   - `sshd -t` validation before reload; never `systemctl restart ssh` blindly.
   - Rollback commands recorded in `docs/OPERATIONS.md`.
   - Break-glass key stored offline, not in the workspace or backups.

**Phase 1 acceptance criteria:** new key login verified; existing access retained until proven;
no public SSH exposure changed without approval; recovery plan documented.

---

## 9. Explicit unknowns

1. Virtualization type, provider, cgroup limits, real CPU/RAM/disk capacity.
2. Whether `machsol` has passwordless sudo and which services are currently active.
3. Exact firewall rules and why port sets differ between public and tailnet interfaces.
4. Whether Caddy failure is client-side or server-side.
5. Installed Rust/Solana/Anchor/Node/Python versions on the VPS.
6. Whether the expected repository is already cloned on the VPS, its branch, and uncommitted changes.
7. Whether GitHub Actions `VPS_SSH_KEY` corresponds to the compromised or a valid key.
8. Telegram bot token availability, administrator user IDs, and whether a bot already exists.
9. Whether the reported 2 vCPU / 4 GB / 40 GB figures are still accurate.

---

## 10. Phase 0 status

| Phase 0 deliverable | Status |
|---|---|
| Read-only VPS audit | BLOCKED — no authenticated shell |
| Infrastructure baseline | PARTIAL — external facts only (this document) |
| Port and service map | COMPLETE for probed ports; needs `ss -lntup` confirmation |
| Access diagnosis | COMPLETE — key rejected, tailnet SSH filtered |
| Resource budget | PROVISIONAL planning envelope only |
| Risk report | COMPLETE (§6) |
| No existing service disrupted | ✅ No VPS command executed |
| No configuration modified | ✅ No VPS file changed |

**Overall project status:** `NOT STARTED`
**Phase 0 status:** `BLOCKED` — awaiting new authorized SSH key / provider console access.
