"""Tests for logging setup module."""

import json
import logging
import sys
from datetime import datetime
from io import StringIO
from unittest.mock import patch, MagicMock

import pytest
from opentelemetry import trace
from opentelemetry.trace import SpanContext, TraceFlags

from app.logging_setup import (
    StructuredFormatter,
    setup_logging,
    get_logger,
    log_recognition_attempt,
    log_ffmpeg_event,
    log_play_confirmed,
    log_retention_job,
    log_clustering_job,
)


class TestStructuredFormatter:
    """Test structured JSON formatter."""
    
    def test_format_basic_log_record(self) -> None:
        """Test basic log record formatting."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        
        result = formatter.format(record)
        log_entry = json.loads(result)
        
        assert log_entry["level"] == "INFO"
        assert log_entry["logger"] == "test_logger"
        assert log_entry["message"] == "Test message"
        assert "timestamp" in log_entry
    
    def test_format_with_exception(self) -> None:
        """Test formatting with exception info."""
        formatter = StructuredFormatter()
        
        try:
            raise ValueError("Test exception")
        except ValueError:
            record = logging.LogRecord(
                name="test_logger",
                level=logging.ERROR,
                pathname="test.py",
                lineno=42,
                msg="Error occurred",
                args=(),
                exc_info=sys.exc_info(),
            )
        
        result = formatter.format(record)
        log_entry = json.loads(result)
        
        assert log_entry["level"] == "ERROR"
        assert log_entry["message"] == "Error occurred"
        assert "exception" in log_entry
        assert "ValueError: Test exception" in log_entry["exception"]
    
    def test_format_with_extra_fields(self) -> None:
        """Test formatting with extra fields."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.custom_field = "custom_value"
        record.number_field = 42
        
        result = formatter.format(record)
        log_entry = json.loads(result)
        
        assert log_entry["custom_field"] == "custom_value"
        assert log_entry["number_field"] == 42
    
    @patch("app.logging_setup.trace.get_current_span")
    def test_format_with_trace_correlation(self, mock_get_span) -> None:
        """Test formatting with trace correlation."""
        # Mock span context
        mock_span = MagicMock()
        mock_span.get_span_context.return_value = SpanContext(
            trace_id=0x1234567890abcdef1234567890abcdef,
            span_id=0x1234567890abcdef,
            is_remote=False,
            trace_flags=TraceFlags(1),
        )
        mock_get_span.return_value = mock_span
        
        formatter = StructuredFormatter(include_trace=True)
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        
        result = formatter.format(record)
        log_entry = json.loads(result)
        
        assert log_entry["trace_id"] == "1234567890abcdef1234567890abcdef"
        assert log_entry["span_id"] == "1234567890abcdef"
    
    @patch("app.logging_setup.trace.get_current_span")
    def test_format_without_trace_correlation(self, mock_get_span) -> None:
        """Test formatting without trace correlation."""
        formatter = StructuredFormatter(include_trace=False)
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        
        result = formatter.format(record)
        log_entry = json.loads(result)
        
        assert "trace_id" not in log_entry
        assert "span_id" not in log_entry


class TestLoggingSetup:
    """Test logging setup functions."""
    
    def test_setup_logging_structured(self) -> None:
        """Test structured logging setup."""
        # Capture log output
        log_output = StringIO()
        
        with patch("sys.stdout", log_output):
            setup_logging(level="INFO", structured=True, include_trace=False)
            
            logger = logging.getLogger("test_logger")
            logger.info("Test message", extra={"test_field": "test_value"})
        
        # Check that output is valid JSON
        output_lines = log_output.getvalue().strip().split("\n")
        assert len(output_lines) >= 2  # Startup message + our message
        
        # Parse the last line (our message)
        log_entry = json.loads(output_lines[-1])
        assert log_entry["level"] == "INFO"
        assert log_entry["message"] == "Test message"
        assert log_entry["test_field"] == "test_value"
    
    def test_setup_logging_unstructured(self) -> None:
        """Test unstructured logging setup."""
        log_output = StringIO()
        
        with patch("sys.stdout", log_output):
            setup_logging(level="INFO", structured=False)
            
            logger = logging.getLogger("test_logger")
            logger.info("Test message")
        
        output = log_output.getvalue()
        assert "Test message" in output
        assert "INFO" in output
        # Should not be JSON
        assert not output.strip().startswith("{")
    
    def test_get_logger(self) -> None:
        """Test getting a logger."""
        logger = get_logger("test_logger")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_logger"


class TestLoggingHelpers:
    """Test logging helper functions."""
    
    def test_log_recognition_attempt_success(self) -> None:
        """Test logging successful recognition attempt."""
        log_output = StringIO()
        
        with patch("sys.stdout", log_output):
            setup_logging(level="INFO", structured=True, include_trace=False)
            
            logger = logging.getLogger("test_logger")
            window_start = datetime(2023, 1, 1, 12, 0, 0)
            
            log_recognition_attempt(
                logger=logger,
                provider="shazam",
                stream="test_stream",
                window_start=window_start,
                duration=2.5,
                success=True,
                track_info={"title": "Test Song", "artist": "Test Artist"},
            )
        
        output_lines = log_output.getvalue().strip().split("\n")
        log_entry = json.loads(output_lines[-1])
        
        assert log_entry["level"] == "INFO"
        assert log_entry["message"] == "Recognition successful"
        assert log_entry["provider"] == "shazam"
        assert log_entry["stream"] == "test_stream"
        assert log_entry["duration_seconds"] == 2.5
        assert log_entry["success"] is True
        assert log_entry["track_info"]["title"] == "Test Song"
        assert log_entry["track_info"]["artist"] == "Test Artist"
    
    def test_log_recognition_attempt_failure(self) -> None:
        """Test logging failed recognition attempt."""
        log_output = StringIO()
        
        with patch("sys.stdout", log_output):
            setup_logging(level="INFO", structured=True, include_trace=False)
            
            logger = logging.getLogger("test_logger")
            window_start = datetime(2023, 1, 1, 12, 0, 0)
            
            log_recognition_attempt(
                logger=logger,
                provider="shazam",
                stream="test_stream",
                window_start=window_start,
                duration=5.0,
                success=False,
                error="Timeout",
            )
        
        output_lines = log_output.getvalue().strip().split("\n")
        log_entry = json.loads(output_lines[-1])
        
        assert log_entry["level"] == "WARNING"
        assert log_entry["message"] == "Recognition failed"
        assert log_entry["success"] is False
        assert log_entry["error"] == "Timeout"
    
    def test_log_ffmpeg_event(self) -> None:
        """Test logging FFmpeg event."""
        log_output = StringIO()
        
        with patch("sys.stdout", log_output):
            setup_logging(level="INFO", structured=True, include_trace=False)
            
            logger = logging.getLogger("test_logger")
            
            log_ffmpeg_event(
                logger=logger,
                stream="test_stream",
                event="started",
                details={"pid": 12345, "url": "rtsp://test.com/stream"},
            )
        
        output_lines = log_output.getvalue().strip().split("\n")
        log_entry = json.loads(output_lines[-1])
        
        assert log_entry["level"] == "INFO"
        assert log_entry["message"] == "FFmpeg started"
        assert log_entry["stream"] == "test_stream"
        assert log_entry["event"] == "started"
        assert log_entry["pid"] == 12345
        assert log_entry["url"] == "rtsp://test.com/stream"
    
    def test_log_play_confirmed(self) -> None:
        """Test logging confirmed play."""
        log_output = StringIO()
        
        with patch("sys.stdout", log_output):
            setup_logging(level="INFO", structured=True, include_trace=False)
            
            logger = logging.getLogger("test_logger")
            window_start = datetime(2023, 1, 1, 12, 0, 0)
            
            log_play_confirmed(
                logger=logger,
                stream="test_stream",
                track_title="Test Song",
                track_artist="Test Artist",
                provider="shazam",
                confidence=0.95,
                window_start=window_start,
            )
        
        output_lines = log_output.getvalue().strip().split("\n")
        log_entry = json.loads(output_lines[-1])
        
        assert log_entry["level"] == "INFO"
        assert log_entry["message"] == "Play confirmed"
        assert log_entry["stream"] == "test_stream"
        assert log_entry["track_title"] == "Test Song"
        assert log_entry["track_artist"] == "Test Artist"
        assert log_entry["provider"] == "shazam"
        assert log_entry["confidence"] == 0.95
    
    def test_log_retention_job(self) -> None:
        """Test logging retention job."""
        log_output = StringIO()
        
        with patch("sys.stdout", log_output):
            setup_logging(level="INFO", structured=True, include_trace=False)
            
            logger = logging.getLogger("test_logger")
            
            log_retention_job(
                logger=logger,
                job="daily_cleanup",
                table="recognitions",
                deleted_count=150,
                duration=5.2,
            )
        
        output_lines = log_output.getvalue().strip().split("\n")
        log_entry = json.loads(output_lines[-1])
        
        assert log_entry["level"] == "INFO"
        assert log_entry["message"] == "Retention job completed"
        assert log_entry["job"] == "daily_cleanup"
        assert log_entry["table"] == "recognitions"
        assert log_entry["deleted_count"] == 150
        assert log_entry["duration_seconds"] == 5.2
    
    def test_log_clustering_job(self) -> None:
        """Test logging clustering job."""
        log_output = StringIO()
        
        with patch("sys.stdout", log_output):
            setup_logging(level="INFO", structured=True, include_trace=False)
            
            logger = logging.getLogger("test_logger")
            
            log_clustering_job(
                logger=logger,
                tracks_processed=1000,
                clusters_found=25,
                duration=30.5,
            )
        
        output_lines = log_output.getvalue().strip().split("\n")
        log_entry = json.loads(output_lines[-1])
        
        assert log_entry["level"] == "INFO"
        assert log_entry["message"] == "Clustering job completed"
        assert log_entry["tracks_processed"] == 1000
        assert log_entry["clusters_found"] == 25
        assert log_entry["duration_seconds"] == 30.5
