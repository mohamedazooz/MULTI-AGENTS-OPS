# ADR-0005: official MCP Python SDK pinned to 1.x

**Status:** Accepted · **Date:** 2026-11-20

## Context
`mcp` 2.x renamed FastMCP→MCPServer and changed Streamable-HTTP internals
(`streamable_http_app` route registration, session-manager semantics).

## Decision
Pin `mcp>=1.12,<2` in backend (+ worker) to keep FastMCP's stable tool surface.
Re-evaluate with the 2.x migration when the ecosystem (clients) converges.

## Consequences
- Tested path: FastMCP + `streamable_http_app()` mounted at `/mcp` with internal
  `streamable_http_path="/"` (mount-path doubling checked in E2E).
- Upgrade plan: adapt `mcp_server.py` + `main.py` mount, rerun MCP E2E.
