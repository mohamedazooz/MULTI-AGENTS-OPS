# Phase Acceptance Criteria

A phase is complete only when every criterion is demonstrably met (test, log, or observed behavior). Fabricated results are a rejection (charter rule 18). Scenario letters reference charter section 26.

## Phase 0 (this PR)
- All mandatory charter documents exist and reference verified evidence (commit SHA, dates).
- Every finding lists severity, evidence, affected files, root cause, solution, tests, dependencies, production impact.
- DEPENDENCY_MATRIX claims cross-checked; stale entries flagged (agentgateway maturity).
- CI green on this PR.

## Phase 1 - Security repair
- Unauthenticated and invalid-key /mcp calls are rejected (Scenario G items 1-2 for the MCP path).
- MCP-submitted jobs carry a real owner; cross-owner job access/cancel is denied (Scenario G item 3).
- No internal exception details in tool responses.
- ```filesystem_write``` enforces a size cap.
- CI includes pip-audit + secret scanning (AUD-007).
- Full test suite green; baseline counts (61) must match reality.

## Phase 2 - MCP registry and gateway
- /mcp clients discover tools in two stages; full schemas are never embedded in prompts.
- Per-tool permission and risk classification enforced server-side.
- MCP audit log records caller, tool, and approval-relevant actions.
- agentgateway spike documented (adopt or defer, with evidence).

## Phase 3 - Telegram bot
- Only the verified owner's Telegram identity is accepted; everyone else rejected (Scenario G).
- Conversations are isolated per agent with persistent session ids; switching agents never bleeds context.
- Streaming job updates and approval prompts work; ```/cancel``` stops a running job.
- initData is never trusted from the browser alone.

## Phase 4 - Mini App dashboard
- All charter 5.4 sections reachable and wired to the shipped APIs; no duplicated business logic between bot and dashboard.
- Dashboard access restricted to the owner; sensitive actions audited.
- Works in Telegram (Mini Apps) and a normal browser.

## Phase 5 - Intelligence gateway
- Scenarios C and D pass: parallel collection with zero LLM calls, results cached and retrievable later, compact evidence bundles with provenance.
- Partial results are returned when a source fails; one source's failure never discards other sources' results.
- Latency targets measured (not claimed) and recorded in docs/PERFORMANCE.md.

## Phase 6 - Model gateway
- Scenario E passes: budget enforcement, no silent paid fallback, accurate usage reporting, disable-inference option.
- Zero-LLM paths counted and visible in the dashboard.

## Phase 7 - Research and knowledge engine
- Multi-format ingestion (PDF/DOCX/PPTX/XLSX/HTML/MD) with citations retained; research history retrievable.
- Semantic index built only if its justification write-up was accepted.

## Phase 8 - Runtime and isolation
- Untrusted jobs never execute as host-subprocess; the Docker/OCI provider is enforced by the scheduler.
- Coding agents work in isolated worktrees; OpenHands runs behind the adapter with cancellation and timeout.
- Scenario H simulations pass (worker loss, Redis interruption, DB restart, queue backlog).

## Phase 9 - Cyber module
- Every recon tool run is tied to an authorization record; out-of-scope targets are refused; intrusive operations require approval (Scenario G).
- Nothing security-testing-related executes on the control plane.

## Phase 10 - Hardening
- Restore (not just backup) tested from off-VPS copies.
- Load-test and failure-injection results published; runbooks current; production acceptance report lists each scenario A-H with evidence.
