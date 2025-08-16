"""FastAPI middleware for metrics and tracing."""

import time
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from .metrics import http_request_duration_seconds, http_requests_total
from .tracing import trace_web_request


class MetricsMiddleware(BaseHTTPMiddleware):
    """Middleware to collect HTTP metrics."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and collect metrics."""
        start_time = time.time()
        status_code = 500  # Default to error status

        try:
            # Create trace span
            with trace_web_request(
                method=request.method,
                endpoint=request.url.path,
            ):
                response = await call_next(request)
                status_code = response.status_code
        except Exception:
            # Record metrics for failed requests
            duration = time.time() - start_time

            http_requests_total.labels(
                method=request.method,
                endpoint=request.url.path,
                status=str(status_code),
            ).inc()

            http_request_duration_seconds.labels(
                method=request.method,
                endpoint=request.url.path,
            ).observe(duration)

            raise

        # Record metrics for successful requests
        duration = time.time() - start_time

        http_requests_total.labels(
            method=request.method,
            endpoint=request.url.path,
            status=str(status_code),
        ).inc()

        http_request_duration_seconds.labels(
            method=request.method,
            endpoint=request.url.path,
        ).observe(duration)

        return response
