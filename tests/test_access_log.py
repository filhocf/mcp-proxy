"""Tests for structured JSON access logging."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from mcp_proxy.access_log import (
    MAX_BYTES,
    BACKUP_COUNT,
    RequestTimer,
    get_access_logger,
    log_request,
)


@pytest.fixture(autouse=True)
def reset_access_logger():
    """Reset the global access logger between tests."""
    import mcp_proxy.access_log as mod
    mod._access_logger = None
    yield
    if mod._access_logger is not None:
        for h in mod._access_logger.handlers[:]:
            h.close()
            mod._access_logger.removeHandler(h)
    mod._access_logger = None


def test_log_request_writes_json(tmp_path):
    """Test that log_request writes valid JSON to the log file."""
    log_file = tmp_path / "access.jsonl"

    with patch("mcp_proxy.access_log.DEFAULT_LOG_PATH", str(log_file)):
        import mcp_proxy.access_log as mod
        mod._access_logger = None  # Force re-creation
        # Manually create logger with test path
        logger = get_access_logger(str(log_file))
        log_request(server="test-server", tool="my_tool", latency_ms=42.5, status="ok", client_ip="127.0.0.1")

    content = log_file.read_text().strip()
    entry = json.loads(content)
    assert entry["server"] == "test-server"
    assert entry["tool"] == "my_tool"
    assert entry["latency_ms"] == 42.5
    assert entry["status"] == "ok"
    assert entry["client_ip"] == "127.0.0.1"
    assert "timestamp" in entry


def test_log_request_error_status(tmp_path):
    """Test logging with error status."""
    log_file = tmp_path / "access.jsonl"
    get_access_logger(str(log_file))
    log_request(server="srv", tool="fail_tool", latency_ms=100.0, status="error")

    content = log_file.read_text().strip()
    entry = json.loads(content)
    assert entry["status"] == "error"
    assert entry["tool"] == "fail_tool"


def test_request_timer():
    """Test RequestTimer measures elapsed time."""
    import time
    with RequestTimer() as timer:
        time.sleep(0.05)
    assert timer.elapsed_ms >= 40  # At least 40ms (allowing some slack)
    assert timer.elapsed_ms < 200  # But not too long


def test_log_creates_directory(tmp_path):
    """Test that the logger creates parent directories."""
    log_file = tmp_path / "nested" / "dir" / "access.jsonl"
    get_access_logger(str(log_file))
    log_request(server="s", tool="t", latency_ms=1.0, status="ok")
    assert log_file.exists()


def test_rotating_handler_config(tmp_path):
    """Test that the rotating handler is configured correctly."""
    from logging.handlers import RotatingFileHandler
    log_file = tmp_path / "access.jsonl"
    logger = get_access_logger(str(log_file))

    handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    assert len(handlers) == 1
    assert handlers[0].maxBytes == MAX_BYTES
    assert handlers[0].backupCount == BACKUP_COUNT
