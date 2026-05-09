# mcp-proxy-plus

Production-grade MCP gateway. Manages multiple MCP servers behind a single endpoint with enterprise features.

[![Tests](https://img.shields.io/badge/tests-196%20passing-brightgreen)]()
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)]()
[![License](https://img.shields.io/github/license/filhocf/mcp-proxy)](LICENSE)

## What is this?

A proxy that sits between your AI client (Claude, Kiro, Cursor) and multiple MCP servers. It:

- Exposes all servers on a **single port** (SSE or Streamable HTTP)
- Adds **rate limiting, circuit breaker, retry** for resilience
- Provides **auth, RBAC, audit logging** for security
- Supports **hot-reload, dynamic registration, lazy connections** for operations
- Includes a **dashboard, metrics, OpenTelemetry** for observability

```
┌─────────────┐         ┌──────────────┐         ┌─────────────────┐
│  AI Client  │◄──SSE──►│  mcp-proxy   │◄──stdio──►│  MCP Server 1  │
│  (Kiro/etc) │         │  :3100       │◄──stdio──►│  MCP Server 2  │
└─────────────┘         │              │◄──stdio──►│  MCP Server N  │
                        └──────────────┘         └─────────────────┘
```

## Install

```bash
# From GitHub (recommended)
uv tool install --force git+https://github.com/filhocf/mcp-proxy.git@v1.0.0

# From source
git clone https://github.com/filhocf/mcp-proxy.git
cd mcp-proxy && uv tool install --force .
```

## Quick Start

```bash
# Single server
mcp-proxy --port 3100 uvx mcp-server-fetch

# Multiple named servers (config file)
mcp-proxy --port 3100 --named-server-config servers.json
```

Servers are accessible at `http://localhost:3100/servers/{name}/sse`.

### Config file (`servers.json`)

```json
{
  "mcpServers": {
    "memory": {
      "command": "/path/to/memory-server",
      "args": ["--db", "/data/memory.db"],
      "env": {"SOME_VAR": "value"}
    },
    "task-orchestrator": {
      "command": "uvx",
      "args": ["task-orchestrator-py"]
    }
  }
}
```

## Features

All features are **opt-in**. Zero config = original mcp-proxy behavior.

### Resilience

| Feature | Config | Description |
|---------|--------|-------------|
| **Rate Limiting** | `max_concurrent` per server | Prevents runaway LLM loops from overwhelming backends |
| **Circuit Breaker** | `failure_threshold`, `recovery_timeout` | Auto-disables failing servers, retries after cooldown |
| **Retry with Backoff** | `max_retries`, `backoff_factor` | Exponential backoff for transient failures (503, timeouts) |
| **Lazy Connection** | `lazy: true` per server | Connect on first request, not at startup. Unavailable backends don't crash proxy |
| **Graceful Failure** | Always on | Single server crash doesn't take down the proxy |

### Security

| Feature | Config | Description |
|---------|--------|-------------|
| **API Key Auth** | `MCP_PROXY_API_KEY` env | Bearer token required for all requests (except /health) |
| **Multi API Key** | `MCP_PROXY_API_KEYS` env | Multiple keys with per-key server permissions |
| **RBAC per Tool** | `allowed_tools`/`denied_tools` | Restrict which tools each key can access |
| **Audit Log** | `MCP_PROXY_AUDIT_LOG` env | JSONL log of all tool calls with rotation |

### Observability

| Feature | Config | Description |
|---------|--------|-------------|
| **JSON Logging** | `MCP_PROXY_JSON_LOGS=1` | Structured access logs for log aggregators |
| **/status Metrics** | Always on | Per-server request counts, errors, latency |
| **OpenTelemetry** | `MCP_PROXY_OTEL_ENDPOINT` | Distributed tracing for tool calls |
| **HTML Dashboard** | GET `/dashboard` | Minimal monitoring UI |

### Operations

| Feature | Config | Description |
|---------|--------|-------------|
| **Hot-Reload** | `SIGHUP` or `POST /reload` | Reload config without restart (no dropped connections) |
| **Dynamic Registration** | `POST /servers` | Add/remove servers at runtime via REST API |
| **REST-to-MCP Adapter** | `MCP_PROXY_REST_SPEC` | Expose MCP tools as REST endpoints via OpenAPI spec |
| **Env Var Expansion** | Always on | Use `${HOME}` in config values |

## Endpoints

| Path | Description |
|------|-------------|
| `/health` | Health check (always public) |
| `/status` | Per-server metrics |
| `/dashboard` | HTML monitoring UI |
| `/reload` | POST to hot-reload config |
| `/servers` | POST to register/remove servers dynamically |
| `/servers/{name}/sse` | SSE endpoint for named server |
| `/servers/{name}/mcp` | Streamable HTTP endpoint |

## CLI Arguments

```
mcp-proxy [OPTIONS] [command_or_url] [args...]

Options:
  --port PORT              Port to listen on (default: random)
  --host HOST              Host to bind (default: 127.0.0.1)
  --named-server-config F  JSON config file for named servers
  --named-server NAME CMD  Define a named server inline
  --api-key KEY            Require API key (or MCP_PROXY_API_KEY env)
  --transport {sse,streamablehttp}  Client transport mode
  --log-level LEVEL        Log level (default: INFO)
  --pass-environment       Pass all env vars to child servers
  --allow-origin ORIGIN    CORS allowed origins
  --stateless              Stateless streamable HTTP mode
```

## systemd Service

```ini
# ~/.config/systemd/user/mcp-proxy.service
[Unit]
Description=MCP Proxy
After=network.target

[Service]
Type=simple
ExecStart=/home/user/.local/bin/mcp-proxy --port 3100 --named-server-config /path/to/servers.json
Restart=on-failure
RestartSec=5
Environment=PATH=/home/user/.local/bin:/usr/bin

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now mcp-proxy
```

## Testing

```bash
uv sync --all-extras
uv run pytest tests/ -q
# 196 passed in 6s
```

## Origin

Originally forked from [sparfenyuk/mcp-proxy](https://github.com/sparfenyuk/mcp-proxy). Diverged significantly with 13 production features, 196 tests (up from ~50), and independent release cycle. Published as `mcp-proxy-plus` on PyPI.

## License

MIT
