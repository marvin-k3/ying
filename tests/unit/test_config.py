"""Tests for app.config module."""

import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.config import Config, StreamConfig


class TestStreamConfig:
    """Test StreamConfig validation."""

    def test_valid_stream_config(self) -> None:
        """Test valid stream configuration."""
        config = StreamConfig(
            name="living_room",
            url="rtsp://user:pass@192.168.1.100:554/stream1",
            enabled=True,
        )
        assert config.name == "living_room"
        assert config.url == "rtsp://user:pass@192.168.1.100:554/stream1"
        assert config.enabled is True

    def test_stream_name_validation(self) -> None:
        """Test stream name validation."""
        # Valid names
        StreamConfig(name="living_room", url="rtsp://test", enabled=True)
        StreamConfig(name="yard-cam", url="rtsp://test", enabled=True)
        StreamConfig(name="cam1", url="rtsp://test", enabled=True)

        # Invalid names
        with pytest.raises(
            ValidationError, match="String should have at least 1 character"
        ):
            StreamConfig(name="", url="rtsp://test", enabled=True)

        with pytest.raises(ValidationError, match="String should match pattern"):
            StreamConfig(name="invalid name", url="rtsp://test", enabled=True)

        with pytest.raises(ValidationError, match="String should match pattern"):
            StreamConfig(name="name with spaces", url="rtsp://test", enabled=True)

    def test_rtsp_url_validation(self) -> None:
        """Test RTSP URL validation."""
        # Valid URLs
        StreamConfig(name="test", url="rtsp://192.168.1.100:554/stream", enabled=True)
        StreamConfig(
            name="test", url="rtsp://user:pass@192.168.1.100:554/stream", enabled=True
        )
        c = StreamConfig(name="test", url="rtsp://localhost/stream", enabled=True)
        assert c.url == "rtsp://localhost/stream"
        c = StreamConfig(name="test", url="rtsps://192.168.1.100:7441/rEdAcTedCoDe?enableSrtp", enabled=True)
        assert c.url == "rtsps://192.168.1.100:7441/rEdAcTedCoDe?enableSrtp"

        # Invalid URLs
        with pytest.raises(ValidationError, match="String should match pattern"):
            StreamConfig(name="test", url="http://test.com", enabled=True)

        with pytest.raises(ValidationError, match="String should match pattern"):
            StreamConfig(name="test", url="", enabled=True)


class TestConfig:
    """Test Config validation and defaults."""

    @pytest.fixture
    def minimal_env(self) -> dict[str, str]:
        """Minimal environment variables for testing."""
        return {
            "DB_PATH": "/data/plays.db",
            "TZ": "America/Los_Angeles",
        }

    def test_defaults(self, minimal_env: dict[str, str]) -> None:
        """Test default values when env vars not set."""
        # Clear all environment variables to test true defaults
        with patch.dict(os.environ, {}, clear=True):
            # Mock the model_config to not load .env file
            with patch.object(Config, 'model_config', {
                "env_file": None,
                "env_file_encoding": "utf-8",
                "case_sensitive": False,
                "extra": "allow",
            }):
                config = Config()

                assert config.port == 44100
                assert config.db_path == "/data/plays.db"
                assert config.timezone == "America/Los_Angeles"
                assert config.stream_count == 5
                assert config.window_seconds == 12
                assert config.hop_seconds == 120
                assert config.dedup_seconds == 300
                assert config.decision_policy == "shazam_two_hit"
                assert config.two_hit_hop_tolerance == 1
                assert config.retain_plays_days == -1
                assert config.retain_recognitions_days == 30
                assert config.retention_cleanup_localtime == "04:00"
                assert config.acoustid_enabled is True
                assert config.log_level == "INFO"
                assert config.structured_logs is True
                assert config.enable_prometheus is True
                assert config.metrics_path == "/metrics"
                assert config.global_max_inflight_recognitions == 3
                assert config.per_provider_max_inflight == 3
                assert config.queue_max_size == 500
                assert config.clusters_enabled is True
                assert config.embed_model == "sentence-transformers/all-MiniLM-L6-v2"
                assert config.embed_device == "cpu"

    def test_stream_config_parsing(self, minimal_env: dict[str, str]) -> None:
        """Test parsing of stream configuration from environment."""
        env = minimal_env.copy()
        env.update(
            {
                "STREAM_COUNT": "2",
                "STREAM_1_NAME": "living_room",
                "STREAM_1_URL": "rtsp://user:pass@192.168.1.100:554/stream1",
                "STREAM_1_ENABLED": "true",
                "STREAM_2_NAME": "yard",
                "STREAM_2_URL": "rtsp://user:pass@192.168.1.101:554/stream2",
                "STREAM_2_ENABLED": "false",
            }
        )

        with patch.dict(os.environ, env, clear=True):
            config = Config()

            assert len(config.streams) == 2
            assert config.streams[0].name == "living_room"
            assert config.streams[0].url == "rtsp://user:pass@192.168.1.100:554/stream1"
            assert config.streams[0].enabled is True
            assert config.streams[1].name == "yard"
            assert config.streams[1].url == "rtsp://user:pass@192.168.1.101:554/stream2"
            assert config.streams[1].enabled is False

    def test_stream_count_bounds(self, minimal_env: dict[str, str]) -> None:
        """Test stream count validation bounds."""
        # Test minimum bound
        env = minimal_env.copy()
        env["STREAM_COUNT"] = "0"
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValidationError, match="Input should be greater than 0"):
                Config()

        # Test maximum bound
        env = minimal_env.copy()
        env["STREAM_COUNT"] = "6"
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(
                ValidationError, match="Input should be less than or equal to 5"
            ):
                Config()

    def test_window_hop_validation(self, minimal_env: dict[str, str]) -> None:
        """Test window and hop seconds validation."""
        # Valid: hop > window
        env = minimal_env.copy()
        env.update(
            {
                "WINDOW_SECONDS": "12",
                "HOP_SECONDS": "120",
            }
        )
        with patch.dict(os.environ, env, clear=True):
            config = Config()
            assert config.window_seconds == 12
            assert config.hop_seconds == 120

        # Invalid: hop <= window
        env = minimal_env.copy()
        env.update(
            {
                "WINDOW_SECONDS": "120",
                "HOP_SECONDS": "12",
            }
        )
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(
                ValidationError, match="hop_seconds must be greater than window_seconds"
            ):
                Config()

    def test_retention_validation(self, minimal_env: dict[str, str]) -> None:
        """Test retention configuration validation."""
        # Valid: -1 means keep forever
        env = minimal_env.copy()
        env["RETAIN_PLAYS_DAYS"] = "-1"
        with patch.dict(os.environ, env, clear=True):
            config = Config()
            assert config.retain_plays_days == -1

        # Valid: positive number
        env = minimal_env.copy()
        env["RETAIN_PLAYS_DAYS"] = "30"
        with patch.dict(os.environ, env, clear=True):
            config = Config()
            assert config.retain_plays_days == 30

        # Invalid: negative but not -1
        env = minimal_env.copy()
        env["RETAIN_PLAYS_DAYS"] = "-5"
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(
                ValidationError, match="Input should be greater than or equal to -1"
            ):
                Config()

    def test_time_validation(self, minimal_env: dict[str, str]) -> None:
        """Test time format validation."""
        # Valid times
        valid_times = ["00:00", "04:00", "12:30", "23:59"]
        for time_str in valid_times:
            env = minimal_env.copy()
            env["RETENTION_CLEANUP_LOCALTIME"] = time_str
            with patch.dict(os.environ, env, clear=True):
                config = Config()
                assert config.retention_cleanup_localtime == time_str

        # Invalid times
        invalid_times = ["24:00", "12:60", "25:00", "12:61", "invalid"]
        for time_str in invalid_times:
            env = minimal_env.copy()
            env["RETENTION_CLEANUP_LOCALTIME"] = time_str
            with patch.dict(os.environ, env, clear=True):
                with pytest.raises(
                    ValidationError, match="String should match pattern"
                ):
                    Config()

    def test_boolean_parsing(self, minimal_env: dict[str, str]) -> None:
        """Test boolean environment variable parsing."""
        boolean_fields = [
            "acoustid_enabled",
            "structured_logs",
            "enable_prometheus",
            "clusters_enabled",
        ]

        for field in boolean_fields:
            env_var = field.upper()

            # Test true values
            for true_val in ["true", "True", "TRUE", "1", "yes", "on"]:
                env = minimal_env.copy()
                env[env_var] = true_val
                with patch.dict(os.environ, env, clear=True):
                    config = Config()
                    assert getattr(config, field) is True

            # Test false values
            for false_val in ["false", "False", "FALSE", "0", "no", "off"]:
                env = minimal_env.copy()
                env[env_var] = false_val
                with patch.dict(os.environ, env, clear=True):
                    config = Config()
                    assert getattr(config, field) is False

    def test_otel_config(self, minimal_env: dict[str, str]) -> None:
        """Test OpenTelemetry configuration."""
        env = minimal_env.copy()
        env.update(
            {
                "OTEL_SERVICE_NAME": "ying-test",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://jaeger:4317",
                "OTEL_TRACES_SAMPLER_ARG": "0.5",
            }
        )

        with patch.dict(os.environ, env, clear=True):
            config = Config()
            assert config.otel_service_name == "ying-test"
            assert config.otel_exporter_otlp_endpoint == "http://jaeger:4317"
            assert config.otel_traces_sampler_arg == 0.5

    def test_enabled_streams_property(self, minimal_env: dict[str, str]) -> None:
        """Test enabled_streams property returns only enabled streams."""
        env = minimal_env.copy()
        env.update(
            {
                "STREAM_COUNT": "3",
                "STREAM_1_NAME": "stream1",
                "STREAM_1_URL": "rtsp://test1",
                "STREAM_1_ENABLED": "true",
                "STREAM_2_NAME": "stream2",
                "STREAM_2_URL": "rtsp://test2",
                "STREAM_2_ENABLED": "false",
                "STREAM_3_NAME": "stream3",
                "STREAM_3_URL": "rtsp://test3",
                "STREAM_3_ENABLED": "true",
            }
        )

        with patch.dict(os.environ, env, clear=True):
            config = Config()
            enabled = config.enabled_streams

            assert len(enabled) == 2
            assert enabled[0].name == "stream1"
            assert enabled[1].name == "stream3"
