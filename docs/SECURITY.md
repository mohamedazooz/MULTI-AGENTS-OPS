# Security

## Authentication

- Users: email + argon2id password hash; JWT (HS256, `OMNIMCP_SECRET_KEY`), 12h TTL.
- Revocation: `User.revocation_ts` vs token `iat` (logout bumps revocation).
- Agents: random 32-byte key, shown once, stored as SHA-256 hash, enable/disable.
- Workers: JWT worker token (30d TTL) stored as SHA-256 hash.
- Production boot fails fast without `OMNIMCP_SECRET_KEY`.

## Authorization

- RBAC: `admin` > `operator` > `user`, enforced via FastAPI deps
  (`require_admin`, `require_operator`, `owns_workspace`).
- Workspace operations are ownership-checked; workers may only touch their claimed job.
- `untrusted` jobs require sandbox-capable, admin-trusted workers (enforced server-side,
  tested by `test_untrusted_requires_sandbox`).

## Execution security (worker side)

- No shell on the control plane; execution happens only on workers behind claims.
- Subprocess limits: `RLIMIT_AS` (ram_mb), `RLIMIT_CPU`, `RLIMIT_NPROC`; whole process
  group killed on timeout/cancel (`os.setsid` + `killpg`).
- Shell runtime requires explicit `--allow-shell` operator override (trusted operators only).
- Container isolation (Docker/OCI/gVisor) is **not yet implemented** (Phase 4) — until then
  workers must only be operated on machines whose owners accept host-subprocess execution.
- No Docker socket or root shell is ever exposed to agents.

## Workspace / archive hardening (tested)

- Path containment on every file op (`safe_workspace_dir`, `safe_join`).
- Zip/tar: absolute-path and `..` traversal rejection, symlink/hardlink rejection,
  per-entry size cap, total-size bomb cap, entry-count cap, streamed extraction.
- git clone restricted to `https://` and `git@` URLs.

## Data protection

- Audit log redacts keys matching password/token/secret/authorization/api_key/env/credentials.
- Agent keys and worker tokens stored only as hashes; never logged.
- Upload integrity via SHA-256 mismatch rejection.
- Error responses follow `{"error":{"code","message"}}` without internals.

## Transport

- Deploy behind TLS (reverse proxy or WireGuard/Tailscale); see DEPLOYMENT.md.
- MCP transport security settings from the SDK (DNS-rebinding protection) are active.

## Secrets management

OpenBao adapter is planned; today secrets come from the environment only. Never place
credentials in prompts, repo files, or logs.
