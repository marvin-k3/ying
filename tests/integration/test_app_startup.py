"""Integration tests for application startup and lifecycle."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import Config
from app.main import create_app


class TestAppStartup:
    """Test application startup and lifecycle."""

    def test_app_creation_succeeds(self):
        """Test that app can be created without errors."""
        app = create_app()
        assert app is not None
        assert app.title == "RTSP Music Tagger"

    @patch("app.main.WorkerManager")
    @patch("app.main.MigrationManager")
    def test_app_startup_lifecycle(
        self, mock_migration_manager_class, mock_worker_manager_class
    ):
        """Test full app startup lifecycle with mocked dependencies."""
        # Setup mocks
        mock_migration_manager = AsyncMock()
        mock_migration_manager.migrate_all.return_value = ["0001_init"]
        mock_migration_manager_class.return_value = mock_migration_manager

        mock_worker_manager = AsyncMock()
        mock_worker_manager.start_all.return_value = None
        mock_worker_manager.stop_all.return_value = None
        mock_worker_manager_class.return_value = mock_worker_manager

        with tempfile.TemporaryDirectory() as temp_dir:
            # Set environment variables for testing
            import os

            original_env = {}
            test_env = {
                "DB_PATH": str(Path(temp_dir) / "test.db"),
                "STREAM_COUNT": "1",
                "STREAM_1_NAME": "test_stream",
                "STREAM_1_URL": "rtsp://test.url",
                "STREAM_1_ENABLED": "false",  # Disable to avoid FFmpeg issues
                "LOG_LEVEL": "WARNING",  # Reduce log noise
            }

            # Save original env vars and set test ones
            for key, value in test_env.items():
                original_env[key] = os.environ.get(key)
                os.environ[key] = value

            try:
                # Test app startup
                app = create_app()

                with TestClient(app) as client:
                    # Test that the app starts successfully
                    response = client.get("/healthz")
                    assert response.status_code == 200
                    assert response.json() == {
                        "status": "healthy",
                        "service": "rtsp-music-tagger",
                    }

                    # Verify that the lifecycle methods were called
                    mock_migration_manager_class.assert_called_once()
                    mock_migration_manager.migrate_all.assert_called_once()
                    mock_worker_manager_class.assert_called_once()
                    mock_worker_manager.start_all.assert_called_once()

                # When the context manager exits, stop_all should be called
                mock_worker_manager.stop_all.assert_called_once()

            finally:
                # Restore original environment
                for key, original_value in original_env.items():
                    if original_value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = original_value

    def test_app_startup_with_real_database(self):
        """Test app startup with real database but disabled workers."""
        with tempfile.TemporaryDirectory() as temp_dir:
            import os

            original_env = {}
            test_env = {
                "DB_PATH": str(Path(temp_dir) / "test.db"),
                "STREAM_COUNT": "1",
                "STREAM_1_NAME": "test_stream",
                "STREAM_1_URL": "rtsp://test.url",
                "STREAM_1_ENABLED": "false",  # Disable streams to avoid FFmpeg
                "LOG_LEVEL": "ERROR",  # Minimize log output
            }

            for key, value in test_env.items():
                original_env[key] = os.environ.get(key)
                os.environ[key] = value

            try:
                app = create_app()

                # Mock only the worker manager to avoid FFmpeg issues
                with patch("app.main.WorkerManager") as mock_worker_manager_class:
                    mock_worker_manager = AsyncMock()
                    mock_worker_manager.start_all.return_value = None
                    mock_worker_manager.stop_all.return_value = None
                    mock_worker_manager_class.return_value = mock_worker_manager

                    with TestClient(app) as client:
                        # Test health endpoint
                        response = client.get("/healthz")
                        assert response.status_code == 200

                        # Test metrics endpoint
                        response = client.get("/metrics")
                        assert response.status_code == 200

                        # Test main page
                        response = client.get("/")
                        assert response.status_code == 200
                        assert "Day View" in response.text

                        # Test diagnostics page
                        response = client.get("/diagnostics")
                        assert response.status_code == 200
                        assert "Diagnostics" in response.text

            finally:
                for key, original_value in original_env.items():
                    if original_value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = original_value

    @patch("app.main.MigrationManager")
    def test_migration_error_handling(self, mock_migration_manager_class):
        """Test that migration errors are properly handled."""
        # Setup migration manager to raise an error
        mock_migration_manager = AsyncMock()
        mock_migration_manager.migrate_all.side_effect = Exception("Migration failed!")
        mock_migration_manager_class.return_value = mock_migration_manager

        with tempfile.TemporaryDirectory() as temp_dir:
            import os

            original_env = {}
            test_env = {
                "DB_PATH": str(Path(temp_dir) / "test.db"),
                "STREAM_COUNT": "1",
                "STREAM_1_NAME": "test_stream",
                "STREAM_1_URL": "rtsp://test.url",
                "STREAM_1_ENABLED": "false",
            }

            for key, value in test_env.items():
                original_env[key] = os.environ.get(key)
                os.environ[key] = value

            try:
                app = create_app()

                # This should raise an error during startup
                with pytest.raises(Exception) as exc_info:
                    with TestClient(app):
                        pass  # Should fail before we can make requests

                # The exception should bubble up from the migration
                assert "Migration failed!" in str(exc_info.value)

            finally:
                for key, original_value in original_env.items():
                    if original_value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = original_value

    @patch("app.main.WorkerManager")
    @patch("app.main.MigrationManager")
    def test_worker_manager_error_handling(
        self, mock_migration_manager_class, mock_worker_manager_class
    ):
        """Test that worker manager errors are properly handled."""
        # Setup mocks
        mock_migration_manager = AsyncMock()
        mock_migration_manager.migrate_all.return_value = ["0001_init"]
        mock_migration_manager_class.return_value = mock_migration_manager

        mock_worker_manager = AsyncMock()
        mock_worker_manager.start_all.side_effect = Exception("Worker startup failed!")
        mock_worker_manager_class.return_value = mock_worker_manager

        with tempfile.TemporaryDirectory() as temp_dir:
            import os

            original_env = {}
            test_env = {
                "DB_PATH": str(Path(temp_dir) / "test.db"),
                "STREAM_COUNT": "1",
                "STREAM_1_NAME": "test_stream",
                "STREAM_1_URL": "rtsp://test.url",
                "STREAM_1_ENABLED": "false",
            }

            for key, value in test_env.items():
                original_env[key] = os.environ.get(key)
                os.environ[key] = value

            try:
                app = create_app()

                # This should raise an error during startup
                with pytest.raises(Exception) as exc_info:
                    with TestClient(app):
                        pass  # Should fail before we can make requests

                assert "Worker startup failed!" in str(exc_info.value)

            finally:
                for key, original_value in original_env.items():
                    if original_value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = original_value


class TestMethodNameValidation:
    """Test that required methods exist with correct names."""

    def test_migration_manager_has_correct_methods(self):
        """Test that MigrationManager has the expected methods."""
        from app.db.migrate import MigrationManager

        # Create instance with dummy path
        manager = MigrationManager(Path("/tmp/test.db"))

        # Check that required methods exist
        assert hasattr(manager, "migrate_all"), (
            "MigrationManager should have migrate_all method"
        )
        assert callable(manager.migrate_all), (
            "migrate_all should be callable"
        )

        # Check that old method names don't exist
        assert not hasattr(manager, "apply_migrations"), (
            "Old method name apply_migrations should not exist"
        )

    def test_worker_manager_has_correct_methods(self):
        """Test that WorkerManager has the expected methods."""
        from app.config import Config
        from app.worker import WorkerManager

        # Create instance with minimal config
        config = Config()
        config.stream_count = 0  # No streams to avoid setup issues
        manager = WorkerManager(config)

        # Check that required methods exist
        assert hasattr(manager, "start_all"), (
            "WorkerManager should have start_all method"
        )
        assert callable(manager.start_all), "start_all should be callable"

        assert hasattr(manager, "stop_all"), "WorkerManager should have stop_all method"
        assert callable(manager.stop_all), "stop_all should be callable"

        # Check that old method names don't exist (if they were used)
        # Note: Individual workers have start/stop, but manager should have start_all/stop_all


class TestConfigValidation:
    """Test configuration validation and parsing."""

    def test_minimal_valid_config(self):
        """Test that minimal valid config can be loaded."""
        import os

        original_env = {}
        test_env = {
            "DB_PATH": "/tmp/test.db",
            "STREAM_COUNT": "1",
            "STREAM_1_NAME": "test",
            "STREAM_1_URL": "rtsp://test",
            "STREAM_1_ENABLED": "false",
        }

        for key, value in test_env.items():
            original_env[key] = os.environ.get(key)
            os.environ[key] = value

        try:
            config = Config()
            assert config.stream_count == 1
            assert len(config.streams) == 1
            assert config.streams[0].name == "test"
            assert config.streams[0].url == "rtsp://test"
            assert config.streams[0].enabled is False

        finally:
            for key, original_value in original_env.items():
                if original_value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = original_value

    def test_config_with_invalid_stream_count(self):
        """Test that invalid stream count raises validation error."""
        import os

        original_env = {}
        test_env = {
            "STREAM_COUNT": "0",  # Invalid - must be 1-5
        }

        for key, value in test_env.items():
            original_env[key] = os.environ.get(key)
            os.environ[key] = value

        try:
            with pytest.raises(ValueError):
                Config()

        finally:
            for key, original_value in original_env.items():
                if original_value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = original_value


if __name__ == "__main__":
    pytest.main([__file__])
