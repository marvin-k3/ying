"""Pytest configuration for integration tests."""

import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def disable_tracing():
    """Disable tracing for all integration tests to avoid connection errors."""
    # Save original environment variables
    original_otel_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    original_otel_console = os.environ.get("OTEL_CONSOLE_EXPORTER")

    # Disable tracing
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = ""
    os.environ["OTEL_CONSOLE_EXPORTER"] = "false"

    yield

    # Restore original environment variables
    if original_otel_endpoint is None:
        os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    else:
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = original_otel_endpoint

    if original_otel_console is None:
        os.environ.pop("OTEL_CONSOLE_EXPORTER", None)
    else:
        os.environ["OTEL_CONSOLE_EXPORTER"] = original_otel_console
