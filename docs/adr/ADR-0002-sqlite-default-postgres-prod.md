# ADR-0002: SQLite (aiosqlite) default, PostgreSQL for production

**Status:** Accepted · **Date:** 2026-11-20

## Context
Zero-config dev/test bootstrapping vs production durability. SQL mostly vendor-neutral.

## Decision
`OMNIMCP_DATABASE_URL` defaults to `sqlite+aiosqlite:///./omnimcp.db`; production sets
`postgresql+asyncpg://...`. All queries use plain SQLAlchemy 2 constructs compatible with
both async dialects.

## Consequences
- Tests get isolated file DBs for free; CI needs no services.
- SQLite serializes writes — never recommended for multi-writer prod load.
- asyncpg is a deliberate prod dependency choice (not installed by default).
