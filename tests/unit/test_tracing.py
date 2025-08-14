"""Tests for tracing module."""

import os
from unittest.mock import patch, MagicMock

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from app.tracing import (
    setup_tracing,
    get_tracer,
    trace_recognition,
    trace_ffmpeg_operation,
    trace_database_operation,
    trace_web_request,
    trace_background_job,
    RecognitionSpan,
    FFmpegSpan,
    DatabaseSpan,
)


class TestTracingSetup:
    """Test tracing setup functions."""
    
    def test_get_tracer(self) -> None:
        """Test getting a tracer."""
        # Setup basic tracing
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
        
        tracer = get_tracer("test_tracer")
        assert isinstance(tracer, trace.Tracer)
    
    @patch("app.tracing.OTLPSpanExporter")
    @patch("app.tracing.BatchSpanProcessor")
    def test_setup_tracing_with_endpoint(
        self,
        mock_batch_processor,
        mock_otlp_exporter,
    ) -> None:
        """Test tracing setup with OTLP endpoint."""
        endpoint = "http://jaeger:4317"
        
        setup_tracing(
            service_name="test-service",
            endpoint=endpoint,
            sample_rate=0.5,
            enable_fastapi=True,
            enable_aiohttp=True,
            enable_asyncio=True,
        )
        
        # Check that OTLP exporter was created
        mock_otlp_exporter.assert_called_once_with(endpoint=endpoint)
    
    @patch.dict(os.environ, {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://jaeger:4317"})
    def test_setup_tracing_from_env(self) -> None:
        """Test tracing setup using environment variable."""
        setup_tracing(
            service_name="test-service",
            sample_rate=1.0,
        )
        
        # Test that setup completes without errors
        assert True
    
    def test_setup_tracing_without_endpoint(self) -> None:
        """Test tracing setup without OTLP endpoint."""
        setup_tracing(
            service_name="test-service",
            endpoint=None,
            enable_fastapi=False,
            enable_aiohttp=False,
            enable_asyncio=False,
        )
        
        # Test that setup completes without errors
        assert True


class TestTracingHelpers:
    """Test tracing helper functions."""
    
    def setup_method(self) -> None:
        """Setup tracing for each test."""
        # Setup basic tracing for testing
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    
    def test_trace_recognition(self) -> None:
        """Test recognition tracing."""
        provider = "shazam"
        stream = "test_stream"
        window_start = "2023-01-01T12:00:00Z"
        
        span = trace_recognition(provider, stream, window_start)
        
        assert span is not None
        assert span.name == "recognition.attempt"
        span.end()
    
    def test_trace_ffmpeg_operation(self) -> None:
        """Test FFmpeg operation tracing."""
        operation = "start"
        stream = "test_stream"
        
        span = trace_ffmpeg_operation(
            operation=operation,
            stream=stream,
            url="rtsp://test.com/stream",
            pid=12345,
        )
        
        assert span is not None
        assert span.name == "ffmpeg.start"
        span.end()
    
    def test_trace_database_operation(self) -> None:
        """Test database operation tracing."""
        operation = "insert"
        table = "tracks"
        
        span = trace_database_operation(
            operation=operation,
            table=table,
            track_id=42,
        )
        
        assert span is not None
        assert span.name == "database.insert"
        span.end()
    
    def test_trace_web_request(self) -> None:
        """Test web request tracing."""
        method = "GET"
        endpoint = "/api/plays"
        
        span = trace_web_request(
            method=method,
            endpoint=endpoint,
            user_agent="test-agent",
        )
        
        assert span is not None
        assert span.name == "web.request"
        span.end()
    
    def test_trace_background_job(self) -> None:
        """Test background job tracing."""
        job_name = "retention_cleanup"
        
        span = trace_background_job(
            job_name=job_name,
            table="recognitions",
            deleted_count=150,
        )
        
        assert span is not None
        assert span.name == "background.retention_cleanup"
        span.end()


class TestTracingContextManagers:
    """Test tracing context managers."""
    
    def setup_method(self) -> None:
        """Setup tracing for each test."""
        # Setup basic tracing for testing
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    
    def test_recognition_span_success(self) -> None:
        """Test RecognitionSpan context manager success."""
        provider = "shazam"
        stream = "test_stream"
        window_start = "2023-01-01T12:00:00Z"
        
        with RecognitionSpan(provider, stream, window_start) as span:
            assert span is not None
            assert span.name == "recognition.attempt"
            span.set_attribute("test_attr", "test_value")
    
    def test_recognition_span_exception(self) -> None:
        """Test RecognitionSpan context manager with exception."""
        provider = "shazam"
        stream = "test_stream"
        window_start = "2023-01-01T12:00:00Z"
        
        with pytest.raises(ValueError):
            with RecognitionSpan(provider, stream, window_start) as span:
                assert span is not None
                raise ValueError("Test error")
    
    def test_ffmpeg_span_success(self) -> None:
        """Test FFmpegSpan context manager success."""
        operation = "start"
        stream = "test_stream"
        
        with FFmpegSpan(operation, stream, url="rtsp://test.com/stream") as span:
            assert span is not None
            assert span.name == "ffmpeg.start"
            span.set_attribute("pid", 12345)
    
    def test_ffmpeg_span_exception(self) -> None:
        """Test FFmpegSpan context manager with exception."""
        operation = "start"
        stream = "test_stream"
        
        with pytest.raises(RuntimeError):
            with FFmpegSpan(operation, stream) as span:
                assert span is not None
                raise RuntimeError("FFmpeg failed")
    
    def test_database_span_success(self) -> None:
        """Test DatabaseSpan context manager success."""
        operation = "insert"
        table = "tracks"
        
        with DatabaseSpan(operation, table, track_id=42) as span:
            assert span is not None
            assert span.name == "database.insert"
            span.set_attribute("success", True)
    
    def test_database_span_exception(self) -> None:
        """Test DatabaseSpan context manager with exception."""
        operation = "insert"
        table = "tracks"
        
        with pytest.raises(Exception):
            with DatabaseSpan(operation, table) as span:
                assert span is not None
                raise Exception("Database error")
