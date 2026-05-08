"""Tests for RBAC per-tool access control."""
# ruff: noqa: PLR2004, S101

import json

import pytest

from mcp_proxy.mcp_server import APIKeyEntry, RBACToolMiddleware

# --- Unit tests for APIKeyEntry.is_tool_allowed ---


class TestIsToolAllowed:
    """Test the is_tool_allowed method."""

    def test_wildcard_allows_all(self) -> None:
        entry = APIKeyEntry(key="k", name="admin", allowed_tools=["*"])
        assert entry.is_tool_allowed("any_tool") is True

    def test_exact_match(self) -> None:
        entry = APIKeyEntry(key="k", name="dev", allowed_tools=["memory_store", "memory_search"])
        assert entry.is_tool_allowed("memory_store") is True
        assert entry.is_tool_allowed("memory_search") is True
        assert entry.is_tool_allowed("kubectl_exec") is False

    def test_wildcard_pattern(self) -> None:
        entry = APIKeyEntry(key="k", name="dev", allowed_tools=["memory_*"])
        assert entry.is_tool_allowed("memory_store") is True
        assert entry.is_tool_allowed("memory_search") is True
        assert entry.is_tool_allowed("kubectl_exec") is False

    def test_denied_takes_precedence(self) -> None:
        entry = APIKeyEntry(key="k", name="dev", allowed_tools=["*"], denied_tools=["kubectl_*"])
        assert entry.is_tool_allowed("memory_store") is True
        assert entry.is_tool_allowed("kubectl_exec") is False
        assert entry.is_tool_allowed("kubectl_apply") is False

    def test_denied_exact_match(self) -> None:
        entry = APIKeyEntry(
            key="k", name="dev", allowed_tools=["*"], denied_tools=["dangerous_tool"]
        )
        assert entry.is_tool_allowed("dangerous_tool") is False
        assert entry.is_tool_allowed("safe_tool") is True

    def test_empty_allowed_denies_all(self) -> None:
        entry = APIKeyEntry(key="k", name="dev", allowed_tools=[])
        assert entry.is_tool_allowed("any_tool") is False

    def test_multiple_denied_patterns(self) -> None:
        entry = APIKeyEntry(
            key="k",
            name="dev",
            allowed_tools=["*"],
            denied_tools=["kubectl_*", "shell_*", "dangerous_*"],
        )
        assert entry.is_tool_allowed("kubectl_exec") is False
        assert entry.is_tool_allowed("shell_run") is False
        assert entry.is_tool_allowed("dangerous_delete") is False
        assert entry.is_tool_allowed("memory_store") is True


# --- Integration tests for RBACToolMiddleware ---


def _make_jsonrpc_body(method: str, tool_name: str = "", req_id: int = 1) -> bytes:
    """Create a JSON-RPC request body."""
    body: dict = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if method == "tools/call":
        body["params"] = {"name": tool_name, "arguments": {}}
    else:
        body["params"] = {}
    return json.dumps(body).encode()


def _make_scope(path: str = "/mcp", entry: APIKeyEntry | None = None) -> dict:
    """Create a minimal ASGI HTTP scope with state."""
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
async def test_rbac_allows_permitted_tool() -> None:
    """Permitted tool passes through."""
    entry = APIKeyEntry(key="k", name="dev", allowed_tools=["memory_*"])
    body = _make_jsonrpc_body("tools/call", "memory_store")
    passed_through = False

    async def dummy_app(scope, receive, send) -> None:
        nonlocal passed_through
        passed_through = True

    mw = RBACToolMiddleware(dummy_app)

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message) -> None:
        pass

    scope = _make_scope(entry=entry)
    await mw(scope, receive, send)
    assert passed_through is True


@pytest.mark.asyncio
async def test_rbac_blocks_denied_tool() -> None:
    """Denied tool returns 403."""
    entry = APIKeyEntry(key="k", name="dev", allowed_tools=["*"], denied_tools=["kubectl_*"])
    body = _make_jsonrpc_body("tools/call", "kubectl_exec")
    responses: list[dict] = []

    async def dummy_app(scope, receive, send) -> None:
        pytest.fail("Should not reach app")

    mw = RBACToolMiddleware(dummy_app)

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message) -> None:
        responses.append(message)

    scope = _make_scope(entry=entry)
    await mw(scope, receive, send)
    status_msg = next(m for m in responses if m["type"] == "http.response.start")
    assert status_msg["status"] == 403
    body_msg = next(m for m in responses if m["type"] == "http.response.body")
    resp_data = json.loads(body_msg["body"])
    assert "kubectl_exec" in resp_data["error"]["message"]
    assert "Forbidden" in resp_data["error"]["message"]


@pytest.mark.asyncio
async def test_rbac_blocks_not_in_allowed_list() -> None:
    """Tool not in allowed list returns 403."""
    entry = APIKeyEntry(key="k", name="dev", allowed_tools=["memory_*"])
    body = _make_jsonrpc_body("tools/call", "shell_exec")
    responses: list[dict] = []

    async def dummy_app(scope, receive, send) -> None:
        pytest.fail("Should not reach app")

    mw = RBACToolMiddleware(dummy_app)

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message) -> None:
        responses.append(message)

    scope = _make_scope(entry=entry)
    await mw(scope, receive, send)
    status_msg = next(m for m in responses if m["type"] == "http.response.start")
    assert status_msg["status"] == 403


@pytest.mark.asyncio
async def test_rbac_non_tool_call_passes_through() -> None:
    """Non tools/call requests pass through."""
    entry = APIKeyEntry(key="k", name="dev", allowed_tools=["memory_*"])
    body = _make_jsonrpc_body("tools/list")
    passed_through = False

    async def dummy_app(scope, receive, send) -> None:
        nonlocal passed_through
        passed_through = True

    mw = RBACToolMiddleware(dummy_app)

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message) -> None:
        pass

    scope = _make_scope(entry=entry)
    await mw(scope, receive, send)
    assert passed_through is True


@pytest.mark.asyncio
async def test_rbac_no_entry_passes_through() -> None:
    """No api_key_entry in state passes through (no auth context)."""
    body = _make_jsonrpc_body("tools/call", "kubectl_exec")
    passed_through = False

    async def dummy_app(scope, receive, send) -> None:
        nonlocal passed_through
        passed_through = True

    mw = RBACToolMiddleware(dummy_app)

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message) -> None:
        pass

    scope = _make_scope()  # No entry
    await mw(scope, receive, send)
    assert passed_through is True


@pytest.mark.asyncio
async def test_rbac_get_request_passes_through() -> None:
    """GET requests pass through without body inspection."""
    entry = APIKeyEntry(key="k", name="dev", allowed_tools=[])
    passed_through = False

    async def dummy_app(scope, receive, send) -> None:
        nonlocal passed_through
        passed_through = True

    mw = RBACToolMiddleware(dummy_app)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message) -> None:
        pass

    scope = _make_scope(entry=entry)
    scope["method"] = "GET"
    await mw(scope, receive, send)
    assert passed_through is True


@pytest.mark.asyncio
async def test_rbac_wildcard_allowed_no_denied_skips_parsing() -> None:
    """Wildcard allowed with no denied skips body parsing (fast path)."""
    entry = APIKeyEntry(key="k", name="admin", allowed_tools=["*"], denied_tools=[])
    body = _make_jsonrpc_body("tools/call", "anything")
    passed_through = False

    async def dummy_app(scope, receive, send) -> None:
        nonlocal passed_through
        passed_through = True

    mw = RBACToolMiddleware(dummy_app)

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message) -> None:
        pass

    scope = _make_scope(entry=entry)
    await mw(scope, receive, send)
    assert passed_through is True


@pytest.mark.asyncio
async def test_rbac_preserves_request_id_in_error() -> None:
    """Error response preserves the JSON-RPC request id."""
    entry = APIKeyEntry(key="k", name="dev", allowed_tools=[], denied_tools=[])
    body = _make_jsonrpc_body("tools/call", "blocked_tool", req_id=42)
    responses: list[dict] = []

    async def dummy_app(scope, receive, send) -> None:
        pytest.fail("Should not reach app")

    mw = RBACToolMiddleware(dummy_app)

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message) -> None:
        responses.append(message)

    scope = _make_scope(entry=entry)
    await mw(scope, receive, send)
    body_msg = next(m for m in responses if m["type"] == "http.response.body")
    resp_data = json.loads(body_msg["body"])
    assert resp_data["id"] == 42
