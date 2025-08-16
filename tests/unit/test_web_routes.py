"""Tests for app.web.routes module."""

import csv
import io
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytz
from fastapi.testclient import TestClient

from app.config import Config, StreamConfig
from app.main import create_app
from app.web.routes import convert_utc_to_pt, get_pt_date_today


class TestUtilityFunctions:
    """Test utility functions."""

    def test_convert_utc_to_pt(self) -> None:
        """Test UTC to Pacific Time conversion."""
        # Test naive datetime (treated as UTC)
        utc_dt = datetime(2024, 1, 15, 20, 30, 45)  # 8:30:45 PM UTC
        pt_str = convert_utc_to_pt(utc_dt)
        assert pt_str == "12:30:45"  # 12:30:45 PM PST

        # Test timezone-aware datetime
        utc_tz = pytz.UTC
        utc_dt_aware = utc_tz.localize(
            datetime(2024, 7, 15, 20, 30, 45)
        )  # Summer (PDT)
        pt_str = convert_utc_to_pt(utc_dt_aware)
        assert pt_str == "13:30:45"  # 1:30:45 PM PDT

    def test_get_pt_date_today(self) -> None:
        """Test getting today's date in Pacific Time."""
        with patch("app.web.routes.datetime") as mock_datetime:
            # Mock PT datetime
            pt_tz = pytz.timezone("America/Los_Angeles")
            mock_pt_dt = pt_tz.localize(datetime(2024, 1, 15, 10, 30, 0))
            mock_datetime.now.return_value = mock_pt_dt

            today = get_pt_date_today()
            assert today == date(2024, 1, 15)
            mock_datetime.now.assert_called_once_with(pt_tz)


class TestWebRoutes:
    """Test web routes with TestClient."""

    @pytest.fixture
    def app_config(self) -> Config:
        """Create test configuration."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = Path(tmp.name)

        # Mock config with test streams
        config = Config()
        config.db_path = db_path
        config.stream_count = 3
        config.stream_1 = StreamConfig(
            name="living_room", url="rtsp://test1", enabled=True
        )
        config.stream_2 = StreamConfig(name="kitchen", url="rtsp://test2", enabled=True)
        config.stream_3 = StreamConfig(name="yard", url="rtsp://test3", enabled=False)

        return config

    @pytest.fixture
    def test_client(self, app_config: Config) -> TestClient:
        """Create test client with mocked dependencies."""
        app = create_app()

        # Override lifespan to avoid actual startup
        app.router.lifespan_context = None

        # Mock app state
        app.state.config = app_config
        app.state.worker_manager = AsyncMock()

        return TestClient(app)

    @pytest.fixture
    def sample_plays_data(self) -> list[dict[str, Any]]:
        """Sample plays data for testing."""
        return [
            {
                "id": 1,
                "track_id": 101,
                "stream_id": 1,
                "recognized_at_utc": datetime(2024, 1, 15, 20, 30, 0),
                "dedup_bucket": 12345,
                "confidence": 0.95,
                "title": "Bohemian Rhapsody",
                "artist": "Queen",
                "album": "A Night at the Opera",
                "artwork_url": "https://example.com/art1.jpg",
                "stream_name": "living_room",
            },
            {
                "id": 2,
                "track_id": 102,
                "stream_id": 2,
                "recognized_at_utc": datetime(2024, 1, 15, 21, 0, 0),
                "dedup_bucket": 12346,
                "confidence": 0.87,
                "title": "Hotel California",
                "artist": "Eagles",
                "album": "Hotel California",
                "artwork_url": None,
                "stream_name": "kitchen",
            },
        ]

    def test_health_check(self, test_client: TestClient) -> None:
        """Test health check endpoint."""
        response = test_client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "rtsp-music-tagger"

    @patch("app.web.routes.get_pt_date_today")
    def test_day_view_page(self, mock_get_today, test_client: TestClient) -> None:
        """Test day view HTML page."""
        mock_get_today.return_value = date(2024, 1, 15)

        response = test_client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

        # Check that template contains expected content
        content = response.text
        assert "RTSP Music Tagger" in content
        assert "Day View" in content
        assert "2024-01-15" in content  # Today's date
        assert "living_room" in content  # Enabled stream
        assert "kitchen" in content  # Enabled stream
        assert "yard" not in content  # Disabled stream

    @patch("app.web.routes.PlayRepository")
    async def test_get_plays_json_success(
        self,
        mock_repo_class,
        test_client: TestClient,
        sample_plays_data: list[dict[str, Any]],
    ) -> None:
        """Test successful JSON plays API response."""
        # Mock repository
        mock_repo = AsyncMock()
        mock_repo.get_plays_by_date.return_value = sample_plays_data
        mock_repo_class.return_value = mock_repo

        response = test_client.get("/api/plays?date=2024-01-15&stream=all&format=json")
        assert response.status_code == 200

        data = response.json()
        assert data["total_count"] == 2
        assert data["date"] == "2024-01-15"
        assert data["stream"] == "all"
        assert len(data["plays"]) == 2

        # Check first play
        play1 = data["plays"][0]
        assert play1["title"] == "Bohemian Rhapsody"
        assert play1["artist"] == "Queen"
        assert play1["recognized_at_pt"] == "12:30:00"  # PST conversion
        assert play1["confidence"] == 0.95

        # Verify repository was called correctly
        mock_repo.get_plays_by_date.assert_called_once_with(date(2024, 1, 15), None)

    @patch("app.web.routes.PlayRepository")
    async def test_get_plays_json_with_stream_filter(
        self,
        mock_repo_class,
        test_client: TestClient,
        sample_plays_data: list[dict[str, Any]],
    ) -> None:
        """Test JSON plays API with stream filter."""
        # Mock repository
        mock_repo = AsyncMock()
        mock_repo.get_plays_by_date.return_value = [
            sample_plays_data[0]
        ]  # Only first play
        mock_repo_class.return_value = mock_repo

        response = test_client.get("/api/plays?date=2024-01-15&stream=living_room")
        assert response.status_code == 200

        data = response.json()
        assert data["total_count"] == 1
        assert data["stream"] == "living_room"

        # Verify repository was called with stream filter
        mock_repo.get_plays_by_date.assert_called_once_with(
            date(2024, 1, 15), "living_room"
        )

    @patch("app.web.routes.PlayRepository")
    async def test_get_plays_csv_format(
        self,
        mock_repo_class,
        test_client: TestClient,
        sample_plays_data: list[dict[str, Any]],
    ) -> None:
        """Test CSV format response."""
        # Mock repository
        mock_repo = AsyncMock()
        mock_repo.get_plays_by_date.return_value = sample_plays_data
        mock_repo_class.return_value = mock_repo

        response = test_client.get("/api/plays?date=2024-01-15&stream=all&format=csv")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv; charset=utf-8"

        # Check Content-Disposition header
        content_disposition = response.headers["content-disposition"]
        assert "attachment" in content_disposition
        assert "plays_2024-01-15_all.csv" in content_disposition

        # Parse CSV content
        csv_content = response.text
        reader = csv.reader(io.StringIO(csv_content))
        rows = list(reader)

        # Check header
        assert rows[0] == [
            "Time (PT)",
            "Title",
            "Artist",
            "Album",
            "Stream",
            "Confidence",
            "Track ID",
            "UTC Timestamp",
        ]

        # Check first data row
        assert rows[1][0] == "12:30:00"  # PT time
        assert rows[1][1] == "Bohemian Rhapsody"
        assert rows[1][2] == "Queen"
        assert rows[1][3] == "A Night at the Opera"
        assert rows[1][4] == "living_room"
        assert rows[1][5] == "0.950"
        assert rows[1][6] == "101"

    def test_get_plays_invalid_date(self, test_client: TestClient) -> None:
        """Test API with invalid date format."""
        response = test_client.get("/api/plays?date=invalid-date&stream=all")
        assert response.status_code == 400
        data = response.json()
        assert "Invalid date format" in data["detail"]

    def test_get_plays_invalid_stream(self, test_client: TestClient) -> None:
        """Test API with invalid stream name."""
        response = test_client.get("/api/plays?date=2024-01-15&stream=nonexistent")
        assert response.status_code == 400
        data = response.json()
        assert "Invalid stream" in data["detail"]
        assert "living_room" in data["detail"]  # Should list valid streams
        assert "kitchen" in data["detail"]

    @patch("app.web.routes.PlayRepository")
    async def test_get_plays_empty_results(
        self, mock_repo_class, test_client: TestClient
    ) -> None:
        """Test API with no plays found."""
        # Mock repository returning empty list
        mock_repo = AsyncMock()
        mock_repo.get_plays_by_date.return_value = []
        mock_repo_class.return_value = mock_repo

        response = test_client.get("/api/plays?date=2024-01-15&stream=all")
        assert response.status_code == 200

        data = response.json()
        assert data["total_count"] == 0
        assert len(data["plays"]) == 0

    async def test_reload_config_success(self, test_client: TestClient) -> None:
        """Test successful config reload."""
        # Mock worker manager
        mock_worker_manager = AsyncMock()
        test_client.app.state.worker_manager = mock_worker_manager

        with patch("app.web.routes.Config") as mock_config_class:
            mock_config = Config()
            mock_config_class.return_value = mock_config

            response = test_client.post("/internal/reload")
            assert response.status_code == 200

            data = response.json()
            assert data["status"] == "reloaded"
            assert "restarted" in data["message"]

            # Verify worker manager methods were called
            mock_worker_manager.stop.assert_called_once()
            mock_worker_manager.start.assert_called_once()

    async def test_reload_config_failure(self, test_client: TestClient) -> None:
        """Test config reload failure."""
        # Mock worker manager that fails on stop
        mock_worker_manager = AsyncMock()
        mock_worker_manager.stop.side_effect = Exception("Stop failed")
        test_client.app.state.worker_manager = mock_worker_manager

        response = test_client.post("/internal/reload")
        assert response.status_code == 500

        data = response.json()
        assert "Failed to reload configuration" in data["detail"]
        assert "Stop failed" in data["detail"]


class TestPlayRecordModel:
    """Test PlayRecord Pydantic model."""

    def test_play_record_creation(self) -> None:
        """Test PlayRecord model creation and validation."""
        from app.web.routes import PlayRecord

        utc_time = datetime(2024, 1, 15, 20, 30, 0)

        play = PlayRecord(
            id=1,
            track_id=101,
            stream_id=1,
            recognized_at_utc=utc_time,
            recognized_at_pt="12:30:00",
            dedup_bucket=12345,
            confidence=0.95,
            title="Test Song",
            artist="Test Artist",
            album="Test Album",
            artwork_url="https://example.com/art.jpg",
            stream_name="test_stream",
        )

        assert play.id == 1
        assert play.title == "Test Song"
        assert play.recognized_at_pt == "12:30:00"

    def test_play_record_optional_fields(self) -> None:
        """Test PlayRecord with optional fields as None."""
        from app.web.routes import PlayRecord

        utc_time = datetime(2024, 1, 15, 20, 30, 0)

        play = PlayRecord(
            id=1,
            track_id=101,
            stream_id=1,
            recognized_at_utc=utc_time,
            recognized_at_pt="12:30:00",
            dedup_bucket=12345,
            confidence=None,
            title="Test Song",
            artist="Test Artist",
            album=None,
            artwork_url=None,
            stream_name="test_stream",
        )

        assert play.confidence is None
        assert play.album is None
        assert play.artwork_url is None


class TestCSVGeneration:
    """Test CSV generation functionality."""

    def test_csv_filename_generation(self) -> None:
        """Test CSV filename generation for different scenarios."""
        from app.web.routes import PlayRecord, generate_csv_response

        # Create sample play record
        play = PlayRecord(
            id=1,
            track_id=101,
            stream_id=1,
            recognized_at_utc=datetime(2024, 1, 15, 20, 30, 0),
            recognized_at_pt="12:30:00",
            dedup_bucket=12345,
            confidence=0.95,
            title="Test Song",
            artist="Test Artist",
            album="Test Album",
            artwork_url=None,
            stream_name="test_stream",
        )

        # Test all streams
        response = generate_csv_response([play], date(2024, 1, 15), "all")
        assert "plays_2024-01-15_all.csv" in response.headers["content-disposition"]

        # Test specific stream
        response = generate_csv_response([play], date(2024, 1, 15), "living_room")
        assert (
            "plays_2024-01-15_living_room.csv"
            in response.headers["content-disposition"]
        )

    def test_csv_content_formatting(self) -> None:
        """Test CSV content formatting."""
        from app.web.routes import PlayRecord, generate_csv_response

        # Create play with missing optional fields
        play = PlayRecord(
            id=1,
            track_id=101,
            stream_id=1,
            recognized_at_utc=datetime(2024, 1, 15, 20, 30, 0),
            recognized_at_pt="12:30:00",
            dedup_bucket=12345,
            confidence=None,  # Missing confidence
            title="Test Song",
            artist="Test Artist",
            album=None,  # Missing album
            artwork_url=None,
            stream_name="test_stream",
        )

        response = generate_csv_response([play], date(2024, 1, 15), "all")
        csv_content = response.body.decode()

        # Parse CSV
        reader = csv.reader(io.StringIO(csv_content))
        rows = list(reader)

        # Check data row handles missing values
        data_row = rows[1]
        assert data_row[3] == ""  # Empty album
        assert data_row[5] == ""  # Empty confidence
