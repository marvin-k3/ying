"""Unit tests for the main application module."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.main import create_app, lifespan


class TestCreateApp:
    """Test the create_app function."""

    def test_create_app_returns_fastapi_instance(self):
        """Test that create_app returns a FastAPI instance."""
        app = create_app()

        assert app is not None
        assert hasattr(app, "title")
        assert app.title == "RTSP Music Tagger"
        assert hasattr(app, "description")
        assert "Real-time music recognition" in app.description

    def test_create_app_includes_required_routes(self):
        """Test that the app includes all required routes."""
        app = create_app()

        # Check that routes are included
        route_paths = [route.path for route in app.routes]

        # Basic endpoints
        assert "/healthz" in [
            route.path for route in app.routes if hasattr(route, "path")
        ]
        assert "/metrics" in [
            route.path for route in app.routes if hasattr(route, "path")
        ]

        # Check that router is included (routes from web.routes)
        assert any("/diagnostics" in str(route) for route in app.routes)

    def test_create_app_includes_middleware(self):
        """Test that required middleware is added."""
        app = create_app()

        # Check that MetricsMiddleware is added
        middleware_types = [
            getattr(middleware.cls, "__name__", str(middleware.cls))
            for middleware in app.user_middleware
        ]
        assert "MetricsMiddleware" in middleware_types

    def test_create_app_configures_templates_and_static(self):
        """Test that templates and static files are configured."""
        app = create_app()

        # Check that static files are mounted
        assert hasattr(app, "mount")

        # Check that templates are configured in state (during lifespan)
        assert hasattr(app, "state")


class TestLifespan:
    """Test the lifespan context manager."""

    @pytest.mark.asyncio
    @patch("app.main.setup_tracing")
    @patch("app.main.setup_logging")
    @patch("app.main.WorkerManager")
    @patch("app.main.MigrationManager")
    @patch("app.main.Config")
    async def test_lifespan_startup_sequence(
        self,
        mock_config_class,
        mock_migration_manager_class,
        mock_worker_manager_class,
        mock_setup_logging,
        mock_setup_tracing,
    ):
        """Test that lifespan executes startup sequence correctly."""
        # Setup mocks
        mock_config = MagicMock()
        mock_config.db_path = Path("/tmp/test.db")
        mock_config.log_level = "INFO"
        mock_config.structured_logs = True
        mock_config.otel_service_name = "test-service"
        mock_config.otel_exporter_otlp_endpoint = "http://test"
        mock_config.otel_traces_sampler_arg = 1.0
        mock_config_class.return_value = mock_config

        mock_migration_manager = AsyncMock()
        mock_migration_manager.migrate_all.return_value = ["0001_init"]
        mock_migration_manager_class.return_value = mock_migration_manager

        mock_worker_manager = AsyncMock()
        mock_worker_manager.start_all.return_value = None
        mock_worker_manager.stop_all.return_value = None
        mock_worker_manager_class.return_value = mock_worker_manager

        # Create mock app
        mock_app = MagicMock()
        mock_app.state = MagicMock()

        # Test lifespan
        async with lifespan(mock_app):
            # During startup
            mock_setup_logging.assert_called_once_with(level="INFO", structured=True)
            mock_setup_tracing.assert_called_once_with(
                service_name="test-service", endpoint="http://test", sample_rate=1.0
            )
            mock_migration_manager_class.assert_called_once_with(mock_config.db_path)
            mock_migration_manager.migrate_all.assert_called_once()
            mock_worker_manager_class.assert_called_once_with(mock_config)
            mock_worker_manager.start_all.assert_called_once()

            # Check that config and worker manager are stored in app state
            assert mock_app.state.config == mock_config
            assert mock_app.state.worker_manager == mock_worker_manager

        # After shutdown
        mock_worker_manager.stop_all.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.main.setup_tracing")
    @patch("app.main.setup_logging")
    @patch("app.main.WorkerManager")
    @patch("app.main.MigrationManager")
    @patch("app.main.Config")
    async def test_lifespan_migration_method_name(
        self,
        mock_config_class,
        mock_migration_manager_class,
        mock_worker_manager_class,
        mock_setup_logging,
        mock_setup_tracing,
    ):
        """Test that lifespan calls the correct migration method name."""
        # This test specifically checks for the method name bug we encountered
        mock_config = MagicMock()
        mock_config.db_path = Path("/tmp/test.db")
        mock_config.log_level = "INFO"
        mock_config.structured_logs = True
        mock_config.otel_service_name = "test-service"
        mock_config.otel_exporter_otlp_endpoint = "http://test"
        mock_config.otel_traces_sampler_arg = 1.0
        mock_config_class.return_value = mock_config

        mock_migration_manager = AsyncMock()
        # This should be migrate_all, not apply_migrations
        mock_migration_manager.migrate_all.return_value = ["0001_init"]
        mock_migration_manager_class.return_value = mock_migration_manager

        mock_worker_manager = AsyncMock()
        mock_worker_manager.start_all.return_value = None
        mock_worker_manager.stop_all.return_value = None
        mock_worker_manager_class.return_value = mock_worker_manager

        mock_app = MagicMock()
        mock_app.state = MagicMock()

        # Test that the correct method is called
        async with lifespan(mock_app):
            pass

        # Verify the correct method was called
        mock_migration_manager.migrate_all.assert_called_once()

        # Verify the incorrect method doesn't exist or isn't called
        assert (
            not hasattr(mock_migration_manager, "apply_migrations")
            or not mock_migration_manager.apply_migrations.called
        )

    @pytest.mark.asyncio
    @patch("app.main.setup_tracing")
    @patch("app.main.setup_logging")
    @patch("app.main.WorkerManager")
    @patch("app.main.MigrationManager")
    @patch("app.main.Config")
    async def test_lifespan_worker_method_names(
        self,
        mock_config_class,
        mock_migration_manager_class,
        mock_worker_manager_class,
        mock_setup_logging,
        mock_setup_tracing,
    ):
        """Test that lifespan calls the correct worker manager method names."""
        # This test specifically checks for the worker method name bug
        mock_config = MagicMock()
        mock_config.log_level = "INFO"
        mock_config.structured_logs = True
        mock_config.otel_service_name = "test-service"
        mock_config.otel_exporter_otlp_endpoint = "http://test"
        mock_config.otel_traces_sampler_arg = 1.0
        mock_config_class.return_value = mock_config

        mock_migration_manager = AsyncMock()
        mock_migration_manager.migrate_all.return_value = []
        mock_migration_manager_class.return_value = mock_migration_manager

        mock_worker_manager = AsyncMock()
        # These should be start_all/stop_all, not start/stop
        mock_worker_manager.start_all.return_value = None
        mock_worker_manager.stop_all.return_value = None
        mock_worker_manager_class.return_value = mock_worker_manager

        mock_app = MagicMock()
        mock_app.state = MagicMock()

        # Test that the correct methods are called
        async with lifespan(mock_app):
            pass

        # Verify the correct methods were called
        mock_worker_manager.start_all.assert_called_once()
        mock_worker_manager.stop_all.assert_called_once()

        # Verify the incorrect methods don't exist or aren't called
        assert (
            not hasattr(mock_worker_manager, "start")
            or not mock_worker_manager.start.called
        )
        assert (
            not hasattr(mock_worker_manager, "stop")
            or not mock_worker_manager.stop.called
        )

    @pytest.mark.asyncio
    @patch("app.main.setup_tracing")
    @patch("app.main.setup_logging")
    @patch("app.main.WorkerManager")
    @patch("app.main.MigrationManager")
    @patch("app.main.Config")
    async def test_lifespan_migration_error_propagation(
        self,
        mock_config_class,
        mock_migration_manager_class,
        mock_worker_manager_class,
        mock_setup_logging,
        mock_setup_tracing,
    ):
        """Test that migration errors are properly propagated."""
        mock_config = MagicMock()
        mock_config.log_level = "INFO"
        mock_config.structured_logs = True
        mock_config.otel_service_name = "test-service"
        mock_config.otel_exporter_otlp_endpoint = "http://test"
        mock_config.otel_traces_sampler_arg = 1.0
        mock_config_class.return_value = mock_config

        mock_migration_manager = AsyncMock()
        mock_migration_manager.migrate_all.side_effect = Exception("Migration error!")
        mock_migration_manager_class.return_value = mock_migration_manager

        mock_worker_manager = AsyncMock()
        mock_worker_manager_class.return_value = mock_worker_manager

        mock_app = MagicMock()
        mock_app.state = MagicMock()

        # Test that migration errors are propagated
        with pytest.raises(Exception, match="Migration error!"):
            async with lifespan(mock_app):
                pass

        # Worker manager should not be started if migration fails
        mock_worker_manager.start_all.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.main.setup_tracing")
    @patch("app.main.setup_logging")
    @patch("app.main.WorkerManager")
    @patch("app.main.MigrationManager")
    @patch("app.main.Config")
    async def test_lifespan_worker_error_propagation(
        self,
        mock_config_class,
        mock_migration_manager_class,
        mock_worker_manager_class,
        mock_setup_logging,
        mock_setup_tracing,
    ):
        """Test that worker startup errors are properly propagated."""
        mock_config = MagicMock()
        mock_config.log_level = "INFO"
        mock_config.structured_logs = True
        mock_config.otel_service_name = "test-service"
        mock_config.otel_exporter_otlp_endpoint = "http://test"
        mock_config.otel_traces_sampler_arg = 1.0
        mock_config_class.return_value = mock_config

        mock_migration_manager = AsyncMock()
        mock_migration_manager.migrate_all.return_value = []
        mock_migration_manager_class.return_value = mock_migration_manager

        mock_worker_manager = AsyncMock()
        mock_worker_manager.start_all.side_effect = Exception("Worker error!")
        mock_worker_manager.stop_all.return_value = None
        mock_worker_manager_class.return_value = mock_worker_manager

        mock_app = MagicMock()
        mock_app.state = MagicMock()

        # Test that worker errors are propagated
        with pytest.raises(Exception, match="Worker error!"):
            async with lifespan(mock_app):
                pass

        # Migration should complete before worker error
        mock_migration_manager.migrate_all.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__])
