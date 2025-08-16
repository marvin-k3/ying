"""OpenTelemetry tracing setup for RTSP Music Tagger."""

import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

# Note: Instrumentation packages are not available in this version
# from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
# from opentelemetry.instrumentation.aiohttp import AioHttpClientInstrumentor
# from opentelemetry.instrumentation.asyncio import AsyncioInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# Note: Sampling configuration simplified for compatibility


def setup_tracing(
    service_name: str = "rtsp-music-tagger",
    endpoint: str | None = None,
    sample_rate: float = 1.0,
    enable_fastapi: bool = True,
    enable_aiohttp: bool = True,
    enable_asyncio: bool = True,
) -> None:
    """Setup OpenTelemetry tracing.

    Args:
        service_name: Name of the service for traces
        endpoint: OTLP endpoint URL (defaults to env var OTEL_EXPORTER_OTLP_ENDPOINT)
        sample_rate: Sampling rate (0.0 to 1.0)
        enable_fastapi: Whether to instrument FastAPI
        enable_aiohttp: Whether to instrument aiohttp
        enable_asyncio: Whether to instrument asyncio
    """
    # Get endpoint from environment if not provided
    if endpoint is None:
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")

    # Create resource with service information
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": "0.1.0",
            "deployment.environment": os.getenv("ENVIRONMENT", "development"),
        }
    )

    # Create tracer provider (simplified sampling for compatibility)
    provider = TracerProvider(
        resource=resource,
    )

    # Add OTLP exporter if endpoint is provided
    if endpoint:
        otlp_exporter = OTLPSpanExporter(endpoint=endpoint)
        provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

    # Set the global tracer provider
    trace.set_tracer_provider(provider)

    # Instrument libraries (disabled for now due to dependency issues)
    # if enable_fastapi:
    #     FastAPIInstrumentor.instrument()
    #
    # if enable_aiohttp:
    #     AioHttpClientInstrumentor.instrument()
    #
    # if enable_asyncio:
    #     AsyncioInstrumentor.instrument()


def get_tracer(name: str) -> trace.Tracer:
    """Get a tracer with the given name."""
    return trace.get_tracer(name)


# Convenience functions for common tracing patterns
def trace_recognition(
    provider: str,
    stream: str,
    window_start: str,
) -> trace.Span:
    """Create a span for a recognition attempt."""
    tracer = get_tracer("recognition")
    span = tracer.start_span(
        "recognition.attempt",
        attributes={
            "provider": provider,
            "stream": stream,
            "window_start": window_start,
        },
    )
    return span


def trace_ffmpeg_operation(
    operation: str,
    stream: str,
    **attributes: str,
) -> trace.Span:
    """Create a span for an FFmpeg operation."""
    tracer = get_tracer("ffmpeg")
    span = tracer.start_span(
        f"ffmpeg.{operation}",
        attributes={
            "stream": stream,
            **attributes,
        },
    )
    return span


def trace_database_operation(
    operation: str,
    table: str,
    **attributes: str,
) -> trace.Span:
    """Create a span for a database operation."""
    tracer = get_tracer("database")
    span = tracer.start_span(
        f"database.{operation}",
        attributes={
            "table": table,
            **attributes,
        },
    )
    return span


def trace_web_request(
    method: str,
    endpoint: str,
    **attributes: str,
) -> trace.Span:
    """Create a span for a web request."""
    tracer = get_tracer("web")
    span = tracer.start_span(
        "web.request",
        attributes={
            "http.method": method,
            "http.route": endpoint,
            **attributes,
        },
    )
    return span


def trace_background_job(
    job_name: str,
    **attributes: str,
) -> trace.Span:
    """Create a span for a background job."""
    tracer = get_tracer("background")
    span = tracer.start_span(
        f"background.{job_name}",
        attributes=attributes,
    )
    return span


# Context managers for automatic span management
class RecognitionSpan:
    """Context manager for recognition spans."""

    def __init__(
        self,
        provider: str,
        stream: str,
        window_start: str,
    ) -> None:
        self.provider = provider
        self.stream = stream
        self.window_start = window_start
        self.span: trace.Span | None = None

    def __enter__(self) -> trace.Span:
        self.span = trace_recognition(
            self.provider,
            self.stream,
            self.window_start,
        )
        return self.span

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        if self.span:
            if exc_type:
                self.span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc_val)))
            self.span.end()


class FFmpegSpan:
    """Context manager for FFmpeg operation spans."""

    def __init__(
        self,
        operation: str,
        stream: str,
        **attributes: str,
    ) -> None:
        self.operation = operation
        self.stream = stream
        self.attributes = attributes
        self.span: trace.Span | None = None

    def __enter__(self) -> trace.Span:
        self.span = trace_ffmpeg_operation(
            self.operation,
            self.stream,
            **self.attributes,
        )
        return self.span

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        if self.span:
            if exc_type:
                self.span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc_val)))
            self.span.end()


class DatabaseSpan:
    """Context manager for database operation spans."""

    def __init__(
        self,
        operation: str,
        table: str,
        **attributes: str,
    ) -> None:
        self.operation = operation
        self.table = table
        self.attributes = attributes
        self.span: trace.Span | None = None

    def __enter__(self) -> trace.Span:
        self.span = trace_database_operation(
            self.operation,
            self.table,
            **self.attributes,
        )
        return self.span

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        if self.span:
            if exc_type:
                self.span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc_val)))
            self.span.end()
