# MCP Integration

Server: official MCP Python SDK (FastMCP), Streamable HTTP, mounted at `/mcp`
(SSE-capable; JSON responses supported). Endpoint: `http(s)://<host>/mcp`.

## Tools (12)

| Tool | Purpose |
|---|---|
| system_status | version, queue depth, running jobs, workers online |
| workspace_create | create (+optional https git clone) |
| workspace_list | list workspaces |
| filesystem_read / filesystem_write | contained file ops by workspace name |
| job_submit / job_status / job_cancel | schedule + track jobs |
| worker_list / worker_capabilities | registry introspection |
| connector_list | connector registry |
| artifact_list | storage objects |

Deliberate exclusions: no generic shell tool, no unbounded filesystem access — execution
goes through jobs bounded by worker capabilities, resources and policy.

## Authentication (enforced in-process)

Bearer enforcement is active on every `/mcp` request (closes THREAT MODEL #10):

1. **Static shared token** — `Authorization: Bearer <OMNIMCP_MCP_TOKEN>` (constant-time compare).
2. **User JWT** — a token issued by the REST auth API (active, non-revoked user).
3. **Agent key** — an enabled agent's key from the agent registry.

Without credentials, requests are served only from **loopback clients** and only in
**non-production** environments. In production, configure `OMNIMCP_MCP_TOKEN`, or (only
when an authenticated reverse proxy fronts `/mcp`) set
`OMNIMCP_MCP_UNAUTHENTICATED_PROXY=true`. Unauthorized requests receive
`401` with `WWW-Authenticate: Bearer`.

Planned next step: OAuth 2.1 resource-server metadata (RFC 9728 / RFC 8707, MCP spec
2026-07-28) so external MCP clients can discover the authorization server.

## Client compatibility matrix

| Client | Transport | Status |
|---|---|---|
| Official Python MCP client (`streamablehttp_client`) | Streamable HTTP | ✅ tested E2E in CI (loopback, dev env) |
| Claude Code / Codex / Gemini CLI / Roo Code / ChatGPT-connector | MCP HTTP | 🔴 **Not tested** — never advertise as supported until each is verified per phase 8 |
| Any MCP 1.x client | Streamable HTTP | expected compatible, untested |

## Configuration example (generic MCP client)

```json
{"mcpServers": {"omnimcp": {"url": "http://127.0.0.1:8000/mcp", "headers": {"Authorization": "Bearer <token>"}}}}
```
