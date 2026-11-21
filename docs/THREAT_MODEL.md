# Threat Model

Scope: the control plane (API + MCP + scheduler) and workers on machines controlled by
the operator. Assumption: HTTPS/WireGuard transport terminates outside the app.

## Adversaries and mitigations

| # | Adversary / vector | Impact | Mitigation | Status |
|---|---|---|---|---|
| 1 | Anonymous attacker → REST API | auth bypass, DoS | argon2+JWT, RBAC, rate limits on register/login/worker-register | Tested |
| 2 | Stolen user JWT | account access | 12h TTL, revocation_ts, logout | Tested |
| 3 | Stolen agent/worker key | job injection | hashed at rest, enable/disable, 30d worker TTL | Implemented |
| 4 | Malicious archive upload (Zip Slip, symlinks, bombs) | arbitrary file write, disk exhaustion | traversal/symlink/caps/entry-count/streamed checks | Tested |
| 5 | Malicious job payload | host compromise on worker | no shell by default, rlimits, process-group kill, untrusted⇒sandbox gate | Tested (subprocess level); container isolation pending (Phase 4) |
| 6 | Malicious git URL | SSRF / local file read | https:// + git@ URL allow-policy, timeout | Tested (policy) |
| 7 | Secret leakage via logs/audit | credential exposure | redaction list, hashed tokens, never log env | Tested |
| 8 | Path traversal in workspace file ops | FS escape | resolve+containment checks | Tested |
| 9 | Worker impersonation / bad capability report | wrong scheduling, DoS | signed JWT worker identity; capability reports are trust-on-registration (residual risk: a compromised worker can lie about RAM — accepted for MVP, see Residual) | Partial |
| 10 | MCP client abuse of tools | unauthorized ops | in-process bearer enforcement: static token, valid user JWT, or enabled agent key; unauthenticated requests only from loopback in non-production; production requires OMNIMCP_MCP_TOKEN or an explicit authenticated-proxy declaration | Tested |
| 11 | SQL injection | data access | SQLAlchemy-bound parameters only | Design |
| 12 | Large uploads exhausting VPS disk/RAM | DoS | 1 MiB streaming chunks, size caps, >10 GB directs to GCS | Implemented (local tested; GCS unverified) |
| 13 | Scheduler starvation / noisy neighbor | availability | priority queue, max_retries, offline requeue | Tested basics |

## Residual risks (accepted for MVP, tracked)

1. **MCP authentication is bearer-based.** Static tokens, user JWTs and agent keys are
   enforced in-process; full OAuth 2.1 resource-server behavior (RFC 9728 / RFC 8707,
   MCP spec 2026-07-28) is planned so external MCP clients can discover the
   authorization server. Rotate OMNIMCP_MCP_TOKEN through the secret-management path.
2. **Worker capability reports are self-asserted.** A compromised worker can overstate
   resources. Later: scheduler-side probes for claimed jobs (admission check on claim).
3. **Single process control plane**: no HA; acceptable on 2 vCPU/4 GB target.
4. **SQLite default** dev storage; production must use PostgreSQL (limitation: concurrent
   writes serialize; see ADR-0002).
