"""Tests for FastAPI middleware."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.middleware import MetricsMiddleware
from app.metrics import http_requests_total, http_request_duration_seconds


class TestMetricsMiddleware:
    """Test metrics middleware."""
    
    def test_middleware_records_metrics(self) -> None:
        """Test that middleware records HTTP metrics."""
        app = FastAPI()
        app.add_middleware(MetricsMiddleware)
        
        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}
        
        client = TestClient(app)
        
        # Get initial metric values
        initial_requests = http_requests_total.labels(
            method="GET", endpoint="/test", status="200"
        )._value.get()
        
        initial_duration_sum = http_request_duration_seconds.labels(
            method="GET", endpoint="/test"
        )._sum.get()
        
        # Make request
        response = client.get("/test")
        assert response.status_code == 200
        
        # Check that metrics were recorded
        new_requests = http_requests_total.labels(
            method="GET", endpoint="/test", status="200"
        )._value.get()
        
        new_duration_sum = http_request_duration_seconds.labels(
            method="GET", endpoint="/test"
        )._sum.get()
        
        assert new_requests == initial_requests + 1
        assert new_duration_sum > initial_duration_sum
    
    def test_middleware_records_error_metrics(self) -> None:
        """Test that middleware records error metrics."""
        app = FastAPI()
        app.add_middleware(MetricsMiddleware)
        
        @app.get("/error")
        def error_endpoint():
            raise ValueError("Test error")
        
        client = TestClient(app)
        
        # Get initial metric values
        initial_requests = http_requests_total.labels(
            method="GET", endpoint="/error", status="500"
        )._value.get()
        
        # Make request (should raise exception)
        try:
            response = client.get("/error")
        except Exception:
            # Expected to fail
            pass
        
        # Check that error metrics were recorded
        new_requests = http_requests_total.labels(
            method="GET", endpoint="/error", status="500"
        )._value.get()
        
        assert new_requests == initial_requests + 1
    
    def test_middleware_records_different_methods(self) -> None:
        """Test that middleware records different HTTP methods."""
        app = FastAPI()
        app.add_middleware(MetricsMiddleware)
        
        @app.get("/test")
        def get_endpoint():
            return {"method": "GET"}
        
        @app.post("/test")
        def post_endpoint():
            return {"method": "POST"}
        
        client = TestClient(app)
        
        # Make requests
        get_response = client.get("/test")
        post_response = client.post("/test")
        
        assert get_response.status_code == 200
        assert post_response.status_code == 200
        
        # Check that both methods were recorded
        get_requests = http_requests_total.labels(
            method="GET", endpoint="/test", status="200"
        )._value.get()
        
        post_requests = http_requests_total.labels(
            method="POST", endpoint="/test", status="200"
        )._value.get()
        
        assert get_requests >= 1
        assert post_requests >= 1
    
    def test_middleware_records_duration(self) -> None:
        """Test that middleware records request duration."""
        import time
        
        app = FastAPI()
        app.add_middleware(MetricsMiddleware)
        
        @app.get("/slow")
        def slow_endpoint():
            time.sleep(0.1)  # Simulate slow request
            return {"message": "slow"}
        
        client = TestClient(app)
        
        # Get initial duration metrics
        initial_sum = http_request_duration_seconds.labels(
            method="GET", endpoint="/slow"
        )._sum.get()
        
        # Make request
        response = client.get("/slow")
        assert response.status_code == 200
        
        # Check that duration was recorded
        new_sum = http_request_duration_seconds.labels(
            method="GET", endpoint="/slow"
        )._sum.get()
        
        assert new_sum > initial_sum  # Should have recorded some duration
    
    @patch("app.middleware.trace_web_request")
    def test_middleware_creates_trace_span(self, mock_trace_web_request) -> None:
        """Test that middleware creates trace spans."""
        app = FastAPI()
        app.add_middleware(MetricsMiddleware)
        
        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}
        
        client = TestClient(app)
        
        # Mock the trace context manager
        mock_context = mock_trace_web_request.return_value.__enter__.return_value
        
        # Make request
        response = client.get("/test")
        assert response.status_code == 200
        
        # Check that trace span was created
        mock_trace_web_request.assert_called_once_with(
            method="GET", endpoint="/test"
        )
