"""Tests for Audit Log middleware."""
# ruff: noqa: PLR2004, S101

import json
import tempfile
from pathlib import Path

import pytest

from mcp_proxy.mcp_server import APIKeyEntry, AuditLogger, AuditLogMiddleware

# --- Unit tests for AuditLogger ---


def test_audit_logger_creates_directory() -> None:
    """AuditLogger creates parent directories if missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "subdir" / "audit.jsonl"
        AuditLogger(log_path)
        assert log_path.parent.exists()


def test_audit_logger_writes_jsonl() -> None:
    """AuditLogger writes valid JSONL entries."""
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path)
    logger.log(
        api_key_name="admin",
        server="memory-service",
        tool="memory_store",
        args_summary='{"content":"hello"}',
        result_status="success",
        latency_ms=42.5,
    )

    with open(log_path) as f:
        line = f.readline()
        entry = json.loads(line)

    assert entry["api_key_name"] == "admin"
    assert entry["server"] == "memory-service"
    assert entry["tool"] == "memory_store"
    assert entry["result_status"] == "success"
    assert entry["latency_ms"] == 42.5
    assert "timestamp" in entry


def test_audit_logger_truncates_args() -> None:
    """args_summary is truncated to 200 chars."""
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path)
    long_args = "x" * 500
    logger.log(
        api_key_name="test",
        server="srv",
        tool="tool",
        args_summary=long_args,
        result_status="success",
        latency_ms=1.0,
    )

    with open(log_path) as f:
        entry = json.loads(f.readline())

    assert len(entry["args_summary"]) == 200


def test_audit_logger_multiple_entries() -> None:
    """Multiple log calls produce multiple lines."""
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path)
    for i in range(3):
        logger.log(
            api_key_name=f"user{i}",
            server="srv",
            tool="tool",
            args_summary="{}",
            result_status="success",
            latency_ms=float(i),
        )

    with open(log_path) as f:
        lines = f.readlines()

    assert len(lines) == 3


# --- Integration tests for AuditLogMiddleware ---


def _make_jsonrpc_body(method: str, tool_name: str = "", args: dict | None = None) -> bytes:
    """Create a JSON-RPC request body."""
    body: dict = {"jsonrpc": "2.0", "id": 1, "method": method}
    if method == "tools/call":
        body["params"] = {"name": tool_name, "arguments": args or {}}
    else:
        body["params"] = {}
    return json.dumps(body).encode()


def _make_scope(path: str = "/mcp", entry: APIKeyEntry | None = None) -> dict:
    """Create a minimal ASGI HTTP scope."""
    scope: dict = {
        "type": "http",
        "path": path,
        "method": "POST",
        "headers": [(b"content-type", b"application/json")],
    }
    if entry:
        scope["state"] = {"api_key_entry": entry}
    return scope


@pytest.mark.asyncio
async def test_audit_logs_tool_call() -> None:
    """Tool call is logged with correct fields."""
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        log_path = f.name

    audit_logger = AuditLogger(log_path)
    entry = APIKeyEntry(key="k", name="dev-user", allowed_servers=["*"])
    body = _make_jsonrpc_body("tools/call", "memory_store", {"content": "hello"})

    async def dummy_app(scope, receive, send) -> None:
        from starlette.responses import JSONResponse

        resp = JSONResponse({"jsonrpc": "2.0", "result": {}, "id": 1})
        await resp(scope, receive, send)

    mw = AuditLogMiddleware(dummy_app, audit_logger=audit_logger)

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    responses = []

    async def send(message) -> None:
        responses.append(message)

    scope = _make_scope("/servers/memory-service/mcp", entry=entry)
    await mw(scope, receive, send)

    with open(log_path) as f:
        log_entry = json.loads(f.readline())

    assert log_entry["api_key_name"] == "dev-user"
    assert log_entry["server"] == "memory-service"
    assert log_entry["tool"] == "memory_store"
    assert log_entry["result_status"] == "success"
    assert log_entry["latency_ms"] > 0
    assert "content" in log_entry["args_summary"]


@pytest.mark.asyncio
async def test_audit_does_not_log_non_tool_calls() -> None:
    """Non tools/call requests are not logged."""
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        log_path = f.name

    audit_logger = AuditLogger(log_path)
    entry = APIKeyEntry(key="k", name="user", allowed_servers=["*"])
    body = _make_jsonrpc_body("tools/list")

    async def dummy_app(scope, receive, send) -> None:
        from starlette.responses import JSONResponse

        resp = JSONResponse({"jsonrpc": "2.0", "result": [], "id": 1})
        await resp(scope, receive, send)

    mw = AuditLogMiddleware(dummy_app, audit_logger=audit_logger)

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message) -> None:
        pass

    scope = _make_scope(entry=entry)
    await mw(scope, receive, send)

    with open(log_path) as f:
        content = f.read()

    assert content == ""


@pytest.mark.asyncio
async def test_audit_logs_error_status() -> None:
    """Error responses are logged with error status."""
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        log_path = f.name

    audit_logger = AuditLogger(log_path)
    entry = APIKeyEntry(key="k", name="user", allowed_servers=["*"])
    body = _make_jsonrpc_body("tools/call", "failing_tool")

    async def error_app(scope, receive, send) -> None:
        from starlette.responses import JSONResponse

        resp = JSONResponse({"error": "internal"}, status_code=500)
        await resp(scope, receive, send)

    mw = AuditLogMiddleware(error_app, audit_logger=audit_logger)

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message) -> None:
        pass

    scope = _make_scope(entry=entry)
    await mw(scope, receive, send)

    with open(log_path) as f:
        log_entry = json.loads(f.readline())

    assert log_entry["result_status"] == "error"


@pytest.mark.asyncio
async def test_audit_anonymous_when_no_auth() -> None:
    """Logs 'anonymous' when no api_key_entry in state."""
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        log_path = f.name

    audit_logger = AuditLogger(log_path)
    body = _make_jsonrpc_body("tools/call", "some_tool")

    async def dummy_app(scope, receive, send) -> None:
        from starlette.responses import JSONResponse

        resp = JSONResponse({"jsonrpc": "2.0", "result": {}, "id": 1})
        await resp(scope, receive, send)

    mw = AuditLogMiddleware(dummy_app, audit_logger=audit_logger)

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message) -> None:
        pass

    scope = _make_scope()  # No entry
    await mw(scope, receive, send)

    with open(log_path) as f:
        log_entry = json.loads(f.readline())

    assert log_entry["api_key_name"] == "anonymous"


@pytest.mark.asyncio
async def test_audit_get_request_passes_through() -> None:
    """GET requests pass through without auditing."""
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        log_path = f.name

    audit_logger = AuditLogger(log_path)
    passed_through = False

    async def dummy_app(scope, receive, send) -> None:
        nonlocal passed_through
        passed_through = True

    mw = AuditLogMiddleware(dummy_app, audit_logger=audit_logger)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message) -> None:
        pass

    scope = _make_scope()
    scope["method"] = "GET"
    await mw(scope, receive, send)

    assert passed_through is True
    with open(log_path) as f:
        assert f.read() == ""
