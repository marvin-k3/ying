"""Regression tests to demonstrate catching the startup errors we encountered."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.main import lifespan


class TestStartupRegressionCases:
    """Tests that would have caught the startup errors we encountered."""
    
    @pytest.mark.asyncio
    async def test_wrong_migration_method_name_error(self):
        """Test that using wrong migration method name would be caught."""
        # This test demonstrates what would happen if we had the wrong method name
        
        with patch('app.main.Config') as mock_config_class, \
             patch('app.main.MigrationManager') as mock_migration_manager_class, \
             patch('app.main.WorkerManager') as mock_worker_manager_class, \
             patch('app.main.setup_logging'), \
             patch('app.main.setup_tracing'):
            
            # Setup config mock
            mock_config = MagicMock()
            mock_config.log_level = "INFO"
            mock_config.structured_logs = True
            mock_config.otel_service_name = "test"
            mock_config.otel_exporter_otlp_endpoint = "http://test"
            mock_config.otel_traces_sampler_arg = 1.0
            mock_config_class.return_value = mock_config
            
            # Setup migration manager with WRONG method name (this is the bug)
            mock_migration_manager = AsyncMock()
            # Don't add migrate_all method - simulate the old wrong name
            delattr(mock_migration_manager, 'migrate_all')
            mock_migration_manager.apply_migrations.return_value = ["0001_init"]  # Wrong method name
            mock_migration_manager_class.return_value = mock_migration_manager
            
            # Setup worker manager
            mock_worker_manager = AsyncMock()
            mock_worker_manager.start_all.return_value = None
            mock_worker_manager.stop_all.return_value = None
            mock_worker_manager_class.return_value = mock_worker_manager
            
            mock_app = MagicMock()
            mock_app.state = MagicMock()
            
            # This should raise AttributeError because migrate_all doesn't exist
            with pytest.raises(AttributeError, match="migrate_all"):
                async with lifespan(mock_app):
                    pass
    
    @pytest.mark.asyncio
    async def test_wrong_worker_method_name_error(self):
        """Test that using wrong worker method names would be caught."""
        # This test demonstrates what would happen if we had the wrong worker method names
        
        with patch('app.main.Config') as mock_config_class, \
             patch('app.main.MigrationManager') as mock_migration_manager_class, \
             patch('app.main.WorkerManager') as mock_worker_manager_class, \
             patch('app.main.setup_logging'), \
             patch('app.main.setup_tracing'):
            
            # Setup config mock
            mock_config = MagicMock()
            mock_config.log_level = "INFO"
            mock_config.structured_logs = True
            mock_config.otel_service_name = "test"
            mock_config.otel_exporter_otlp_endpoint = "http://test"
            mock_config.otel_traces_sampler_arg = 1.0
            mock_config_class.return_value = mock_config
            
            # Setup migration manager correctly
            mock_migration_manager = AsyncMock()
            mock_migration_manager.migrate_all.return_value = ["0001_init"]
            mock_migration_manager_class.return_value = mock_migration_manager
            
            # Setup worker manager with WRONG method names (this is the bug)
            mock_worker_manager = AsyncMock()
            # Don't add start_all/stop_all methods - simulate the old wrong names
            delattr(mock_worker_manager, 'start_all')
            delattr(mock_worker_manager, 'stop_all')
            mock_worker_manager.start.return_value = None  # Wrong method name
            mock_worker_manager.stop.return_value = None   # Wrong method name
            mock_worker_manager_class.return_value = mock_worker_manager
            
            mock_app = MagicMock()
            mock_app.state = MagicMock()
            
            # This should raise AttributeError because start_all doesn't exist
            with pytest.raises(AttributeError, match="start_all"):
                async with lifespan(mock_app):
                    pass
    
    def test_migration_manager_interface_validation(self):
        """Test that verifies MigrationManager has the correct interface."""
        from app.db.migrate import MigrationManager
        
        # Create a temporary instance to check its interface
        manager = MigrationManager(Path("/tmp/test.db"))
        
        # Verify the correct method exists
        assert hasattr(manager, 'migrate_all'), "MigrationManager must have migrate_all method"
        assert callable(getattr(manager, 'migrate_all')), "migrate_all must be callable"
        
        # Verify old incorrect method names don't exist
        assert not hasattr(manager, 'apply_migrations'), \
            "MigrationManager should not have old apply_migrations method"
    
    def test_worker_manager_interface_validation(self):
        """Test that verifies WorkerManager has the correct interface."""
        from app.worker import WorkerManager
        from app.config import Config
        
        # Create a minimal config for testing
        config = Config()
        config.stream_count = 0  # No streams to avoid complex setup
        manager = WorkerManager(config)
        
        # Verify the correct methods exist
        assert hasattr(manager, 'start_all'), "WorkerManager must have start_all method"
        assert callable(getattr(manager, 'start_all')), "start_all must be callable"
        
        assert hasattr(manager, 'stop_all'), "WorkerManager must have stop_all method"
        assert callable(getattr(manager, 'stop_all')), "stop_all must be callable"
        
        # Individual workers have start/stop, but manager should have start_all/stop_all
        # (This test would catch if we confused the interfaces)


class TestMethodNameDocumentation:
    """Document the correct method names to prevent future confusion."""
    
    def test_migration_manager_correct_method_name(self):
        """Document: MigrationManager should use migrate_all(), not apply_migrations()."""
        from app.db.migrate import MigrationManager
        
        manager = MigrationManager(Path("/tmp/test.db"))
        
        # The CORRECT method name
        assert hasattr(manager, 'migrate_all')
        
        # Common WRONG method names that might be confused
        wrong_names = ['apply_migrations', 'run_migrations', 'execute_migrations']
        for wrong_name in wrong_names:
            assert not hasattr(manager, wrong_name), f"Should not have {wrong_name} method"
    
    def test_worker_manager_correct_method_names(self):
        """Document: WorkerManager should use start_all()/stop_all(), not start()/stop()."""
        from app.worker import WorkerManager
        from app.config import Config
        
        config = Config()
        config.stream_count = 0
        manager = WorkerManager(config)
        
        # The CORRECT method names for WorkerManager
        assert hasattr(manager, 'start_all')
        assert hasattr(manager, 'stop_all')
        
        # Note: Individual StreamWorker instances have start()/stop()
        # But WorkerManager (which manages multiple workers) has start_all()/stop_all()
        # This test documents this distinction to prevent future confusion


if __name__ == "__main__":
    pytest.main([__file__])
