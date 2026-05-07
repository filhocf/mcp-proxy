"""Dynamic server registry for runtime registration/unregistration of MCP servers."""

import json
import logging
from pathlib import Path
from typing import Any

from mcp.client.stdio import StdioServerParameters

logger = logging.getLogger(__name__)


class ServerRegistry:
    """Manages dynamic server registration with config persistence."""

    def __init__(self, config_path: str | Path | None = None) -> None:
        self._servers: dict[str, dict[str, Any]] = {}
        self._config_path = Path(config_path) if config_path else None

    @property
    def servers(self) -> dict[str, dict[str, Any]]:
        return self._servers.copy()

    def register(self, name: str, config: dict[str, Any]) -> StdioServerParameters:
        """Register a new server. Returns StdioServerParameters for immediate use."""
        if name in self._servers:
            msg = f"Server '{name}' already registered"
            raise ValueError(msg)
        if not config.get("command"):
            msg = "Server config must include 'command'"
            raise ValueError(msg)

        self._servers[name] = config
        self._persist()
        logger.info("Registered server '%s': %s", name, config.get("command"))
        return self._to_stdio_params(name, config)

    def unregister(self, name: str) -> None:
        """Unregister a server by name."""
        if name not in self._servers:
            msg = f"Server '{name}' not found"
            raise KeyError(msg)
        del self._servers[name]
        self._persist()
        logger.info("Unregistered server '%s'", name)

    def list_servers(self) -> list[dict[str, Any]]:
        """List all registered servers."""
        return [
            {"name": name, **config}
            for name, config in self._servers.items()
        ]

    def _to_stdio_params(self, name: str, config: dict[str, Any]) -> StdioServerParameters:
        return StdioServerParameters(
            command=config["command"],
            args=config.get("args", []),
            env=config.get("env", {}),
            cwd=None,
        )

    def _persist(self) -> None:
        """Persist current state to config file."""
        if not self._config_path:
            return
        try:
            # Load existing config or create new
            if self._config_path.exists():
                with self._config_path.open() as f:
                    data = json.load(f)
            else:
                data = {}

            data["mcpServers"] = {
                name: {k: v for k, v in config.items() if k != "name"}
                for name, config in self._servers.items()
            }
            with self._config_path.open("w") as f:
                json.dump(data, f, indent=2)
            logger.debug("Persisted config to %s", self._config_path)
        except Exception:
            logger.exception("Failed to persist config to %s", self._config_path)

    def load_from_config(self) -> None:
        """Load servers from config file (for initial startup)."""
        if not self._config_path or not self._config_path.exists():
            return
        try:
            with self._config_path.open() as f:
                data = json.load(f)
            for name, config in data.get("mcpServers", {}).items():
                if config.get("enabled", True):
                    self._servers[name] = config
        except Exception:
            logger.exception("Failed to load config from %s", self._config_path)
