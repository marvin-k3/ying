"""Tests for metrics module."""

from prometheus_client import REGISTRY

from app.metrics import (
    clustering_last_run_timestamp,
    embeddings_index_size,
    # Import all metrics
    ffmpeg_restarts_total,
    get_metrics,
    get_metrics_dict,
    get_metrics_openmetrics,
    plays_inserted_total,
    queue_depth,
    recognitions_failure_total,
    recognitions_success_total,
    recognitions_total,
    recognizer_latency_seconds,
    record_ffmpeg_restart,
    record_play_inserted,
    record_recognition,
    record_retention_deletes,
    retention_deletes_total,
    retention_last_run_timestamp,
    set_clustering_last_run,
    set_embeddings_index_size,
    set_queue_depth,
    set_retention_last_run,
    set_stream_active,
    streams_active,
)


class TestMetrics:
    """Test metrics collection and recording."""

    def test_get_metrics_returns_bytes(self) -> None:
        """Test that get_metrics returns bytes."""
        metrics = get_metrics()
        assert isinstance(metrics, bytes)
        assert len(metrics) > 0

    def test_get_metrics_openmetrics_returns_bytes(self) -> None:
        """Test that get_metrics_openmetrics returns bytes."""
        metrics = get_metrics_openmetrics()
        assert isinstance(metrics, bytes)
        assert len(metrics) > 0

    def test_get_metrics_dict_returns_dict(self) -> None:
        """Test that get_metrics_dict returns a dictionary."""
        metrics_dict = get_metrics_dict()
        assert isinstance(metrics_dict, dict)
        assert "counters" in metrics_dict
        assert "histograms" in metrics_dict
        assert "gauges" in metrics_dict

    def test_record_ffmpeg_restart(self) -> None:
        """Test recording FFmpeg restart."""
        stream = "test_stream"
        initial_value = ffmpeg_restarts_total.labels(stream=stream)._value.get()

        record_ffmpeg_restart(stream)

        new_value = ffmpeg_restarts_total.labels(stream=stream)._value.get()
        assert new_value == initial_value + 1

    def test_record_recognition_success(self) -> None:
        """Test recording successful recognition."""
        provider = "shazam"
        stream = "test_stream"
        status = "success"

        # Record success
        record_recognition(provider, stream, status)

        # Check total counter
        total_value = recognitions_total.labels(
            provider=provider, stream=stream, status=status
        )._value.get()
        assert total_value == 1

        # Check success counter
        success_value = recognitions_success_total.labels(
            provider=provider, stream=stream
        )._value.get()
        assert success_value == 1

    def test_record_recognition_failure(self) -> None:
        """Test recording failed recognition."""
        provider = "shazam"
        stream = "test_stream"
        status = "failure"
        error_type = "timeout"

        # Record failure
        record_recognition(provider, stream, status, error_type)

        # Check total counter
        total_value = recognitions_total.labels(
            provider=provider, stream=stream, status=status
        )._value.get()
        assert total_value == 1

        # Check failure counter
        failure_value = recognitions_failure_total.labels(
            provider=provider, stream=stream, error_type=error_type
        )._value.get()
        assert failure_value == 1

    def test_record_play_inserted(self) -> None:
        """Test recording play insertion."""
        stream = "test_stream"
        provider = "shazam"

        initial_value = plays_inserted_total.labels(
            stream=stream, provider=provider
        )._value.get()

        record_play_inserted(stream, provider)

        new_value = plays_inserted_total.labels(
            stream=stream, provider=provider
        )._value.get()
        assert new_value == initial_value + 1

    def test_record_retention_deletes(self) -> None:
        """Test recording retention deletions."""
        table = "recognitions"
        count = 5

        initial_value = retention_deletes_total.labels(table=table)._value.get()

        record_retention_deletes(table, count)

        new_value = retention_deletes_total.labels(table=table)._value.get()
        assert new_value == initial_value + count

    def test_set_stream_active(self) -> None:
        """Test setting stream active status."""
        stream = "test_stream"

        # Set active
        set_stream_active(stream, True)
        active_value = streams_active.labels(stream=stream)._value.get()
        assert active_value == 1

        # Set inactive
        set_stream_active(stream, False)
        inactive_value = streams_active.labels(stream=stream)._value.get()
        assert inactive_value == 0

    def test_set_queue_depth(self) -> None:
        """Test setting queue depth."""
        queue_name = "recognition_queue"
        depth = 42

        set_queue_depth(queue_name, depth)

        queue_value = queue_depth.labels(name=queue_name)._value.get()
        assert queue_value == depth

    def test_set_retention_last_run(self) -> None:
        """Test setting retention last run timestamp."""
        job = "daily_cleanup"
        timestamp = 1234567890.0

        set_retention_last_run(job, timestamp)

        timestamp_value = retention_last_run_timestamp.labels(job=job)._value.get()
        assert timestamp_value == timestamp

    def test_set_embeddings_index_size(self) -> None:
        """Test setting embeddings index size."""
        size = 1000

        set_embeddings_index_size(size)

        size_value = embeddings_index_size._value.get()
        assert size_value == size

    def test_set_clustering_last_run(self) -> None:
        """Test setting clustering last run timestamp."""
        timestamp = 1234567890.0

        set_clustering_last_run(timestamp)

        timestamp_value = clustering_last_run_timestamp._value.get()
        assert timestamp_value == timestamp

    def test_histogram_observation(self) -> None:
        """Test histogram observations."""
        provider = "shazam"
        stream = "test_stream"
        latency = 2.5

        recognizer_latency_seconds.labels(provider=provider, stream=stream).observe(
            latency
        )

        # Check that the observation was recorded
        # Note: We can't easily check the exact value due to histogram internals
        # but we can verify the metric exists and has observations
        metric = recognizer_latency_seconds.labels(provider=provider, stream=stream)
        assert metric._sum.get() > 0
        # Histograms don't have _count attribute, but we can check _sum
        assert metric._sum.get() == latency

    def test_metrics_registry_contains_all_metrics(self) -> None:
        """Test that all metrics are registered in the Prometheus registry."""
        # Trigger creation of all metrics by using them
        record_ffmpeg_restart("test")
        record_recognition("shazam", "test", "success")
        record_play_inserted("test", "shazam")
        record_retention_deletes("test", 1)
        set_stream_active("test", True)
        set_queue_depth("test", 1)
        set_retention_last_run("test", 1234567890.0)
        set_embeddings_index_size(1)
        set_clustering_last_run(1234567890.0)

        # Now check registry - note that counters don't have _total suffix in registry
        metric_names = {
            "ffmpeg_restarts",
            "recognitions",
            "recognitions_success",
            "recognitions_failure",
            "plays_inserted",
            "retention_deletes",
            "recognizer_latency_seconds",
            "window_to_recognized_seconds",
            "ffmpeg_read_gap_seconds",
            "streams_active",
            "queue_depth",
            "retention_last_run_timestamp",
            "embeddings_index_size",
            "clustering_last_run_timestamp",
            "http_requests",
            "http_request_duration_seconds",
        }

        registered_names = {metric.name for metric in REGISTRY.collect()}

        for name in metric_names:
            assert name in registered_names, f"Metric {name} not found in registry"

    def test_metrics_labels_are_valid(self) -> None:
        """Test that metrics have valid label configurations."""
        # Test counter with labels - use a unique stream name to avoid conflicts
        counter = ffmpeg_restarts_total.labels(stream="unique_test_stream")
        assert counter._value.get() == 0

        # Test histogram with labels
        histogram = recognizer_latency_seconds.labels(
            provider="unique_test", stream="unique_test_stream"
        )
        assert histogram._sum.get() == 0
        # Histograms don't have _count attribute

        # Test gauge with labels
        gauge = streams_active.labels(stream="unique_test_stream")
        assert gauge._value.get() == 0

    def test_multiple_streams_metrics_isolation(self) -> None:
        """Test that metrics for different streams are isolated."""
        stream1 = "stream_1"
        stream2 = "stream_2"

        # Record metrics for different streams
        record_ffmpeg_restart(stream1)
        record_ffmpeg_restart(stream2)
        record_ffmpeg_restart(stream1)

        # Check isolation
        stream1_value = ffmpeg_restarts_total.labels(stream=stream1)._value.get()
        stream2_value = ffmpeg_restarts_total.labels(stream=stream2)._value.get()

        assert stream1_value == 2
        assert stream2_value == 1
