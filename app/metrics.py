"""Prometheus metrics for RTSP Music Tagger."""

from typing import Dict, Any
from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    REGISTRY,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from prometheus_client.openmetrics.exposition import generate_latest as generate_openmetrics


# Counters
ffmpeg_restarts_total = Counter(
    "ffmpeg_restarts_total",
    "Total number of FFmpeg process restarts",
    ["stream"],
)

recognitions_total = Counter(
    "recognitions_total",
    "Total number of recognition attempts",
    ["provider", "stream", "status"],
)

recognitions_success_total = Counter(
    "recognitions_success_total",
    "Total number of successful recognitions",
    ["provider", "stream"],
)

recognitions_failure_total = Counter(
    "recognitions_failure_total",
    "Total number of failed recognitions",
    ["provider", "stream", "error_type"],
)

plays_inserted_total = Counter(
    "plays_inserted_total",
    "Total number of plays inserted into database",
    ["stream", "provider"],
)

retention_deletes_total = Counter(
    "retention_deletes_total",
    "Total number of records deleted by retention policy",
    ["table"],
)

# Histograms
recognizer_latency_seconds = Histogram(
    "recognizer_latency_seconds",
    "Recognition latency in seconds",
    ["provider", "stream"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

window_to_recognized_seconds = Histogram(
    "window_to_recognized_seconds",
    "Time from window start to recognition completion",
    ["stream"],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0],
)

ffmpeg_read_gap_seconds = Histogram(
    "ffmpeg_read_gap_seconds",
    "Gap between FFmpeg reads in seconds",
    ["stream"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

# Gauges
streams_active = Gauge(
    "streams_active",
    "Number of active streams",
    ["stream"],
)

queue_depth = Gauge(
    "queue_depth",
    "Current depth of various queues",
    ["name"],
)

retention_last_run_timestamp = Gauge(
    "retention_last_run_timestamp",
    "Timestamp of last retention job run",
    ["job"],
)

embeddings_index_size = Gauge(
    "embeddings_index_size",
    "Number of embeddings in the search index",
)

clustering_last_run_timestamp = Gauge(
    "clustering_last_run_timestamp",
    "Timestamp of last clustering job run",
)

# HTTP metrics (will be instrumented by FastAPI middleware)
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)


def get_metrics() -> bytes:
    """Get Prometheus metrics in text format."""
    return generate_latest(REGISTRY)


def get_metrics_openmetrics() -> bytes:
    """Get Prometheus metrics in OpenMetrics format."""
    return generate_openmetrics(REGISTRY)


def get_metrics_dict() -> Dict[str, Any]:
    """Get metrics as a dictionary for testing/debugging."""
    # This is a simplified version for testing
    # In production, you'd want to parse the actual metrics output
    return {
        "counters": {
            "ffmpeg_restarts_total": {},
            "recognitions_total": {},
            "plays_inserted_total": {},
            "retention_deletes_total": {},
        },
        "histograms": {
            "recognizer_latency_seconds": {},
            "window_to_recognized_seconds": {},
            "ffmpeg_read_gap_seconds": {},
        },
        "gauges": {
            "streams_active": {},
            "queue_depth": {},
            "retention_last_run_timestamp": {},
            "embeddings_index_size": {},
        },
    }


# Convenience functions for common metric operations
def record_ffmpeg_restart(stream: str) -> None:
    """Record an FFmpeg restart for a stream."""
    ffmpeg_restarts_total.labels(stream=stream).inc()


def record_recognition(
    provider: str, stream: str, status: str, error_type: str | None = None
) -> None:
    """Record a recognition attempt."""
    recognitions_total.labels(
        provider=provider, stream=stream, status=status
    ).inc()
    
    if status == "success":
        recognitions_success_total.labels(provider=provider, stream=stream).inc()
    elif status == "failure" and error_type:
        recognitions_failure_total.labels(
            provider=provider, stream=stream, error_type=error_type
        ).inc()


def record_play_inserted(stream: str, provider: str) -> None:
    """Record a play insertion."""
    plays_inserted_total.labels(stream=stream, provider=provider).inc()


def record_retention_deletes(table: str, count: int) -> None:
    """Record retention deletions."""
    retention_deletes_total.labels(table=table).inc(count)


def set_stream_active(stream: str, active: bool) -> None:
    """Set stream active status."""
    streams_active.labels(stream=stream).set(1 if active else 0)


def set_queue_depth(queue_name: str, depth: int) -> None:
    """Set queue depth."""
    queue_depth.labels(name=queue_name).set(depth)


def set_retention_last_run(job: str, timestamp: float) -> None:
    """Set retention job last run timestamp."""
    retention_last_run_timestamp.labels(job=job).set(timestamp)


def set_embeddings_index_size(size: int) -> None:
    """Set embeddings index size."""
    embeddings_index_size.set(size)


def set_clustering_last_run(timestamp: float) -> None:
    """Set clustering job last run timestamp."""
    clustering_last_run_timestamp.set(timestamp)
