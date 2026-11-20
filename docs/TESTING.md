# Testing

From the repo root with the shared venv (`.venv`):

```bash
# backend (51 tests): unit + API + archive-attack + storage + 4 live-server E2E
cd backend && ../.venv/bin/python -m pytest tests -q

# worker agent (10 tests): capabilities, command parsing, executor limits
cd worker && ../.venv/bin/python -m pytest tests -q

# lint
cd .. && .venv/bin/ruff check backend worker
```

## Layout

- `backend/tests/conftest.py` — isolated env per test run (temp dir, fresh sqlite file),
  ASGI client fixture, and a `live_server` fixture that boots a **real uvicorn** on a
  random port with the real scheduler (fast interval) — used by E2E tests.
- E2E: real HTTP server + real worker agent process loop over httpx + real MCP client
  (`streamablehttp_client`) — no ASGI shortcuts.
- `worker/tests/test_worker_agent.py` — executor limits (memory, timeout, missing
  binary), capability probe, strict command parsing.

## Conventions

- No network-external tests in CI (GCS/HF/git live calls intentionally excluded).
- Failures are fixed, never skipped silently; environment-blocked integrations are
  marked in IMPLEMENTATION_STATUS.md instead of faked.
- Coverage targets and load tests: Phase 10 (see PERFORMANCE.md policy).
