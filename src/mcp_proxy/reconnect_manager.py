"""Reconnect manager for stdio MCP servers — lazy respawn after process death."""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from anyio import ClosedResourceError, EndOfStream
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

logger = logging.getLogger(__name__)

# Errors that indicate a dead process/pipe
RECONNECTABLE_ERRORS = (
    ClosedResourceError,
    EndOfStream,
    BrokenPipeError,
    ConnectionResetError,
    OSError,
)


@dataclass
class ManagedSession:
    """A managed MCP session with reconnect capability."""

    name: str
    params: StdioServerParameters
    session: ClientSession | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    reconnect_count: int = 0

    async def reconnect(self) -> ClientSession:
        """Spawn a fresh process and create new session."""
        async with self._lock:
            logger.warning("Reconnecting server '%s' (attempt #%d)...", self.name, self.reconnect_count + 1)
            # Spawn new process
            cm = stdio_client(self.params)
            streams = await cm.__aenter__()
            session_cm = ClientSession(*streams)
            self.session = await session_cm.__aenter__()
            await self.session.initialize()
            self.reconnect_count += 1
            logger.info("Server '%s' reconnected successfully (PID active).", self.name)
            return self.session


class ReconnectManager:
    """Manages lazy reconnect for named MCP servers."""

    def __init__(self) -> None:
        self._sessions: dict[str, ManagedSession] = {}

    def register(self, name: str, params: StdioServerParameters, session: ClientSession) -> None:
        """Register a server's session and params for future reconnect."""
        managed = ManagedSession(name=name, params=params, session=session)
        self._sessions[name] = managed

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


def get_reconnect_manager() -> ReconnectManager:
    """Get the global reconnect manager."""
    return _manager
