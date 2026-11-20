# API Reference

Base: `/api/v1`. Auth: `Authorization: Bearer <jwt|agent-key|worker-jwt>`.
Errors: `{"error": {"code": "...", "message": "..."}}`. Live OpenAPI at `/docs`.

## Auth
| Method | Path | Notes |
|---|---|---|
| POST | /auth/register | email+password; body `{email,password}`. Rate-limited. First user ⇒ admin |
| POST | /auth/login | `{email,password}` → `{access_token}` (12h) |
| GET | /auth/me | current user |
| POST | /auth/logout | revokes token |

## Agents
| POST /agents | `{name}` → agent record + `key` (plaintext shown once) |
| GET /agents · GET /agents/{id} | list/get (admin/operator) |
| POST /agents/{id}/enable · /disable | — |

## Workers
| POST /workers/register | `{name, capabilities, limits?, trusted?}` → `{worker_id, token}` (30d JWT). Rate-limited |
| GET /workers · GET /workers/{id} | list/get with capabilities, health |
| GET /workers/me | self view (worker JWT) |
| POST /workers/me/heartbeat | `{capabilities, active_jobs}` → 204 |
| POST /workers/me/claim | → `{job_id, job}` or `{job_id: null}` |
| POST /workers/me/jobs/{id}/logs | batch of `{stream, line, ts}` → 204 |
| POST /workers/me/jobs/{id}/status | `{success, result?, error?}` → final transition |
| POST /workers/me/jobs/{id}/cancel-check | → `{cancel_requested}` |
| POST /workers/{id}/enable · /disable | admin; disable drains/quarantines |

## Jobs
| POST /jobs | body: `{kind, payload, workspace_id?, priority?, required_capabilities?, required_os?, required_arch?, min_cpu?, min_ram_mb?, required_gpu_mb?, untrusted?, timeout_s?, max_retries?, idempotency_key?}` → 201 Job; idempotent on `(owner, idempotency_key)` |
| GET /jobs · GET /jobs/{id} | list/get |
| GET /jobs/{id}/logs · /events | logs and full transition history |
| POST /jobs/{id}/cancel | cancel queued (immediate) or running (CANCELLING) |
| POST /jobs/{id}/cancel-approval | admin approval gate |

**Job payload for `kind=exec`** (worker `parse_command`):
- `{"command": {"runtime": "python"|"node"|"shell", "script": "..."}}`
- `{"command": {"argv": ["prog", "arg", ...]}}` — explicit argv
- shell string only allowed where the worker runs with `--allow-shell`

Worker limits come from the job (`min_ram_mb` → `RLIMIT_AS`) and worker config.

## Workspaces
| POST /workspaces | `{name, description}` |
| GET /workspaces · /{id} | — |
| DELETE /workspaces/{id} | approval-gated (`?approve=true`) |
| GET /{id}/files | tree listing |
| GET /{id}/files/read?path= | text read (size-capped) |
| PUT /{id}/files | `{path, content}` write |
| DELETE /{id}/files?path= | delete |
| POST /{id}/archive | hardened zip/tar extraction |
| POST /{id}/clone | `{repo_url, branch?}` — https/git@ only |
| GET /{id}/inspect | project type detection |

## Connectors
| POST/GET /connectors | `{name, kind: mcp\|http\|openapi, endpoint_url, spec?, enabled}` |
| GET /connectors/{id} | — |
| POST /connectors/{id}/health | reachability probe via httpx |
| POST /connectors/{id}/enable · /disable | — |

## Storage
| POST | /storage/upload | single-shot multipart upload (size-capped) |
| POST | /storage/upload-sessions | `{filename, size, kind, sha256?, provider?}` → session (chunked) or `{upload_url}` direct-resumable for >10 GB to GCS |
| PUT | /storage/upload-sessions/{id} | chunk upload |
| POST | /storage/upload-sessions/{id}/finalize | sha256 verify → `StorageObject` |
| GET | /storage/objects · /{id} | — |
| GET | /storage/objects/{id}/download | streamed, range via provider `start` |
| DELETE | /storage/objects/{id} | — |
| GET | /storage/status | active providers + configuration state |

## Audit
| GET /audit | list (admin/operator), redacted details |

## System
| GET | /healthz · /readyz |
| GET | /metrics (Prometheus) |
| GET | /api/v1/system/support-report (operator+) |
| POST | /api/v1/system/scheduler/tick (admin) |
