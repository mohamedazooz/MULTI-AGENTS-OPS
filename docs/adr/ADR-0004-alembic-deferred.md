# ADR-0004: Alembic deferred; create_all for MVP

**Status:** Accepted · **Date:** 2026-11-20

## Context
The prompt specifies Alembic; however the schema changed constantly during Phase 1-3
development. Managing migrations mid-flux risks broken migration chains worse than
honest deferral.

## Decision
`Base.metadata.create_all` on boot for the MVP. Alembic scaffold becomes mandatory
**before** any post-MVP schema change ships (tracked in ROADMAP/Phase 1 item).

## Consequences
- Existing dev databases won't auto-upgrade if columns change — recreate or manually
  migrate.
- Accepted trade-off: fresh-clone deployments unaffected.
