"""Reconnect manager for stdio MCP servers — lazy respawn after process death."""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from anyio import ClosedResourceError, EndOfStream
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

logger = logging.getLogger(__name__)

# Errors that indicate a dead process/pipe (specific, not broad OSError)
RECONNECTABLE_ERRORS = (
    ClosedResourceError,
    EndOfStream,
    BrokenPipeError,
    ConnectionResetError,
)


@dataclass
class ManagedSession:
    """A managed MCP session with reconnect capability."""

    name: str
    params: StdioServerParameters
    session: ClientSession | None = None
    _cm: Any = field(default=None, repr=False)
    _session_cm: Any = field(default=None, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    reconnect_count: int = 0

    async def reconnect(self) -> ClientSession:
        """Cleanup dead session, spawn fresh process, create new session."""
        async with self._lock:
            logger.warning("Reconnecting server '%s' (attempt #%d)...", self.name, self.reconnect_count + 1)
            # Cleanup old resources
            await self._cleanup()
            # Spawn new process
            self._cm = stdio_client(self.params)
            streams = await self._cm.__aenter__()
            self._session_cm = ClientSession(*streams)
            self.session = await self._session_cm.__aenter__()
            await self.session.initialize()
            self.reconnect_count += 1
            logger.info("Server '%s' reconnected successfully.", self.name)
            return self.session

    async def _cleanup(self) -> None:
        """Cleanup old session and context manager resources."""
        if self._session_cm is not None:
            try:
                await self._session_cm.__aexit__(None, None, None)
            except Exception:
                pass
            self._session_cm = None
        if self._cm is not None:
            try:
                await self._cm.__aexit__(None, None, None)
            except Exception:
                pass
            self._cm = None
        self.session = None


class ReconnectManager:
    """Manages lazy reconnect for named MCP servers."""

    def __init__(self) -> None:
        self._sessions: dict[str, ManagedSession] = {}

    def register(self, name: str, params: StdioServerParameters, session: ClientSession) -> None:
        """Register a server's session and params for future reconnect."""
        managed = ManagedSession(name=name, params=params, session=session)
        self._sessions[name] = managed

    def get_session(self, name: str) -> ClientSession:
        """Get current session for a server."""
        managed = self._sessions.get(name)
        if managed is None:
            raise KeyError(f"Server '{name}' not registered for reconnect")
        if managed.session is None:
            raise RuntimeError(f"Server '{name}' not connected")
        return managed.session

    async def call_with_reconnect(self, name: str, coro_factory):
        """Execute a coroutine with automatic reconnect on connection failure.

        coro_factory: callable(session) -> awaitable
        """
        managed = self._sessions.get(name)
        if managed is None:
            raise KeyError(f"Server '{name}' not registered for reconnect")

        try:
            return await coro_factory(managed.session)
        except RECONNECTABLE_ERRORS as e:
            logger.warning(
                "Server '%s' connection lost (%s: %s). Attempting reconnect...",
                name, type(e).__name__, e,
            )
            new_session = await managed.reconnect()
            # Retry once with new session
            return await coro_factory(new_session)

    def status(self) -> dict[str, Any]:
        """Get reconnect status for all managed servers."""
        return {
            name: {
                "reconnect_count": ms.reconnect_count,
            }
            for name, ms in self._sessions.items()
        }


# Global instance
_manager = ReconnectManager()


def get_reconnect_manager() -> "ReconnectManager":
    """Get the global reconnect manager."""
    return _manager
