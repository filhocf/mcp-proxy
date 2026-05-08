"""Tests for in-memory metrics collection."""

import pytest

from mcp_proxy.metrics import (
    MetricsCollector,
    ServerMetrics,
    get_metrics_status,
    record_metric,
    reset_metrics,
)


@pytest.fixture(autouse=True)
def clean_metrics():
    """Reset metrics between tests."""
    reset_metrics()
    yield
    reset_metrics()


def test_server_metrics_record() -> None:
    """Test basic recording of metrics."""
    m = ServerMetrics()
    m.record(50.0, False)
    m.record(100.0, True)
    assert m.requests_total == 2
    assert m.errors_total == 1
    assert m.last_request_at is not None


def test_server_metrics_percentiles() -> None:
    """Test percentile calculation."""
    m = ServerMetrics()
    # Add 100 values from 1 to 100
    for i in range(1, 101):
        m.record(float(i), False)
    # p50 index = int(100*0.5) = 50 -> sorted[50] = 51
    assert m.latency_p50() == 51.0
    # p99 index = int(100*0.99) = 99 -> sorted[99] = 100
    assert m.latency_p99() == 100.0


def test_server_metrics_empty_percentiles() -> None:
    """Test percentiles with no data."""
    m = ServerMetrics()
    assert m.latency_p50() is None
    assert m.latency_p99() is None


def test_server_metrics_to_dict() -> None:
    """Test dict serialization."""
    m = ServerMetrics()
    m.record(42.0, False)
    d = m.to_dict()
    assert d["requests_total"] == 1
    assert d["errors_total"] == 0
    assert d["latency_p50_ms"] == 42.0
    assert d["latency_p99_ms"] == 42.0
    assert d["last_request_at"] is not None


def test_collector_multiple_servers() -> None:
    """Test collector with multiple servers."""
    c = MetricsCollector()
    c.record("server-a", 10.0, False)
    c.record("server-a", 20.0, False)
    c.record("server-b", 50.0, True)

    status = c.get_status()
    assert status["global"]["total_requests"] == 3
    assert status["global"]["total_errors"] == 1
    assert "uptime_seconds" in status["global"]
    assert status["per_server"]["server-a"]["requests_total"] == 2
    assert status["per_server"]["server-b"]["errors_total"] == 1


def test_module_level_functions() -> None:
    """Test the module-level record_metric and get_metrics_status."""
    record_metric("test-srv", 25.0, False)
    record_metric("test-srv", 75.0, True)

    status = get_metrics_status()
    assert status["global"]["total_requests"] == 2
    assert status["global"]["total_errors"] == 1
    assert status["per_server"]["test-srv"]["requests_total"] == 2


def test_latency_window_limit() -> None:
    """Test that latency deque respects window size."""
    from mcp_proxy.metrics import LATENCY_WINDOW

    m = ServerMetrics()
    for i in range(LATENCY_WINDOW + 100):
        m.record(float(i), False)
    assert len(m.latencies) == LATENCY_WINDOW
