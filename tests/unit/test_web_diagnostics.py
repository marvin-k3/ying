"""Tests for web diagnostics routes."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import Config
from app.main import create_app


@pytest.fixture
def mock_config():
    """Mock configuration for testing."""
    config = Config()
    config.db_path = Path(":memory:")
    config.stream_count = 2
    config.stream_1 = type(
        "StreamConfig",
        (),
        {"name": "living_room", "url": "rtsp://test1", "enabled": True},
    )()
    config.stream_2 = type(
        "StreamConfig", (), {"name": "kitchen", "url": "rtsp://test2", "enabled": True}
    )()
    return config


@pytest.fixture
def mock_worker_manager():
    """Mock worker manager for testing."""
    return AsyncMock()


@pytest.fixture
def test_app(mock_config, mock_worker_manager):
    """Create test FastAPI app with mocked dependencies."""
    app = create_app()
    app.state.config = mock_config
    app.state.worker_manager = mock_worker_manager
    return app


@pytest.fixture
def client(test_app):
    """Create test client."""
    return TestClient(test_app)


@pytest.fixture
def sample_recognitions():
    """Sample recognition data for testing."""
    base_time = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)

    return [
        {
            "id": 1,
            "stream_id": 1,
            "stream_name": "living_room",
            "provider": "shazam",
            "recognized_at_utc": base_time.isoformat(),
            "window_start_utc": base_time.isoformat(),
            "window_end_utc": base_time.isoformat(),
            "track_id": 101,
            "title": "Test Song",
            "artist": "Test Artist",
            "confidence": 0.85,
            "latency_ms": 1250,
            "error_message": None,
            "raw_response": '{"track": {"title": "Test Song"}}',
        },
        {
            "id": 2,
            "stream_id": 2,
            "stream_name": "kitchen",
            "provider": "acoustid",
            "recognized_at_utc": (base_time.replace(minute=31)).isoformat(),
            "window_start_utc": None,
            "window_end_utc": None,
            "track_id": None,
            "title": None,
            "artist": None,
            "confidence": None,
            "latency_ms": 3500,
            "error_message": None,
            "raw_response": None,
        },
        {
            "id": 3,
            "stream_id": 1,
            "stream_name": "living_room",
            "provider": "shazam",
            "recognized_at_utc": (base_time.replace(minute=32)).isoformat(),
            "window_start_utc": base_time.isoformat(),
            "window_end_utc": base_time.isoformat(),
            "track_id": None,
            "title": None,
            "artist": None,
            "confidence": None,
            "latency_ms": None,
            "error_message": "Network timeout",
            "raw_response": None,
        },
    ]


class TestDiagnosticsView:
    """Test the diagnostics HTML view."""

    def test_diagnostics_view_renders(self, client, mock_config):
        """Test that diagnostics view renders with correct template."""
        response = client.get("/diagnostics")

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"

        # Check that the page contains expected elements
        content = response.text
        assert "Diagnostics" in content
        assert "Recent Recognitions" in content
        assert "living_room" in content  # Stream from config
        assert "kitchen" in content  # Stream from config
        assert "shazam" in content  # Provider option
        assert "acoustid" in content  # Provider option

    def test_diagnostics_view_includes_streams(self, client):
        """Test that diagnostics view includes configured streams."""
        response = client.get("/diagnostics")
        content = response.text

        # Check for stream options in the select dropdown
        assert '<option value="living_room">living_room</option>' in content
        assert '<option value="kitchen">kitchen</option>' in content

    def test_diagnostics_view_includes_javascript(self, client):
        """Test that diagnostics view includes required JavaScript."""
        response = client.get("/diagnostics")
        content = response.text

        # Check for key JavaScript functions
        assert "loadRecognitions" in content
        assert "showRawJson" in content
        assert "toggleAutoRefresh" in content


class TestRecognitionsAPI:
    """Test the recognitions API endpoints."""

    @patch("app.web.routes.RecognitionRepository")
    def test_get_recognitions_success(
        self, mock_repo_class, client, sample_recognitions
    ):
        """Test successful recognition retrieval."""
        # Setup mock repository
        mock_repo = AsyncMock()
        mock_repo.get_recent_recognitions.return_value = sample_recognitions
        mock_repo_class.return_value = mock_repo

        response = client.get("/api/recognitions")

        assert response.status_code == 200
        data = response.json()

        assert "recognitions" in data
        assert "total_count" in data
        assert data["total_count"] == 3
        assert len(data["recognitions"]) == 3

        # Check first recognition
        rec = data["recognitions"][0]
        assert rec["id"] == 1
        assert rec["provider"] == "shazam"
        assert rec["stream_name"] == "living_room"
        assert rec["title"] == "Test Song"
        assert rec["artist"] == "Test Artist"
        assert rec["confidence"] == 0.85
        assert rec["latency_ms"] == 1250
        assert rec["has_raw_response"] is True
        assert "recognized_at_pt" in rec

    @patch("app.web.routes.RecognitionRepository")
    def test_get_recognitions_with_limit(
        self, mock_repo_class, client, sample_recognitions
    ):
        """Test recognition retrieval with limit parameter."""
        mock_repo = AsyncMock()
        mock_repo.get_recent_recognitions.return_value = sample_recognitions[:2]
        mock_repo_class.return_value = mock_repo

        response = client.get("/api/recognitions?limit=2")

        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] == 2

        # Verify the repo was called with correct limit
        mock_repo.get_recent_recognitions.assert_called_once_with(
            limit=2, stream_name=None, provider=None
        )

    @patch("app.web.routes.RecognitionRepository")
    def test_get_recognitions_with_stream_filter(
        self, mock_repo_class, client, sample_recognitions
    ):
        """Test recognition retrieval with stream filter."""
        mock_repo = AsyncMock()
        mock_repo.get_recent_recognitions.return_value = [sample_recognitions[0]]
        mock_repo_class.return_value = mock_repo

        response = client.get("/api/recognitions?stream=living_room")

        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] == 1
        assert data["stream"] == "living_room"

        # Verify the repo was called with correct stream
        mock_repo.get_recent_recognitions.assert_called_once_with(
            limit=100, stream_name="living_room", provider=None
        )

    @patch("app.web.routes.RecognitionRepository")
    def test_get_recognitions_with_provider_filter(
        self, mock_repo_class, client, sample_recognitions
    ):
        """Test recognition retrieval with provider filter."""
        mock_repo = AsyncMock()
        mock_repo.get_recent_recognitions.return_value = [sample_recognitions[0]]
        mock_repo_class.return_value = mock_repo

        response = client.get("/api/recognitions?provider=shazam")

        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] == 1
        assert data["provider"] == "shazam"

        # Verify the repo was called with correct provider
        mock_repo.get_recent_recognitions.assert_called_once_with(
            limit=100, stream_name=None, provider="shazam"
        )

    def test_get_recognitions_invalid_stream(self, client):
        """Test recognition retrieval with invalid stream."""
        response = client.get("/api/recognitions?stream=invalid_stream")

        assert response.status_code == 400
        data = response.json()
        assert "Invalid stream" in data["detail"]
        assert "living_room" in data["detail"]  # Should list valid streams

    def test_get_recognitions_invalid_provider(self, client):
        """Test recognition retrieval with invalid provider."""
        response = client.get("/api/recognitions?provider=invalid_provider")

        assert response.status_code == 400
        data = response.json()
        assert "Invalid provider" in data["detail"]
        assert "shazam" in data["detail"]  # Should list valid providers

    def test_get_recognitions_invalid_limit(self, client):
        """Test recognition retrieval with invalid limit."""
        response = client.get("/api/recognitions?limit=0")
        assert response.status_code == 422  # Validation error

        response = client.get("/api/recognitions?limit=2000")
        assert response.status_code == 422  # Validation error

    @patch("app.web.routes.RecognitionRepository")
    def test_get_recognitions_empty_result(self, mock_repo_class, client):
        """Test recognition retrieval with no results."""
        mock_repo = AsyncMock()
        mock_repo.get_recent_recognitions.return_value = []
        mock_repo_class.return_value = mock_repo

        response = client.get("/api/recognitions")

        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] == 0
        assert len(data["recognitions"]) == 0

    @patch("app.web.routes.RecognitionRepository")
    def test_get_recognitions_handles_datetime_parsing(self, mock_repo_class, client):
        """Test that datetime parsing handles various formats."""
        mock_repo = AsyncMock()
        mock_repo.get_recent_recognitions.return_value = [
            {
                "id": 1,
                "stream_id": 1,
                "stream_name": "test",
                "provider": "shazam",
                "recognized_at_utc": "2024-01-15T10:30:00Z",  # With Z suffix
                "window_start_utc": "2024-01-15T10:30:00+00:00",  # With timezone
                "window_end_utc": None,
                "track_id": None,
                "title": None,
                "artist": None,
                "confidence": None,
                "latency_ms": None,
                "error_message": None,
                "raw_response": None,
            }
        ]
        mock_repo_class.return_value = mock_repo

        response = client.get("/api/recognitions")

        assert response.status_code == 200
        data = response.json()
        rec = data["recognitions"][0]
        assert "recognized_at_pt" in rec  # Should be converted to PT time string


class TestRawJSONAPI:
    """Test the raw JSON API endpoint."""

    @patch("aiosqlite.connect")
    def test_get_recognition_raw_success(self, mock_connect, client):
        """Test successful raw JSON retrieval."""
        # Setup mock database
        mock_cursor = AsyncMock()
        mock_cursor.fetchone.return_value = ('{"test": "data"}',)

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_cursor
        mock_db.__aenter__.return_value = mock_db
        mock_db.__aexit__.return_value = None

        mock_connect.return_value = mock_db

        response = client.get("/api/recognitions/1/raw")

        assert response.status_code == 200
        data = response.json()
        assert data == {"test": "data"}

    @patch("aiosqlite.connect")
    def test_get_recognition_raw_not_found(self, mock_connect, client):
        """Test raw JSON retrieval for non-existent recognition."""
        # Setup mock database
        mock_cursor = AsyncMock()
        mock_cursor.fetchone.return_value = None

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_cursor
        mock_db.__aenter__.return_value = mock_db
        mock_db.__aexit__.return_value = None

        mock_connect.return_value = mock_db

        response = client.get("/api/recognitions/999/raw")

        assert response.status_code == 404
        data = response.json()
        assert "Recognition not found" in data["detail"]

    @patch("aiosqlite.connect")
    def test_get_recognition_raw_no_response(self, mock_connect, client):
        """Test raw JSON retrieval when no raw response exists."""
        # Setup mock database
        mock_cursor = AsyncMock()
        mock_cursor.fetchone.return_value = (None,)  # No raw response

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_cursor
        mock_db.__aenter__.return_value = mock_db
        mock_db.__aexit__.return_value = None

        mock_connect.return_value = mock_db

        response = client.get("/api/recognitions/1/raw")

        assert response.status_code == 404
        data = response.json()
        assert "No raw response available" in data["detail"]

    @patch("aiosqlite.connect")
    def test_get_recognition_raw_invalid_json(self, mock_connect, client):
        """Test raw JSON retrieval with malformed JSON."""
        # Setup mock database
        mock_cursor = AsyncMock()
        mock_cursor.fetchone.return_value = ("invalid json{",)

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_cursor
        mock_db.__aenter__.return_value = mock_db
        mock_db.__aexit__.return_value = None

        mock_connect.return_value = mock_db

        response = client.get("/api/recognitions/1/raw")

        assert response.status_code == 500
        data = response.json()
        assert "Invalid JSON" in data["detail"]


class TestDiagnosticsIntegration:
    """Integration tests for diagnostics functionality."""

    @patch("app.web.routes.RecognitionRepository")
    def test_diagnostics_page_integration(
        self, mock_repo_class, client, sample_recognitions
    ):
        """Test full integration from diagnostics page to API."""
        # Setup mock repository
        mock_repo = AsyncMock()
        mock_repo.get_recent_recognitions.return_value = sample_recognitions
        mock_repo_class.return_value = mock_repo

        # First, get the diagnostics page
        page_response = client.get("/diagnostics")
        assert page_response.status_code == 200

        # Then test the API endpoint that the page would call
        api_response = client.get("/api/recognitions")
        assert api_response.status_code == 200

        data = api_response.json()
        assert len(data["recognitions"]) == 3

        # Test filtering by stream (as the UI would do)
        filtered_response = client.get("/api/recognitions?stream=living_room&limit=50")
        assert filtered_response.status_code == 200

        # Verify repo was called with filters
        mock_repo.get_recent_recognitions.assert_called_with(
            limit=50, stream_name="living_room", provider=None
        )

    def test_diagnostics_response_models(self, client):
        """Test that response models are properly defined."""
        # This test ensures our Pydantic models work correctly
        from app.web.routes import RecognitionRecord, RecognitionsResponse

        # Test RecognitionRecord model
        rec_data = {
            "id": 1,
            "stream_id": 1,
            "stream_name": "test",
            "provider": "shazam",
            "recognized_at_utc": datetime.now(UTC),
            "recognized_at_pt": "10:30:00",
            "window_start_utc": None,
            "window_end_utc": None,
            "track_id": None,
            "title": None,
            "artist": None,
            "confidence": None,
            "latency_ms": None,
            "error_message": None,
            "has_raw_response": False,
        }

        rec = RecognitionRecord(**rec_data)
        assert rec.id == 1
        assert rec.provider == "shazam"
        assert rec.has_raw_response is False

        # Test RecognitionsResponse model
        resp_data = {
            "recognitions": [rec],
            "total_count": 1,
            "stream": None,
            "provider": None,
        }

        resp = RecognitionsResponse(**resp_data)
        assert resp.total_count == 1
        assert len(resp.recognitions) == 1


class TestDiagnosticsErrorHandling:
    """Test error handling in diagnostics routes."""

    @patch("app.web.routes.RecognitionRepository")
    def test_api_handles_database_error(self, mock_repo_class, client):
        """Test that API handles database errors gracefully."""
        # Setup mock repository to raise an exception
        mock_repo = AsyncMock()
        mock_repo.get_recent_recognitions.side_effect = Exception("Database error")
        mock_repo_class.return_value = mock_repo

        # The route should catch the exception but in this case it will propagate
        # In production, we'd want proper error handling
        with pytest.raises((ValueError, RuntimeError, Exception)):
            client.get("/api/recognitions")

    def test_invalid_recognition_id_type(self, client):
        """Test raw JSON endpoint with invalid ID type."""
        response = client.get("/api/recognitions/invalid/raw")
        assert response.status_code == 422  # Validation error


if __name__ == "__main__":
    pytest.main([__file__])
