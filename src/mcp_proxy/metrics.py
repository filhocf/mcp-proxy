"""In-memory metrics collection for per-server and global statistics."""

import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

LATENCY_WINDOW = 1000  # Keep last N latencies for percentile calculation

_start_time: float = time.monotonic()


@dataclass
class ServerMetrics:
    """Metrics for a single server."""

    requests_total: int = 0
    errors_total: int = 0
    latencies: deque = field(default_factory=lambda: deque(maxlen=LATENCY_WINDOW))
    last_request_at: str | None = None

    def record(self, latency_ms: float, is_error: bool) -> None:
        self.requests_total += 1
        self.latencies.append(latency_ms)
        self.last_request_at = datetime.now(timezone.utc).isoformat()
        if is_error:
            self.errors_total += 1

    def _percentile(self, p: float) -> float | None:
        if not self.latencies:
            return None
        sorted_lat = sorted(self.latencies)
        idx = int(len(sorted_lat) * p)
        return round(sorted_lat[min(idx, len(sorted_lat) - 1)], 2)

    def latency_p50(self) -> float | None:
        return self._percentile(0.5)

    def latency_p99(self) -> float | None:
        return self._percentile(0.99)

    def to_dict(self) -> dict:
        return {
            "requests_total": self.requests_total,
            "errors_total": self.errors_total,
            "latency_p50_ms": self.latency_p50(),
            "latency_p99_ms": self.latency_p99(),
            "last_request_at": self.last_request_at,
        }


class MetricsCollector:
    """Global metrics collector singleton."""

    def __init__(self) -> None:
        self._servers: dict[str, ServerMetrics] = {}

    def record(self, server_name: str, latency_ms: float, is_error: bool) -> None:
        if server_name not in self._servers:
            self._servers[server_name] = ServerMetrics()
        self._servers[server_name].record(latency_ms, is_error)

    def get_status(self) -> dict:
        total_requests = sum(s.requests_total for s in self._servers.values())
        total_errors = sum(s.errors_total for s in self._servers.values())
        return {
            "per_server": {name: m.to_dict() for name, m in self._servers.items()},
            "global": {
                "uptime_seconds": round(time.monotonic() - _start_time, 1),
                "total_requests": total_requests,
                "total_errors": total_errors,
            },
        }


# Module-level singleton
_collector = MetricsCollector()


def record_metric(server_name: str, latency_ms: float, is_error: bool) -> None:
    """Record a request metric."""
    _collector.record(server_name, latency_ms, is_error)


def get_metrics_status() -> dict:
    """Get the full metrics status."""
    return _collector.get_status()


def reset_metrics() -> None:
    """Reset all metrics (for testing)."""
    global _collector
    _collector = MetricsCollector()
