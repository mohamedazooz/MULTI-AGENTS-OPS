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

## Authentication (status)

Tool calls currently run **without per-request bearer enforcement** (transport security
settings from the SDK are active). Requirement: bind /mcp to a private interface or
authenticated proxy until the in-process bearer verifier lands
(THREAT_MODEL #10, Phase 8).

## Client compatibility matrix

| Client | Transport | Status |
|---|---|---|
| Official Python MCP client (`streamablehttp_client`) | Streamable HTTP | ✅ tested E2E in CI |
| Claude Code / Codex / Gemini CLI / Roo Code / ChatGPT-connector | MCP HTTP | 🔴 **Not tested** — never advertise as supported until each is verified per phase 8 |
| Any MCP 1.x client | Streamable HTTP | expected compatible, untested |

## Configuration example (generic MCP client)

```json
{"mcpServers": {"omnimcp": {"url": "http://127.0.0.1:8000/mcp"}}}
```
