# Operations Runbook

## Health checks

- `GET /healthz` — liveness (always cheap)
- `GET /readyz` — DB reachable
- `GET /metrics` — Prometheus (`omnimcp_http_request_latency_seconds`, request counters)

## Common procedures

**Inspect platform**: `GET /api/v1/system/support-report` — versions, config echo
(redacted), provider availability, crypto self-test. Auth: operator+.

**Inspect a failed job**:
1. `GET /api/v1/jobs/{id}` — state, error, attempts, worker.
2. `GET /api/v1/jobs/{id}/events` — full transition history with timestamps.
3. `GET /api/v1/jobs/{id}/logs` — streamed worker logs.

**Force scheduler pass**: `POST /api/v1/system/scheduler/tick` (admin) — useful when
running with `OMNIMCP_SCHEDULER_ENABLED=false` (e.g. external cron driving ticks).

**Drain a worker**: `POST /api/v1/workers/{id}/disable` — stops new claims; running jobs
continue. Quarantine (bad worker): same endpoint with quarantine flag in the workers API.

**Requeue stuck jobs**: disable the worker; scheduler marks it offline after the stale
threshold and requeues its RUNNING jobs automatically.

**Rotate secrets**: set new `OMNIMCP_SECRET_KEY` and restart (all JWTs invalidated —
users log in again, workers must re-register; schedule maintenance accordingly).

## Monitoring

Prometheus scrape `/metrics`. Alert suggestions (Phase 10 calibration): healthz flaps,
queue depth growth > N minutes, failed-job ratio, worker count drop.

## Logs

Structured JSON to stdout (`omnimcp.logging_setup`). Ship with journald → Loki/OTel later.
