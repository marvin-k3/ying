"""Structured logging setup for RTSP Music Tagger."""

import json
import logging
import sys
from datetime import datetime
from typing import Any, Dict, Optional

from opentelemetry import trace


class StructuredFormatter(logging.Formatter):
    """JSON formatter with trace correlation."""

    def __init__(self, include_trace: bool = True) -> None:
        super().__init__()
        self.include_trace = include_trace

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON with trace correlation."""
        # Get current span context
        span_context = trace.get_current_span().get_span_context()
        
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Add trace correlation if enabled and span is valid
        if self.include_trace and span_context.is_valid:
            log_entry["trace_id"] = format(span_context.trace_id, "032x")
            log_entry["span_id"] = format(span_context.span_id, "016x")
        
        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields from record
        for key, value in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "lineno", "funcName", "created",
                "msecs", "relativeCreated", "thread", "threadName",
                "processName", "process", "getMessage", "exc_info",
                "exc_text", "stack_info"
            }:
                log_entry[key] = value
        
        return json.dumps(log_entry, default=str)


def setup_logging(
    level: str = "INFO",
    structured: bool = True,
    include_trace: bool = True,
) -> None:
    """Setup structured logging with trace correlation.
    
    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        structured: Whether to use JSON formatting
        include_trace: Whether to include trace correlation
    """
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    
    if structured:
        console_handler.setFormatter(StructuredFormatter(include_trace=include_trace))
    else:
        console_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
        )
    
    root_logger.addHandler(console_handler)
    
    # Set specific logger levels
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    
    # Log startup message
    logger = logging.getLogger(__name__)
    logger.info(
        "Logging initialized",
        extra={
            "level": level,
            "structured": structured,
            "include_trace": include_trace,
        }
    )


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the given name."""
    return logging.getLogger(name)


# Convenience functions for common logging patterns
def log_recognition_attempt(
    logger: logging.Logger,
    provider: str,
    stream: str,
    window_start: datetime,
    duration: float,
    success: bool,
    error: Optional[str] = None,
    track_info: Optional[Dict[str, Any]] = None,
) -> None:
    """Log a recognition attempt with structured data."""
    extra = {
        "provider": provider,
        "stream": stream,
        "window_start": window_start.isoformat(),
        "duration_seconds": duration,
        "success": success,
    }
    
    if error:
        extra["error"] = error
    
    if track_info:
        extra["track_info"] = track_info
    
    if success:
        logger.info("Recognition successful", extra=extra)
    else:
        logger.warning("Recognition failed", extra=extra)


def log_ffmpeg_event(
    logger: logging.Logger,
    stream: str,
    event: str,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Log an FFmpeg-related event."""
    extra = {
        "stream": stream,
        "event": event,
    }
    
    if details:
        extra.update(details)
    
    logger.info(f"FFmpeg {event}", extra=extra)


def log_play_confirmed(
    logger: logging.Logger,
    stream: str,
    track_title: str,
    track_artist: str,
    provider: str,
    confidence: float,
    window_start: datetime,
) -> None:
    """Log a confirmed play."""
    logger.info(
        "Play confirmed",
        extra={
            "stream": stream,
            "track_title": track_title,
            "track_artist": track_artist,
            "provider": provider,
            "confidence": confidence,
            "window_start": window_start.isoformat(),
        }
    )


def log_retention_job(
    logger: logging.Logger,
    job: str,
    table: str,
    deleted_count: int,
    duration: float,
) -> None:
    """Log a retention job execution."""
    logger.info(
        "Retention job completed",
        extra={
            "job": job,
            "table": table,
            "deleted_count": deleted_count,
            "duration_seconds": duration,
        }
    )


def log_clustering_job(
    logger: logging.Logger,
    tracks_processed: int,
    clusters_found: int,
    duration: float,
) -> None:
    """Log a clustering job execution."""
    logger.info(
        "Clustering job completed",
        extra={
            "tracks_processed": tracks_processed,
            "clusters_found": clusters_found,
            "duration_seconds": duration,
        }
    )
