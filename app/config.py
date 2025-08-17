"""Configuration management for ying RTSP music tagger."""

from typing import Any

from pydantic import BaseModel, Field, computed_field, field_validator
from pydantic_settings import BaseSettings


class StreamConfig(BaseModel):
    """Configuration for a single RTSP stream."""

    name: str = Field(..., pattern=r"^[a-zA-Z0-9_-]+$", min_length=1, max_length=50)
    url: str = Field(..., pattern=r"^rtsps?://.*$")
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate stream name format."""
        if not v:
            raise ValueError("Stream name cannot be empty")
        if len(v) > 50:
            raise ValueError("Stream name too long")
        return v

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate RTSP URL format."""
        if not v.startswith(("rtsp://", "rtsps://")):
            raise ValueError("URL must be RTSP or RTSP over SSL protocol")
        return v


class Config(BaseSettings):
    """Main application configuration."""

    # Core settings
    port: int = Field(default=44100, ge=1024, le=65535)
    db_path: str = Field(default="/data/plays.db")
    timezone: str = Field(default="America/Los_Angeles")

    # Stream configuration
    stream_count: int = Field(default=5, gt=0, le=5)

    # Windowing and deduplication
    window_seconds: int = Field(default=12, gt=0, le=300)  # Allow up to 5 minutes
    hop_seconds: int = Field(default=120, gt=0)
    dedup_seconds: int = Field(default=300, gt=0)

    # Decision policy
    decision_policy: str = Field(default="shazam_two_hit")
    two_hit_hop_tolerance: int = Field(default=1, ge=0, le=10)

    # Retention settings
    retain_plays_days: int = Field(default=-1, ge=-1)
    retain_recognitions_days: int = Field(default=30, gt=0)
    retention_cleanup_localtime: str = Field(
        default="04:00", pattern=r"^([01]?[0-9]|2[0-3]):[0-5][0-9]$"
    )

    # Provider settings
    acoustid_enabled: bool = Field(default=False)
    acoustid_api_key: str = Field(default="")
    chromaprint_path: str = Field(default="/usr/bin/fpcalc")

    # Logging and tracing
    log_level: str = Field(default="INFO")
    structured_logs: bool = Field(default=True)
    otel_service_name: str = Field(default="ying")
    otel_exporter_otlp_endpoint: str = Field(default="http://jaeger:4317")
    otel_traces_sampler_arg: float = Field(default=1.0, ge=0.0, le=1.0)

    # Prometheus metrics
    enable_prometheus: bool = Field(default=True)
    metrics_path: str = Field(default="/metrics")

    # Queue and backpressure
    global_max_inflight_recognitions: int = Field(default=3, gt=0)
    per_provider_max_inflight: int = Field(default=3, gt=0)
    queue_max_size: int = Field(default=500, gt=0)

    # Clustering and embeddings
    clusters_enabled: bool = Field(default=True)
    embed_model: str = Field(default="sentence-transformers/all-MiniLM-L6-v2")
    embed_model_revision: str = Field(default="main")
    embed_device: str = Field(default="cpu")

    # Internal settings
    streams: list[StreamConfig] = Field(default_factory=list)

    @field_validator("retain_plays_days")
    @classmethod
    def validate_retain_plays_days(cls, v: int) -> int:
        """Validate retention days for plays."""
        if v != -1 and v <= 0:
            raise ValueError("Input should be -1 or greater than 0")
        return v

    @field_validator("hop_seconds")
    @classmethod
    def validate_hop_seconds(cls, v: int, info: Any) -> int:
        """Validate hop seconds is greater than window seconds."""
        if "window_seconds" in info.data and v <= info.data["window_seconds"]:
            raise ValueError("hop_seconds must be greater than window_seconds")
        return v

    @field_validator("decision_policy")
    @classmethod
    def validate_decision_policy(cls, v: str) -> str:
        """Validate decision policy."""
        valid_policies = ["shazam_two_hit"]
        if v not in valid_policies:
            raise ValueError(f"Decision policy must be one of: {valid_policies}")
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of: {valid_levels}")
        return v.upper()

    @field_validator("embed_device")
    @classmethod
    def validate_embed_device(cls, v: str) -> str:
        """Validate embedding device."""
        valid_devices = ["cpu", "cuda", "mps"]
        if v.lower() not in valid_devices:
            raise ValueError(f"Embed device must be one of: {valid_devices}")
        return v.lower()

    @computed_field
    def enabled_streams(self) -> list[StreamConfig]:
        """Get only enabled streams."""
        return [stream for stream in self.streams if stream.enabled]

    def model_post_init(self, __context: Any) -> None:
        """Post-initialization to parse stream configuration."""
        self._parse_stream_config()

    def _parse_stream_config(self) -> None:
        """Parse stream configuration from environment variables."""
        streams = []

        # Get environment variables directly
        import os

        for i in range(1, self.stream_count + 1):
            name_key = f"STREAM_{i}_NAME"
            url_key = f"STREAM_{i}_URL"
            enabled_key = f"STREAM_{i}_ENABLED"

            # Try to get from os.environ first (for backward compatibility)
            name = os.environ.get(name_key, f"stream_{i}")
            url = os.environ.get(url_key, "")
            enabled_str = os.environ.get(enabled_key, "true")

            # Parse boolean
            enabled = self._parse_boolean(enabled_str)

            if url:  # Only add if URL is provided
                streams.append(StreamConfig(name=name, url=url, enabled=enabled))

        self.streams = streams

    def _parse_boolean(self, value: str) -> bool:
        """Parse boolean from string."""
        return value.lower() in ("true", "1", "yes", "on")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "allow",  # Allow extra fields for stream parsing
    }
