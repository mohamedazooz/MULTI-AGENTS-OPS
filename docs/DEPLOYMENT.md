# Deployment

Target: single 2 vCPU / 4 GB VPS. Minimal footprint: one control-plane process + SQLite
(dev) or PostgreSQL + the API. Nothing else is deployed by default (see ADR-0002 and
DEPENDENCY_MATRIX — no Redis/K8s/Kafka/Nomad/Temporal in the MVP).

## Option A — systemd (recommended smallest)

```bash
# on the VPS
python3.12 -m venv /opt/omnimcp/.venv
/opt/omnimcp/.venv/bin/pip install -e /srv/omnimcp/backend
cat >/etc/omnimcp.env <<'ENV'
OMNIMCP_ENV=production
OMNIMCP_SECRET_KEY=<openssl rand -hex 32>
OMNIMCP_DATABASE_URL=postgresql+asyncpg://omnimcp:***@127.0.0.1/omnimcp
OMNIMCP_HOST=127.0.0.1
OMNIMCP_PORT=8000
OMNIMCP_STORAGE_ROOT=/var/lib/omnimcp/storage
OMNIMCP_WORKSPACE_ROOT=/var/lib/omnimcp/workspaces
ENV
# then a unit file running: ExecStart=/opt/omnimcp/.venv/bin/omnimcp-server,
# EnvironmentFile=/etc/omnimcp.env, plus nginx/Caddy TLS in front (proxy to 127.0.0.1:8000)
```

## Option B — docker compose

```bash
cp .env.example .env   # edit OMNIMCP_SECRET_KEY etc.
docker compose up -d --build
```

`docker-compose.yml` ships the control plane only. Workers run on separate machines
(daemon sets / systemd / user-managed) — see WORKER_SETUP.md.

## TLS / network

- Terminate TLS at nginx/Caddy; app binds loopback only.
- Workers reach `https://<host>` over public TLS, or a WireGuard/Tailscale interface
  (preferred; keeps /mcp and admin APIs off the public internet).
- Until in-process MCP bearer auth lands (THREAT_MODEL #10), /mcp must not be public.

## Database

Dev default is SQLite. Production: PostgreSQL via `OMNIMCP_DATABASE_URL` (async driver).
Migrations: `create_all` for MVP (ADR-0004); Alembic before schema changes ship.

## Backups & restore

- SQLite/Postgres dump + `OMNIMCP_STORAGE_ROOT` + `OMNIMCP_WORKSPACE_ROOT` tarball to GCS
  (`kind=backup` routes to GCS automatically via the storage router).
- Restore: restore DB dump, untar roots, start service. Restore drills: Phase 10 (not run).

## Rollback

- Immutable releases: deploy to `/srv/omnimcp@<git-sha>`, symlink switch, restart unit.
- Compose: `docker compose down && docker compose up -d --build` from the previous tag.
