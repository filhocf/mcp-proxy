"""Structured JSON access logging for proxied requests."""

import json
import logging
import os
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from typing_extensions import Self

DEFAULT_LOG_PATH = os.path.expanduser("~/dtp/ai-configs/mcp-proxy/logs/access.jsonl")
MAX_BYTES = 10 * 1024 * 1024  # 10MB
BACKUP_COUNT = 5

_access_logger: logging.Logger | None = None


def get_access_logger(log_path: str = DEFAULT_LOG_PATH) -> logging.Logger:
    """Get or create the access logger with rotating file handler."""
    global _access_logger
    if _access_logger is not None:
        return _access_logger

    Path(log_path).parent.mkdir(parents=True, exist_ok=True)

    _access_logger = logging.getLogger("mcp_proxy.access")
    _access_logger.setLevel(logging.INFO)
    _access_logger.propagate = False  # Don't pollute main logs

    handler = RotatingFileHandler(log_path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT)
    handler.setFormatter(logging.Formatter("%(message)s"))
    _access_logger.addHandler(handler)

    return _access_logger


def log_request(
    server: str,
    tool: str,
    latency_ms: float,
    status: str,
    client_ip: str = "",
) -> None:
    """Log a structured JSON access entry."""
    logger = get_access_logger()
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "server": server,
        "tool": tool,
        "latency_ms": round(latency_ms, 2),
        "status": status,
        "client_ip": client_ip,
    }
    logger.info(json.dumps(entry, separators=(",", ":")))


class RequestTimer:
    """Context manager to measure request latency."""

    def __init__(self) -> None:
        self.start_time: float = 0
        self.elapsed_ms: float = 0

    def __enter__(self) -> Self:
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, *_) -> None:
        self.elapsed_ms = (time.perf_counter() - self.start_time) * 1000
