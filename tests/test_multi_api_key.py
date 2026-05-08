"""Tests for Multi API Key authentication with per-key permissions."""
# ruff: noqa: PLR2004, S101

import json
import tempfile

import pytest

from mcp_proxy.mcp_server import APIKeyEntry, APIKeyMiddleware, load_api_keys_config

# --- Unit tests for load_api_keys_config ---


def test_load_api_keys_config_basic() -> None:
    """Load a valid config file with multiple keys."""
    config = {
        "api_keys": [
            {"key": "k1", "name": "admin", "role": "admin", "allowed_servers": ["*"]},
            {"key": "k2", "name": "dev", "role": "dev", "allowed_servers": ["memory-service"]},
        ]
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(config, f)
        f.flush()
        entries = load_api_keys_config(f.name)

    assert len(entries) == 2
    assert entries[0].key == "k1"
    assert entries[0].name == "admin"
    assert entries[0].allowed_servers == ["*"]
    assert entries[1].allowed_servers == ["memory-service"]


def test_load_api_keys_config_defaults() -> None:
    """Missing optional fields get defaults."""
    config = {"api_keys": [{"key": "k1", "name": "user1"}]}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(config, f)
        f.flush()
        entries = load_api_keys_config(f.name)

    assert entries[0].role == "user"
    assert entries[0].allowed_servers == ["*"]
    assert entries[0].allowed_tools == ["*"]
    assert entries[0].denied_tools == []


# --- Unit tests for APIKeyMiddleware logic ---


class TestServerAccessCheck:
    """Test _has_server_access static method."""

    def test_wildcard_allows_all(self) -> None:
        entry = APIKeyEntry(key="k", name="admin", allowed_servers=["*"])
        assert APIKeyMiddleware._has_server_access(entry, "any-server") is True

    def test_exact_match(self) -> None:
        entry = APIKeyEntry(key="k", name="dev", allowed_servers=["memory-service"])
        assert APIKeyMiddleware._has_server_access(entry, "memory-service") is True
        assert APIKeyMiddleware._has_server_access(entry, "other-service") is False

    def test_fnmatch_pattern(self) -> None:
        entry = APIKeyEntry(key="k", name="dev", allowed_servers=["db-*"])
        assert APIKeyMiddleware._has_server_access(entry, "db-mcp-py") is True
        assert APIKeyMiddleware._has_server_access(entry, "memory-service") is False

    def test_multiple_patterns(self) -> None:
        entry = APIKeyEntry(key="k", name="dev", allowed_servers=["memory-service", "db-*"])
        assert APIKeyMiddleware._has_server_access(entry, "memory-service") is True
        assert APIKeyMiddleware._has_server_access(entry, "db-mcp-py") is True
        assert APIKeyMiddleware._has_server_access(entry, "kubectl") is False


class TestExtractServerName:
    """Test _extract_server_name static method."""

    def test_named_server_path(self) -> None:
        assert (
            APIKeyMiddleware._extract_server_name("/servers/memory-service/sse") == "memory-service"
        )

    def test_default_server_sse(self) -> None:
        assert APIKeyMiddleware._extract_server_name("/sse") == "default"

    def test_default_server_mcp(self) -> None:
        assert APIKeyMiddleware._extract_server_name("/mcp") == "default"

    def test_messages_path(self) -> None:
        assert APIKeyMiddleware._extract_server_name("/messages/abc") == "default"

    def test_unknown_path(self) -> None:
        assert APIKeyMiddleware._extract_server_name("/unknown") is None


# --- Integration tests using ASGI scope simulation ---


@pytest.fixture
def multi_key_middleware():
    """Create middleware with multiple keys."""
    keys = [
        APIKeyEntry(key="admin-key", name="admin", role="admin", allowed_servers=["*"]),
        APIKeyEntry(
            key="dev-key",
            name="dev-jr",
            role="dev",
            allowed_servers=["memory-service", "db-mcp-py"],
        ),
    ]

    async def dummy_app(scope, receive, send) -> None:
        from starlette.responses import JSONResponse

        resp = JSONResponse({"ok": True})
        await resp(scope, receive, send)

    return APIKeyMiddleware(dummy_app, api_keys=keys)


def _make_scope(path: str, method: str = "GET", token: str = "") -> dict:
    """Create a minimal ASGI HTTP scope."""
    headers = []
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    return {
        "type": "http",
        "path": path,
        "method": method,
        "headers": headers,
    }


@pytest.mark.asyncio
async def test_multi_key_admin_access_all_servers(multi_key_middleware) -> None:
    """Admin key can access any server."""
    responses = []

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message) -> None:
        responses.append(message)

    scope = _make_scope("/servers/memory-service/sse", token="admin-key")
    await multi_key_middleware(scope, receive, send)
    # Should pass through (200)
    body_msg = next(m for m in responses if m["type"] == "http.response.body")
    assert b'"ok"' in body_msg["body"]


@pytest.mark.asyncio
async def test_multi_key_dev_access_allowed_server(multi_key_middleware) -> None:
    """Dev key can access allowed server."""
    responses = []

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message) -> None:
        responses.append(message)

    scope = _make_scope("/servers/memory-service/sse", token="dev-key")
    await multi_key_middleware(scope, receive, send)
    body_msg = next(m for m in responses if m["type"] == "http.response.body")
    assert b'"ok"' in body_msg["body"]


@pytest.mark.asyncio
async def test_multi_key_dev_denied_server(multi_key_middleware) -> None:
    """Dev key gets 403 for unauthorized server."""
    responses = []

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message) -> None:
        responses.append(message)

    scope = _make_scope("/servers/kubectl/sse", token="dev-key")
    await multi_key_middleware(scope, receive, send)
    status_msg = next(m for m in responses if m["type"] == "http.response.start")
    assert status_msg["status"] == 403


@pytest.mark.asyncio
async def test_multi_key_invalid_key_401(multi_key_middleware) -> None:
    """Invalid key gets 401."""
    responses = []

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message) -> None:
        responses.append(message)

    scope = _make_scope("/servers/memory-service/sse", token="wrong-key")
    await multi_key_middleware(scope, receive, send)
    status_msg = next(m for m in responses if m["type"] == "http.response.start")
    assert status_msg["status"] == 401


@pytest.mark.asyncio
async def test_multi_key_public_paths_bypass(multi_key_middleware) -> None:
    """Public paths bypass auth."""
    responses = []

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message) -> None:
        responses.append(message)

    scope = _make_scope("/health")
    await multi_key_middleware(scope, receive, send)
    body_msg = next(m for m in responses if m["type"] == "http.response.body")
    assert b'"ok"' in body_msg["body"]


@pytest.mark.asyncio
async def test_multi_key_stores_entry_in_scope(multi_key_middleware) -> None:
    """Authenticated request stores APIKeyEntry in scope state."""
    responses = []
    captured_scope = {}

    async def dummy_app(scope, receive, send) -> None:
        captured_scope.update(scope)
        from starlette.responses import JSONResponse

        resp = JSONResponse({"ok": True})
        await resp(scope, receive, send)

    keys = [APIKeyEntry(key="test-key", name="tester", role="admin", allowed_servers=["*"])]
    mw = APIKeyMiddleware(dummy_app, api_keys=keys)

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message) -> None:
        responses.append(message)

    scope = _make_scope("/servers/any/sse", token="test-key")
    await mw(scope, receive, send)
    assert captured_scope["state"]["api_key_entry"].name == "tester"


@pytest.mark.asyncio
async def test_backward_compat_single_key() -> None:
    """Single api_key param still works (backward compatible)."""
    responses = []

    async def dummy_app(scope, receive, send) -> None:
        from starlette.responses import JSONResponse

        resp = JSONResponse({"ok": True})
        await resp(scope, receive, send)

    mw = APIKeyMiddleware(dummy_app, api_key="legacy-key")

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message) -> None:
        responses.append(message)

    scope = _make_scope("/sse", token="legacy-key")
    await mw(scope, receive, send)
    body_msg = next(m for m in responses if m["type"] == "http.response.body")
    assert b'"ok"' in body_msg["body"]
