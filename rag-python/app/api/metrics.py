"""Prometheus-compatible operational metrics endpoint for WorkMesh."""

from collections import defaultdict
import time
from typing import Dict, List, Tuple
from fastapi import APIRouter, Response

router = APIRouter(tags=["metrics"])

# Thread-safe in-memory metrics counters
_request_counts: Dict[Tuple[str, str, int], int] = defaultdict(int)
_request_latencies: Dict[str, List[float]] = defaultdict(list)
_search_queries_count: int = 0
_ask_queries_count: int = 0


def record_request_metric(method: str, path: str, status_code: int, duration_seconds: float) -> None:
    """Record endpoint request count and latency."""
    # Normalize paths with path parameters
    normalized_path = path
    if path.startswith("/api/v1/admin/audit/events"):
        normalized_path = "/api/v1/admin/audit/events"
    elif path.startswith("/api/v1/"):
        parts = path.split("/")
        if len(parts) > 4:
            normalized_path = "/" + "/".join(parts[1:4])

    _request_counts[(method, normalized_path, status_code)] += 1
    latencies = _request_latencies[normalized_path]
    latencies.append(duration_seconds)
    if len(latencies) > 1000:
        _request_latencies[normalized_path] = latencies[-1000:]

    if normalized_path == "/api/v1/search":
        global _search_queries_count
        _search_queries_count += 1
    elif normalized_path == "/api/v1/ask":
        global _ask_queries_count
        _ask_queries_count += 1


def reset_metrics_for_testing() -> None:
    """Reset counters for unit testing."""
    _request_counts.clear()
    _request_latencies.clear()
    global _search_queries_count, _ask_queries_count
    _search_queries_count = 0
    _ask_queries_count = 0


@router.get("/metrics", response_class=Response)
def get_prometheus_metrics() -> Response:
    """Export platform metrics in Prometheus text exposition format."""
    lines: List[str] = [
        "# HELP workmesh_http_requests_total Total number of HTTP requests processed.",
        "# TYPE workmesh_http_requests_total counter",
    ]

    for (method, path, status_code), count in sorted(_request_counts.items()):
        lines.append(
            f'workmesh_http_requests_total{{method="{method}",path="{path}",status="{status_code}"}} {count}'
        )

    lines.extend([
        "# HELP workmesh_search_queries_total Total search queries processed.",
        "# TYPE workmesh_search_queries_total counter",
        f"workmesh_search_queries_total {_search_queries_count}",
        "# HELP workmesh_ask_queries_total Total grounded Q&A queries processed.",
        "# TYPE workmesh_ask_queries_total counter",
        f"workmesh_ask_queries_total {_ask_queries_count}",
    ])

    lines.extend([
        "# HELP workmesh_http_request_duration_seconds Request duration in seconds.",
        "# TYPE workmesh_http_request_duration_seconds summary",
    ])
    for path, latencies in sorted(_request_latencies.items()):
        if latencies:
            total = sum(latencies)
            count = len(latencies)
            sorted_lat = sorted(latencies)
            p50 = sorted_lat[int(count * 0.5)]
            p90 = sorted_lat[min(int(count * 0.9), count - 1)]
            p99 = sorted_lat[min(int(count * 0.99), count - 1)]
            lines.append(f'workmesh_http_request_duration_seconds{{path="{path}",quantile="0.5"}} {p50:.6f}')
            lines.append(f'workmesh_http_request_duration_seconds{{path="{path}",quantile="0.9"}} {p90:.6f}')
            lines.append(f'workmesh_http_request_duration_seconds{{path="{path}",quantile="0.99"}} {p99:.6f}')
            lines.append(f'workmesh_http_request_duration_seconds_sum{{path="{path}"}} {total:.6f}')
            lines.append(f'workmesh_http_request_duration_seconds_count{{path="{path}"}} {count}')

    output = "\n".join(lines) + "\n"
    return Response(content=output, media_type="text/plain; version=0.0.4; charset=utf-8")
