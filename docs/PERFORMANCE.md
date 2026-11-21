# Performance

Policy: **no invented numbers.** Every published benchmark must include hardware,
configuration, dataset and the exact procedure. None published yet.

## What is measured today (instrumented, not benchmarked)

- `omnimcp_http_request_seconds` histogram (per method/path), `omnimcp_http_requests_total`,
  `omnimcp_jobs_dispatched_total`, `omnimcp_jobs_finished_total` (by state),
  `omnimcp_workers_online` and `omnimcp_queue_depth` gauges at `GET /metrics`.
- Job events carry timestamps end-to-end (created→started→finished), so scheduling
  latency and execution duration are queryable from `GET /jobs/{id}/events`.

## Measurement plan (Phase 10)

- API latency p50/p95/p99 under load (hardware: the target 2 vCPU/4 GB VPS).
- Scheduling latency: enqueue→ASSIGNED→RUNNING deltas.
- Upload throughput: local provider 1 MiB chunk path vs direct-to-GCS.
- Worker overhead: agent poll/poll cost vs job duration.
- Baselines to be recorded in this file with reproduction scripts.
