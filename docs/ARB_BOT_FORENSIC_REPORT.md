# ARB-BOT Forensic Report — Phase 3 / Phase D

**Status:** `ROOT CAUSE IDENTIFIED — FIX TESTED ON COPY — PRODUCTION UNTOUCHED`
**Date:** 2026-11-21 (UTC)
**Scope:** Read-only diagnosis of `arb-bot.service` crash loop on `102.206.132.212`
**Evidence:** `C:\Users\azoozz\AppData\Local\Temp\opencode\phaseD\batchA..batchE.out.txt`

> No production database, repository file, service state or script mode was changed.
> All destructive tests were executed on disposable copies under remote `/tmp/arb-bot-forensic-*`.

---

## 1. Executive summary

The crash loop is **not database corruption** and **not a Solana/RPC problem**. It is a
**migration-ordering defect combined with schema drift**:

1. The live database was created by an older `001_init.sql` whose `outcomes` table lacked
   the `provenance` column.
2. The current migration uses `CREATE TABLE IF NOT EXISTS outcomes(...)`, which is a **no-op**
   on that legacy table.
3. The same migration then executes
   `CREATE INDEX IF NOT EXISTS idx_outcomes_pnl ON outcomes(status, provenance, created_at)`,
   which fails with `no such column: provenance`.
4. The Rust self-healing function `SqliteStore::evolve_schema()` — which would add the column —
   runs **after** the batch migration and uses `?`, so the error short-circuits before repair
   is reached. The built-in fix is unreachable on exactly this failure.

A separate, independent defect causes systemd `203/EXEC`: the `ExecStopPost` alert script
exists but has mode `664` (no execute bit).

`arb-bot` has restarted **47,363 times** (`NRestarts`), is fail-closed, and is not trading.

---

## 2. Service evidence

Source: `systemctl cat/show arb-bot`, `journalctl -u arb-bot` (20,000-line window).

| Field | Value |
|---|---|
| Unit | `/etc/systemd/system/arb-bot.service` (no drop-ins found) |
| `ExecStart` | `/home/machsol/SOLANA_FLASHLOAN_ARBITUGE/target/release/arb-bot` |
| `ExecStop` | present in unit |
| `ExecStopPost` | `/home/machsol/SOLANA_FLASHLOAN_ARBITUGE/scripts/arb_bot_failure_alert.sh` → `status=203/EXEC` |
| `EnvironmentFile` | `/home/machsol/SOLANA_FLASHLOAN_ARBITUGE/.env` (path only; values never read) |
| Restart policy | `Restart=on-failure`, `RestartSec=5`, `StartLimitBurst=5/10s`, `StartLimitAction=none` |
| State | `ActiveState=activating`, `SubState=auto-restart`, `Result=core-dump` |
| Exit | `ExecMainStatus=6` / `ABRT` |
| `NRestarts` | **47,363** |
| Panic site | `crates/arb-bot/src/supervisor.rs:266` — `.expect("durable store unavailable; refusing to start (fail-closed: no in-memory fallback)")` |

Journal counts within the scanned window:

| Event | Count |
|---|---|
| `fail_closed` | 494 |
| `no_such_column_provenance` | 494 |
| `scheduled_restart` | 246 |
| `status203` | 247 |
| `main_dumped` | 247 |

Representative error from journal:

```
thread 'main' panicked at crates/arb-bot/src/supervisor.rs:266:10:
durable store unavailable; refusing to start (fail-closed: no in-memory fallback):
SQLite store from DATABASE_URL unavailable (fail-closed): internal error:
Failed to run migration: no such column: provenance
```

---

## 3. Database identification and integrity

`DATABASE_URL` scheme is `sqlite`; its value was **never printed**. The path was derived using
the application's own `sqlite_path_from_url()` logic
(`crates/arb-bot/src/supervisor.rs:162-175`) and confirmed to exist.

| DB | Path | Size | Rows in `outcomes` | Integrity |
|---|---|---|---|---|
| **Active** | `/home/machsol/SOLANA_FLASHLOAN_ARBITUGE/data/warm/sentinel_state.db` | 81,920 B | 13 | `ok` |
| Stale (unused) | `/home/machsol/SOLANA_FLASHLOAN_ARBITUGE/crates/arb-bot/data/warm/sentinel_state.db` | 40,960 B | 0 | `ok` |

Both copies: `user_version = 0`, `provenance` absent from `outcomes`, `idx_outcomes_pnl`
absent. No `-wal`/`-shm` files were present at snapshot time. `sqlite3` CLI is absent; all
checks used Python's `sqlite3` module (SQLite 3.45.1) on **copies only**.

A forensic backup of the active DB and all schema evidence was created under remote
`/tmp/arb-bot-forensic-20261121144620/` and `/tmp/arb-bot-forensic-20261121144822/`, and is
also covered by the encrypted full-repository backup (see `SOLANA_REPOSITORY_RECOVERY.md`).

---

## 4. Root cause — exact source locations

| File | Lines | Finding |
|---|---|---|
| `crates/arb-store/migrations/001_init.sql` | 12–19 | `CREATE TABLE IF NOT EXISTS outcomes(...)` — no-op on legacy DB |
| same | 17 | current definition includes `provenance TEXT,` — legacy DB does not |
| same | 20–21 | `CREATE INDEX IF NOT EXISTS idx_outcomes_pnl ON outcomes(status, provenance, created_at);` — **fails** |
| `crates/arb-store/src/lib.rs` | 13 | `INIT_SQL = include_str!("../migrations/001_init.sql")` |
| same | 138–140 | `execute_batch(INIT_SQL)` in first open path |
| same | 159–161 | `execute_batch(INIT_SQL)` in second open path |
| same | 172–223 | `evolve_schema()` definition |
| same | 196–211 | `has_provenance("provenance")` via `PRAGMA table_info(outcomes)` |
| same | 212–220 | `ALTER TABLE outcomes ADD COLUMN provenance TEXT` + backfill `'estimated'` |
| `crates/arb-store/migrations/001_postgres_init.sql` | 22–24 | Postgres path does it correctly (`ADD COLUMN IF NOT EXISTS` **before** index) |
| `crates/arb-bot/src/supervisor.rs` | 145–150 | `DATABASE_URL` sqlite branch → `SqliteStore::open` |
| same | 262–268 | `open_store(...).expect(...)` — panic site |

**Why self-healing never runs:** `execute_batch(INIT_SQL)?` precedes
`Self::evolve_schema(&conn)?` in both open paths. The failing index aborts the batch, so the
`?` returns early and the ALTER/backfill code is never executed.

---

## 5. Tested minimal migration (disposable copy only)

Applied to `/tmp/arb-bot-forensic-20261121144822/fix_test/fixed.db`:

```sql
ALTER TABLE outcomes ADD COLUMN provenance TEXT;
UPDATE outcomes SET provenance = 'estimated' WHERE provenance IS NULL;
CREATE INDEX IF NOT EXISTS idx_outcomes_pnl
    ON outcomes(status, provenance, created_at);
```

> SQLite has no `ADD COLUMN IF NOT EXISTS`. Guard using `PRAGMA table_info(outcomes)` as
> `evolve_schema()` already does, or run only when the column is absent.

### Verification output

```
APPLY_RESULT=OK
integrity: ok
outcomes_count: 13                     (unchanged)
table_info_outcomes: ... (5, 'provenance', 'TEXT', 0, None, 0)
index_list_outcomes: idx_outcomes_pnl, idx_outcomes_attempt_id
idx_outcomes_pnl_sql: CREATE INDEX idx_outcomes_pnl ON outcomes(status, provenance, created_at)
provenance_values: [('estimated', 13)]
APP_MIGRATION_001_INIT_REPLAY=OK        (full current migration replays cleanly afterwards)
integrity after replay: ok; count: 13
```

### Tested rollback (SQLite 3.45.1)

```sql
DROP INDEX IF EXISTS idx_outcomes_pnl;
ALTER TABLE outcomes DROP COLUMN provenance;
```

```
ROLLBACK_DROP_COLUMN=OK
integrity: ok
schema: original 5 columns, only idx_outcomes_attempt_id
```

Also verified: restoring the untouched `cp -a` copy returns the exact pre-change state
(preferred rollback method).

Production DB size/mtime were unchanged throughout.

---

## 6. ExecStopPost 203/EXEC

| Check | Result |
|---|---|
| Script path | `/home/machsol/SOLANA_FLASHLOAN_ARBITUGE/scripts/arb_bot_failure_alert.sh` — exists |
| Mode | `664` (`-rw-rw-r--`) — **no execute bit** |
| Shebang | `#!/usr/bin/env bash` |
| Interpreters | `/usr/bin/env` and `/bin/bash` both exist |
| `file` | Bourne-Again shell script, UTF-8 text |
| Mount | `rw`, not `noexec` |

Root cause: systemd cannot exec a non-executable file → `203/EXEC`. The script was **not**
executed during diagnosis (per safety rules). Minimal fix: `chmod 755 <script>` (requires
approval), after reviewing its contents for side effects.

---

## 7. Risk classification

| Item | Classification | Notes |
|---|---|---|
| Journal/unit/schema inspection | 1 — Read-only | executed |
| Copy DB to `/tmp` | 2 — Reversible | executed |
| Apply migration to disposable copy | 2 — Reversible | executed |
| Replay current migration on copy | 2 — Reversible | executed |
| Rollback on copy / restore copy | 2 — Reversible | executed |
| Backup active DB before any write | 2 — Reversible | **required before production change** |
| Apply migration to production DB | 3 — Potentially disruptive | NOT authorized; needs approval |
| `chmod +x` alert script | 2 — Reversible | NOT authorized; needs approval |
| `systemctl stop/start arb-bot` | 3 — Potentially disruptive | NOT authorized; needs approval |
| Rebuild/redeploy binary from code fix | 3 — Potentially disruptive | NOT authorized; needs approval |

---

## 8. Proposed code changes (not applied)

**Preferred durable fix** — change initialization order in `crates/arb-store/src/lib.rs`:

- Move `Self::evolve_schema(&conn)?` **before** `execute_batch(INIT_SQL)?` in **both** open
  paths (lines ~138–140 and ~159–161), so legacy schemas are upgraded before the index is
  created.
- Alternatively/additionally, add the guarded `ALTER TABLE ... ADD COLUMN provenance TEXT`
  plus backfill directly into `001_init.sql` **before** `idx_outcomes_pnl`, mirroring
  `001_postgres_init.sql:22–24`.

**Tests required in the dedicated PR:**

1. Unit/integration test: create a legacy-schema SQLite DB without `provenance`, call the
   open path, assert success and `PRAGMA table_info(outcomes)` contains `provenance`.
2. Idempotency test: open the same DB twice; assert no error and one `idx_outcomes_pnl`.
3. Data preservation test: insert a row before upgrade; assert 13→14 rows survive with
   `provenance='estimated'`.
4. Postgres parity test: assert `001_postgres_init.sql` path remains unchanged.
5. Migration rollback test on copies (as executed above).

---

## 9. Service recovery procedure (proposal — requires explicit approval)

1. Confirm fail-closed state (no live trading): inspect journal for `fail-closed` and verify
   kill-switch marker is present.
2. `systemctl stop arb-bot.service` to break the restart loop.
3. Fresh `cp -a` of the active DB (plus `-wal`/`-shm` if present) to an approved backup path;
   verify `PRAGMA integrity_check` on the backup.
4. Choose one:
   - **Data fix:** apply the tested SQL in §5 to the production DB; or
   - **Code fix (preferred):** apply the source patch, rebuild via approved CI artifact
     (see `BUILD_AND_DEPLOYMENT_PLAN.md`), then deploy.
5. `chmod 755` the alert script after content review.
6. Read-only verification: `integrity_check`, `table_info`, `index_list`, row count.
7. `systemctl start arb-bot.service`; monitor journal for `TRACE SUP 3: after store`,
   absence of `fail-closed`, and stable `NRestarts`.
8. Rollback: restore the pre-change DB copy, or execute §5 rollback SQL if no new `actual`
   provenance rows were written.

---

## 10. Could not verify

- `coredumpctl` is not installed — no core file path/backtrace; only systemd metadata.
- `RUST_BACKTRACE` is not set in the unit.
- `.env` values were not read; DB path was derived from code and confirmed to exist.
- The alert script was not executed; only metadata inspected.
- Journal counts are from a capped 20,000-line window; `NRestarts=47363` is cumulative.
- No `-wal`/`-shm` files at snapshot; WAL state at crash unverified.
- Stale zero-row DB was not individually fix-tested (identical schema).

**Final gate:** root cause identified ✅; SQLite repair tested on copy ✅; production untouched ✅;
service recovery not executed — awaiting approval.
