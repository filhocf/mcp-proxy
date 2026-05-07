"""Configuration loader for MCP proxy.

This module provides functionality to load named server configurations from JSON files.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

from mcp.client.stdio import StdioServerParameters

from .circuit_breaker import register_circuit_breaker

logger = logging.getLogger(__name__)


# Store per-server extra config (circuit_breaker, retry, etc.)
_server_configs: dict[str, dict[str, Any]] = {}


def get_server_config(server_name: str) -> dict[str, Any]:
    """Get extra config for a server."""
    return _server_configs.get(server_name, {})


def load_named_server_configs_from_file(
    config_file_path: str | Path,
    base_env: dict[str, str],
) -> dict[str, StdioServerParameters]:
    """Loads named server configurations from a JSON file.

    Args:
        config_file_path: Path to the JSON configuration file.
        base_env: The base environment dictionary to be inherited by servers.

    Returns:
        A dictionary of named server parameters.

    Raises:
        FileNotFoundError: If the config file is not found.
        json.JSONDecodeError: If the config file contains invalid JSON.
        ValueError: If the config file format is invalid.
    """
    named_stdio_params: dict[str, StdioServerParameters] = {}
    logger.info("Loading named server configurations from: %s", config_file_path)

    try:
        with Path(config_file_path).open() as f:
            config_data = json.load(f)
    except FileNotFoundError:
        logger.exception("Configuration file not found: %s", config_file_path)
        raise
    except json.JSONDecodeError:
        logger.exception("Error decoding JSON from configuration file: %s", config_file_path)
        raise
    except Exception as e:
        logger.exception(
            "Unexpected error opening or reading configuration file %s",
            config_file_path,
        )
        error_message = f"Could not read configuration file: {e}"
        raise ValueError(error_message) from e

    if not isinstance(config_data, dict) or "mcpServers" not in config_data:
        msg = f"Invalid config file format in {config_file_path}. Missing 'mcpServers' key."
        logger.error(msg)
        raise ValueError(msg)

    for name, server_config in config_data.get("mcpServers", {}).items():
        if not isinstance(server_config, dict):
            logger.warning(
                "Skipping invalid server config for '%s' in %s. Entry is not a dictionary.",
                name,
                config_file_path,
            )
            continue
        if not server_config.get("enabled", True):  # Default to True if 'enabled' is not present
            logger.info("Named server '%s' from config is not enabled. Skipping.", name)
            continue

        command = server_config.get("command")
        command_args = server_config.get("args", [])
        env = server_config.get("env", {})

        if not command:
            logger.warning(
                "Named server '%s' from config is missing 'command'. Skipping.",
                name,
            )
            continue
        if not isinstance(command_args, list):
            logger.warning(
                "Named server '%s' from config has invalid 'args' (must be a list). Skipping.",
                name,
            )
            continue

        new_env = base_env.copy()
        new_env.update(
            {k: os.path.expandvars(os.path.expanduser(v)) for k, v in env.items()}
        )

        named_stdio_params[name] = StdioServerParameters(
            command=command,
            args=command_args,
            env=new_env,
            cwd=None,
        )
        logger.info(
            "Configured named server '%s' from config: %s %s",
            name,
            command,
            " ".join(command_args),
        )

        # Load extra per-server config (circuit_breaker, retry, etc.)
        extra_cfg: dict[str, Any] = {}
        if "circuit_breaker" in server_config:
            cb_cfg = server_config["circuit_breaker"]
            register_circuit_breaker(name, cb_cfg)
            extra_cfg["circuit_breaker"] = cb_cfg
            logger.info("Circuit breaker configured for server '%s'", name)
        if "retry" in server_config:
            extra_cfg["retry"] = server_config["retry"]
        _server_configs[name] = extra_cfg

    return named_stdio_params
