# Scheduler Design

## Job state machine

```
CREATED → VALIDATING → QUEUED → ASSIGNED → RUNNING → SUCCEEDED
                          ▲          │          ├─→ FAILED (retry policy → RETRYING → QUEUED)
                          │          │          ├─→ CANCELLING → CANCELLED
                          │          │          └─→ EXPIRED (timeout)
                          └─ SCHEDULING
```

Implemented transitions live in `jobs.py::transition` (illegal transitions raise).
All transitions append `JobEvent` rows for observability.

- **Idempotency**: unique `(owner_id, idempotency_key)`; submit returns the existing job.
- **Retry**: attempts ≤ `max_retries` (default 2) → RETRYING → QUEUED; else FAILED.
- **Timeout**: `started_at + timeout > now` → retry-or-fail.
- **Worker loss**: heartbeat stale > `worker_offline_after_seconds` (45s) → worker offline,
  its RUNNING jobs requeued with attempts+1.
- **No double execution**: a job leaves QUEUED only via scheduler dispatch which sets
  ASSIGNED atomically in the tick transaction; claim is worker-bound.

## Worker selection

`pick_worker(job, workers, strategy)` filters by: health=online, compatible OS/arch,
RAM ≥ job.min_ram_mb, CPU ≥ job.min_cpu, required_capabilities ⊆ capabilities,
trusted/sandbox rule for untrusted jobs. Then orders by strategy:

| Strategy | Ordering |
|---|---|
| best_fit (default) | smallest slack over required resources |
| least_loaded | fewest active_jobs |
| capability | most matched capabilities |
| data_locality | workspace present on worker |
| cost_aware | cheapest (cost descriptor; placeholder weights today) |
| priority | queue priority order |

Scheduling runs in the 1s `tick` loop and via `POST /api/v1/system/scheduler/tick`.
Decisions are observable through job events (ASSIGNED/REQUEUED with worker ids).

## Non-goals / honesty

No shared-memory illusion: a job needing 8 GB RAM only schedules on workers whose last
report shows ≥ 8 GB — resources are per-worker, never summed across workers.
Nomad/Ray adapters: deferred — provider interface is the strategy function; see
DEPENDENCY_MATRIX (Nomad BUSL-1.1 rejected for now).
