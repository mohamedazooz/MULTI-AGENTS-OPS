# Build & Deployment Plan — Phase 5 / Phase E

**Status:** `DESIGN COMPLETE — CI PIPELINE NOT YET IMPLEMENTED OR EXECUTED`
**Date:** 2026-11-21 (UTC)
**Source repo:** `mohamedazooz/SOLANA_FLASHLOAN_ARBITUGE` (`main` = `a5f0c2068ddc1f76273bda7f4785fa26d88b4f30`)
**Raw evidence:** `C:\Users\azoozz\AppData\Local\Temp\opencode\phaseE\*` (rust-toolchain.toml, Cargo.toml, Cargo.lock, deny.toml, audit.toml, rustfmt.toml, `.github__workflows__rust-ci.yml`, `web__package.json`, `programs__arb-executor__Anchor.toml`, Dockerfile, deploy scripts, TREE.txt)

> No toolchain was installed on the VPS. No build, deploy, `git reset`, or service
> restart was performed. All content below is derived from raw repository files.

---

## 1. VPS capacity constraint

Measured in Phase 0/current mission: **2 vCPU, 3.8 GiB RAM total, ~1.7 GiB available,
4 GiB swap (2 GiB used), `/` 67 G with 32 G free.**

The release profile already requests `lto = "fat"`, `codegen-units = 1`, `panic = "abort"`
and `overflow-checks = true` — a combination that is memory- and CPU-expensive. Heavy
builds and LTO must therefore run in GitHub Actions, not on this VPS.

---

## 2. Exact version pins (from repository configuration)

| Setting | Value | Source |
|---|---|---|
| Rust channel | `1.99.1` | `rust-toolchain.toml:5` |
| Rust components | `rustfmt`, `clippy` | `rust-toolchain.toml:6` |
| Rust profile | `minimal` | `rust-toolchain.toml:7` |
| Edition | `2024` | `Cargo.toml:8`, `rustfmt.toml:1` |
| MSRV | `1.99` | `Cargo.toml:12` |
| Release profile | `opt-level=3`, `lto="fat"`, `codegen-units=1`, `panic="abort"`, `debug=false`, `overflow-checks=true` | `Cargo.toml:67-75` |
| Docker builder image | `rust:1.99.1-slim-bookworm` | `Dockerfile:9` |
| CI toolchain | `1.99.1` | `.github/workflows/rust-ci.yml:34` |
| Anchor CLI | `0.31.0` | `programs/arb-executor/Anchor.toml:3` |
| Solana CLI | `2.1.14` | `programs/arb-executor/Anchor.toml:4` |
| On-chain crate pins | `solana-address =2.7.0`, `solana-instruction =3.5.0`, `solana-account-info =3.1.1`, `solana-cpi =3.1.0`, `solana-program-error =3.0.1`, `solana-program-entrypoint =3.1.1` | `programs/arb-executor/Cargo.toml:12-18` |
| Lockfile | v4; `solana-client/rpc-client 4.3.2`, `solami 0.1.58`, `litesvm 0.18.2` | `Cargo.lock` |
| Node (CI/Docker) | `22` | `rust-ci.yml:116`, `Dockerfile:29` |
| Web stack | React 18.3.1 + Vite 6.4.6 (`^6.0.3`), TS 5.9.3, lockfileVersion 3; **no Next.js** | `web/package.json`, `web/package-lock.json` |

**Inconsistency to flag:** `Anchor.toml` declares Solana `2.1.14` but `Cargo.lock` resolves
Solana crates in the `4.x` line and the program pins `=3.x`/`=2.7.0` crates. There is no
single authoritative Solana CLI pin for the native build; the `arb-bot` binary build does
**not** require the Solana/Anchor CLIs. Node `20.20.2` on the VPS satisfies all declared
constraints, but CI/Docker intentionally use Node 22 — keep Node changes CI-only.

---

## 3. Existing CI commands (`rust-ci.yml`)

| Job | Command |
|---|---|
| Format | `cargo fmt --all --check` |
| Check | `cargo check --workspace --all-targets` |
| Feature matrix | `cargo check --workspace --all-targets --features arb-bot/extra-ingest,arb-ingest/extra-ingest,arb-bot/split-routing,arb-engine/split-routing,arb-sim/litesvm` |
| Tests | `cargo test --workspace --all-targets` |
| Clippy | `cargo clippy --workspace --all-targets --features <same 5> -- -D warnings` |
| Security | `cargo-deny check advisories bans sources licenses` (workspace + `webhook-service`) |
| Secrets | `gitleaks-action@v2` with `.gitleaks.toml` |
| Web | Node 22, `npm ci`, `npm run build` in `web/` |

**Explicit warning from `rust-ci.yml:47-50`:** use the five-feature matrix, **not**
`--all-features`; quarantined/legacy pump-raydium modules do not compile and must not be
promoted by a blanket gate. `scripts/verify-linux.sh` still uses `--all-features` clippy —
do **not** copy that script into the release pipeline. `deny.toml` ignores six advisories
(`RUSTSEC-2025-0141`, `RUSTSEC-2024-0437`, `RUSTSEC-2021-0139`, `RUSTSEC-2024-0388`,
`RUSTSEC-2024-0436`, `RUSTSEC-2025-0161`); `audit.toml` ignores only the first two.

---

## 4. Release pipeline design (to implement in a dedicated PR)

### 4.1 `.github/workflows/release.yml` — build once on Linux

Key steps:

1. Read Rust channel from `rust-toolchain.toml` (do not re-hardcode); Node fixed to `22`.
2. `dtolnay/rust-toolchain@master` with the pinned channel + `rustfmt,clippy`; `Swatinem/rust-cache@v2`.
3. `cargo fmt --all --check`; `cargo check --workspace --all-targets --locked`; the
   five-feature check; `cargo test --workspace --all-targets --locked`; clippy on the same
   five features with `-D warnings`.
4. `cargo-deny`, gitleaks, `npm ci && npm run build` in `web/` (including the currently
   uninvoked `npm run test:security`).
5. On a **Linux** runner (the workspace does not build on Windows — `yellowstone-grpc-client`
   uses `UnixStream`):
   ```bash
   cargo build --release --locked -p arb-bot --bin arb-bot --target x86_64-unknown-linux-gnu
   ```
   Do **not** add `RUSTFLAGS`: `[profile.release]` already supplies fat LTO/1 CGU.
6. Package `dist/bin/arb-bot`, inner `SHA256SUMS`, `BUILD_INFO.json` (commit/ref/rust/target/profile).
   Name the tarball `arb-bot-${{ github.sha }}-x86_64-unknown-linux-gnu.tar.gz` and write an
   outer `.sha256`.
7. `actions/attest@v4` for provenance with `id-token: write`, `attestations: write`.
8. Upload with `actions/upload-artifact@v7`, retention 30 days.

**Full YAML sketch is preserved in the evidence file**
`C:\Users\azoozz\AppData\Local\Temp\opencode\phaseE\release-workflow-sketch` derived during
Phase E; the essential commands above are the authoritative contract.

### 4.2 `.github/workflows/deploy.yml` — manual, gated, rollback-capable

- Trigger: `workflow_dispatch` with inputs `run_id`, `sha`, `rollback` (boolean).
- Environment: `deploy` (exists today with **no** protection rules — add required reviewers
  and restrict to `main` before enabling).
- Download the exact artifact by run ID; verify `sha256sum -c` and
  `gh attestation verify ... --source-digest <sha> --deny-self-hosted-runners`.
- SSH with `BatchMode=yes`, `StrictHostKeyChecking=yes`, a pinned `VPS_KNOWN_HOSTS` secret,
  and an environment-scoped `VPS_SSH_KEY`.
- Remote layout: immutable `/opt/solana-arb-bot/releases/<sha>/` plus atomic symlink swaps:
  `current` → selected release, and `bin/arb-bot` → `current/bin/arb-bot`.
- **Never** touch `config/`, `.env`, `data/`, or the kill-switch marker.
- Rollback: `ln -sfnT "$(cat .previous_current)" current` via atomic `mv -Tf`, or
  `deploy.yml` with `rollback=true`; no rebuild and no Git operation on the VPS.
- **Explicitly does not use `git reset --hard`** (present in the existing
  `.github/workflows/deploy-vps.yml:54`) and does not run `git fetch/pull/merge` on production.

### 4.3 Why this is safe for the current VPS

- No Rust/Solana/Anchor toolchain is installed on the VPS (verified), and none is needed.
- No LTO build consumes the 1.7 GiB available RAM.
- The existing unit path in `deploy/systemd/arb-bot.service`
  (`/opt/solana-arb-bot/bin/arb-bot --config /opt/solana-arb-bot/config/production.toml`)
  is preserved by the symlink. Note: the *active* unit found on the VPS uses the repo
  `target/release/arb-bot` path instead — confirm the target before any deploy PR.
- The current `deploy/production/deploy.sh` copies `config/*` into each release; the new
  scheme stops that behavior so deployment cannot overwrite operator-owned configuration.

---

## 5. Security constraints

1. Never print secret values; use `env:` and quoted heredocs; no `set -x`.
2. Move `VPS_HOST`, `VPS_PORT`, `VPS_USER`, `VPS_SSH_KEY` from repo scope into the `deploy`
   environment; add `VPS_KNOWN_HOSTS`.
3. Top-level `permissions: contents: read`; elevate per job; pin third-party GitHub Actions
   to full commit SHAs (currently floating `@v4`/`@v2`/`@master`).
4. Deploy identity: dedicated user with no `sudo`, `docker`, or `lxd`; narrow sudo only for
   `systemctl restart/is-active arb-bot.service` via a root-owned wrapper (Phase 2 §7).
5. Attestation verification must succeed before any SSH connection is attempted.

---

## 6. Verification required before this plan is considered executable

- [ ] Implement `release.yml` and `deploy.yml` in a dedicated branch/PR with tests.
- [ ] Run the release workflow from a pinned commit; capture the artifact SHA-256 and
      `BUILD_INFO.json` as reproducible evidence.
- [ ] Verify the artifact checksum and attestation on a runner.
- [ ] Confirm which systemd unit/binary path is active (`/opt/...` vs repo `target/release`).
- [ ] Create the `deploy` environment protection rules and `VPS_KNOWN_HOSTS`.
- [ ] Dry-run the deploy procedure against a non-production target.
- [ ] Obtain explicit approval for any production service restart.

**Final gate:** the CI build is **not yet reproducible** — design only. Phase 1 remains
`BLOCKED` until an actual CI run produces a verified artifact (see
`PHASE1_READINESS_REPORT.md`).
