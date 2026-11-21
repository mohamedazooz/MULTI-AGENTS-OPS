# Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `OMNIMCP_SECRET_KEY required in production` at boot | env=production without secret | set `OMNIMCP_SECRET_KEY` |
| 401 after server restart | JWTs signed with a new/dev secret | log in again (dev); persist secret in prod |
| Worker claims 401/403 | token expired/revoked or worker disabled | re-register worker (`omnimcp-worker register`), re-enable in workers API |
| Job stuck QUEUED | no compatible worker (RAM/CPU/capabilities/OS) | `GET /api/v1/workers` to compare caps; lower requirements or adjust job |
| Job flips QUEUED→RETRYING→QUEUED | worker lost (heartbeat stale) | check worker process/logs; `worker_offline_after_seconds` default 45s |
| Job FAILED with timeout | exceeded `timeout_s` or worker exceeded limit | inspect events; backdate check: timeout enforced from `started_at` |
| MCP client: `Session terminated` | wrong URL/mount path | use `http(s)://host/mcp` (no trailing slash needed); FastMCP internal path is `/` |
| MCP tools error "workspace_not_found" | workspace dir absent | create via `workspace_create` or REST first |
| Storage download 404 but file exists | provider mismatch | `GET /api/v1/storage/status` lists active providers; object `provider` field shows owner |
| Upload finalize rejects with sha mismatch | client computed wrong hash | recompute SHA-256 of exact bytes uploaded |
| `NotConfigured` on storage status | GCS/HF env absent | set `OMNIMCP_GCS_BUCKET`/`OMNIMCP_HF_REPO` + credentials |
| rate limited (429) | register/login/worker-register burst | back off; limits are env-tunable (`OMNIMCP_*_RATE_LIMIT`) |
| Scheduler not running | `OMNIMCP_SCHEDULER_ENABLED=false` | enable or drive `POST /api/v1/system/scheduler/tick` externally |
