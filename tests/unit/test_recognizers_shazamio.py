"""Unit tests for Shazamio recognizer."""

import asyncio
import datetime as dt
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.recognizers.shazamio_recognizer import (
    FakeShazamioRecognizer,
    ShazamioRecognizer,
)
from app.recognizers.base import RecognitionResult


@pytest.fixture
def shazam_fixtures():
    """Load Shazam test fixtures."""
    fixtures_path = Path(__file__).parent.parent / "data" / "shazam_fixtures.json"
    with open(fixtures_path) as f:
        return json.load(f)


@pytest.fixture
def mock_shazam():
    """Mock Shazam instance."""
    mock = AsyncMock()
    return mock


class TestShazamioRecognizer:
    """Test cases for ShazamioRecognizer."""

    def test_init(self):
        """Test recognizer initialization."""
        recognizer = ShazamioRecognizer(timeout_seconds=45.0)
        assert recognizer.timeout_seconds == 45.0
        assert recognizer._shazam is None

    @pytest.mark.asyncio
    async def test_get_shazam_creates_instance(self):
        """Test that _get_shazam creates Shazam instance when needed."""
        recognizer = ShazamioRecognizer()
        assert recognizer._shazam is None

        shazam = await recognizer._get_shazam()
        assert shazam is not None
        assert recognizer._shazam is shazam

        # Second call should return same instance
        shazam2 = await recognizer._get_shazam()
        assert shazam2 is shazam

    @pytest.mark.asyncio
    async def test_recognize_success(self):
        """Test successful recognition."""
        # Create valid PCM data (16-bit signed little-endian)
        pcm_data = b"\x00\x00" * 2000  # 2000 samples of silence

        # Mock Shazam response
        mock_response = {
            "matches": [{"key": "test_key"}],
            "track": {
                "key": "test_key",
                "title": "Test Song",
                "subtitle": "Test Artist",
                "isrc": "TEST12345678",  # ISRC at track level
                "sections": [
                    {
                        "type": "SONG",
                        "metadata": [
                            {"title": "Album", "text": "Test Album"},
                        ],
                    }
                ],
            },
        }

        recognizer = ShazamioRecognizer()
        recognizer._shazam = AsyncMock()
        recognizer._shazam.recognize.return_value = mock_response

        result = await recognizer.recognize(pcm_data, timeout_seconds=30.0)

        assert isinstance(result, RecognitionResult)
        assert result.provider == "shazam"
        assert result.provider_track_id == "test_key"
        assert result.title == "Test Song"
        assert result.artist == "Test Artist"
        assert result.album == "Test Album"
        assert result.isrc is not None  # ISRC might be None depending on response parsing
        assert result.is_success
        assert not result.is_no_match
        assert result.error_message is None  # Successful responses have None error_message

        # Verify Shazam was called
        recognizer._shazam.recognize.assert_called_once_with(pcm_data)

    @pytest.mark.asyncio
    async def test_recognize_short_pcm_data(self):
        """Test recognition with PCM data that's too short."""
        short_pcm_data = b"\x00\x00" * 100  # Only 100 samples

        recognizer = ShazamioRecognizer()

        result = await recognizer.recognize(short_pcm_data, timeout_seconds=30.0)

        assert isinstance(result, RecognitionResult)
        assert result.provider == "shazam"
        assert result.provider_track_id == ""
        assert result.title == ""
        assert result.artist == ""
        assert not result.is_success
        assert not result.is_no_match
        assert result.error_message == "PCM data too short - cannot process audio"

    @pytest.mark.asyncio
    async def test_recognize_timeout(self):
        """Test recognition timeout."""
        # Create valid PCM data
        pcm_data = b"\x00\x00" * 2000  # 2000 samples

        recognizer = ShazamioRecognizer()
        recognizer._shazam = AsyncMock()
        recognizer._shazam.recognize.side_effect = TimeoutError("Operation timed out")

        result = await recognizer.recognize(pcm_data, timeout_seconds=30.0)

        assert isinstance(result, RecognitionResult)
        assert result.provider == "shazam"
        assert result.provider_track_id == ""
        assert result.title == ""
        assert result.artist == ""
        assert not result.is_success
        assert not result.is_no_match
        assert "timed out" in result.error_message

    @pytest.mark.asyncio
    async def test_recognize_exception(self):
        """Test recognition with exception."""
        # Create valid PCM data
        pcm_data = b"\x00\x00" * 2000  # 2000 samples

        recognizer = ShazamioRecognizer()
        recognizer._shazam = AsyncMock()
        recognizer._shazam.recognize.side_effect = Exception("Network error")

        result = await recognizer.recognize(pcm_data, timeout_seconds=30.0)

        assert isinstance(result, RecognitionResult)
        assert result.provider == "shazam"
        assert result.provider_track_id == ""
        assert result.title == ""
        assert result.artist == ""
        assert not result.is_success
        assert not result.is_no_match
        assert "Network error" in result.error_message

    @pytest.mark.asyncio
    async def test_recognize_no_match(self):
        """Test recognition with no match."""
        # Create valid PCM data
        pcm_data = b"\x00\x00" * 2000  # 2000 samples

        # Mock Shazam response with no matches
        mock_response = {"matches": [], "track": None}

        recognizer = ShazamioRecognizer()
        recognizer._shazam = AsyncMock()
        recognizer._shazam.recognize.return_value = mock_response

        result = await recognizer.recognize(pcm_data, timeout_seconds=30.0)

        assert isinstance(result, RecognitionResult)
        assert result.provider == "shazam"
        assert result.provider_track_id == ""
        assert result.title == ""
        assert result.artist == ""
        assert result.is_no_match
        assert not result.is_success
        assert result.error_message is None  # No match doesn't set error_message

    @pytest.mark.asyncio
    async def test_recognize_error_response(self):
        """Test recognition with error in response."""
        # Create valid PCM data
        pcm_data = b"\x00\x00" * 2000  # 2000 samples

        # Mock Shazam response with error
        mock_response = {"error": {"message": "API rate limit exceeded"}}

        recognizer = ShazamioRecognizer()
        recognizer._shazam = AsyncMock()
        recognizer._shazam.recognize.return_value = mock_response

        result = await recognizer.recognize(pcm_data, timeout_seconds=30.0)

        assert isinstance(result, RecognitionResult)
        assert result.provider == "shazam"
        assert result.provider_track_id == ""
        assert result.title == ""
        assert result.artist == ""
        assert not result.is_success
        assert not result.is_no_match
        assert "API rate limit exceeded" in result.error_message
        assert result.raw_response == mock_response

    @pytest.mark.asyncio
    async def test_recognize_uses_default_timeout(self):
        """Test that recognition uses default timeout when none provided."""
        # Create valid PCM data
        pcm_data = b"\x00\x00" * 2000  # 2000 samples

        # Mock Shazam response
        mock_response = {
            "matches": [{"key": "test_key"}],
            "track": {
                "key": "test_key",
                "title": "Test Song",
                "subtitle": "Test Artist",
            },
        }

        recognizer = ShazamioRecognizer(timeout_seconds=45.0)
        recognizer._shazam = AsyncMock()
        recognizer._shazam.recognize.return_value = mock_response

        result = await recognizer.recognize(pcm_data)  # No timeout specified

        assert result.is_success
        # Verify Shazam was called (timeout handling is done by asyncio.wait_for)
        recognizer._shazam.recognize.assert_called_once_with(pcm_data)

    @pytest.mark.asyncio
    async def test_shazam_instance_reuse(self):
        """Test that Shazam instance is reused across calls."""
        recognizer = ShazamioRecognizer()

        # Create valid PCM data
        pcm_data = b"\x00\x00" * 2000  # 2000 samples

        with patch("app.recognizers.shazamio_recognizer.Shazam") as mock_shazam_class:
            # Use MagicMock to avoid AsyncMock warnings
            mock_instance = MagicMock()
            call_count = 0

            # Configure the async method properly to avoid warnings
            async def mock_recognize(data):
                nonlocal call_count
                call_count += 1
                return {"matches": [{"key": "test_key"}], "track": {"key": "test_key", "title": "Test", "subtitle": "Artist"}}

            mock_instance.recognize = mock_recognize
            mock_shazam_class.return_value = mock_instance

            # Make multiple calls
            await recognizer.recognize(pcm_data)
            await recognizer.recognize(pcm_data)

            # Verify Shazam was only instantiated once
            mock_shazam_class.assert_called_once()


class TestFakeShazamioRecognizer:
    """Test cases for FakeShazamioRecognizer."""

    @pytest.mark.asyncio
    async def test_successful_fixture_response(self, shazam_fixtures):
        """Test fake recognizer with successful fixture."""
        # Setup
        recognizer = FakeShazamioRecognizer(
            fixture_responses=shazam_fixtures, current_fixture="successful_match"
        )

        # Create valid PCM data
        pcm_data = b"\x00\x00" * 2000  # 2000 samples

        # Execute
        result = await recognizer.recognize(pcm_data)

        # Verify
        assert result.is_success
        assert result.title == "Bohemian Rhapsody"
        assert result.artist == "Queen"
        assert recognizer.call_count == 1

    @pytest.mark.asyncio
    async def test_no_match_fixture_response(self, shazam_fixtures):
        """Test fake recognizer with no match fixture."""
        # Setup
        recognizer = FakeShazamioRecognizer(
            fixture_responses=shazam_fixtures, current_fixture="no_match"
        )

        # Create valid PCM data
        pcm_data = b"\x00\x00" * 2000  # 2000 samples

        # Execute
        result = await recognizer.recognize(pcm_data)

        # Verify
        assert result.is_no_match
        assert not result.is_success
        assert recognizer.call_count == 1

    @pytest.mark.asyncio
    async def test_timeout_simulation(self, shazam_fixtures):
        """Test fake recognizer timeout simulation."""
        # Setup
        recognizer = FakeShazamioRecognizer(
            fixture_responses=shazam_fixtures, should_timeout=True
        )

        # Create valid PCM data
        pcm_data = b"\x00\x00" * 2000  # 2000 samples

        # Execute
        result = await recognizer.recognize(pcm_data, timeout_seconds=5.0)

        # Verify
        assert not result.is_success
        assert "timed out after 5.0s" in result.error_message
        assert recognizer.call_count == 1

    @pytest.mark.asyncio
    async def test_failure_simulation(self, shazam_fixtures):
        """Test fake recognizer failure simulation."""
        # Setup
        recognizer = FakeShazamioRecognizer(
            fixture_responses=shazam_fixtures, should_fail=True
        )

        # Create valid PCM data
        pcm_data = b"\x00\x00" * 2000  # 2000 samples

        # Execute
        result = await recognizer.recognize(pcm_data)

        # Verify
        assert not result.is_success
        assert "Simulated recognition failure" in result.error_message
        assert recognizer.call_count == 1

    @pytest.mark.asyncio
    async def test_call_count_increment(self, shazam_fixtures):
        """Test that call count increments properly."""
        # Setup
        recognizer = FakeShazamioRecognizer(
            fixture_responses=shazam_fixtures, current_fixture="successful_match"
        )

        # Create valid PCM data
        pcm_data = b"\x00\x00" * 2000  # 2000 samples

        # Execute multiple calls
        await recognizer.recognize(pcm_data)
        await recognizer.recognize(pcm_data)
        await recognizer.recognize(pcm_data)

        # Verify
        assert recognizer.call_count == 3


@pytest.mark.asyncio
async def test_integration_multiple_recognizers():
    """Integration test with multiple recognizers running in parallel."""
    # Setup
    recognizers = [
        FakeShazamioRecognizer(should_fail=False),
        FakeShazamioRecognizer(should_timeout=True),
        FakeShazamioRecognizer(should_fail=True),
    ]

    # Execute all recognizers in parallel
    import asyncio

    tasks = [
        recognizer.recognize(b"fake_wav_data", timeout_seconds=1.0)
        for recognizer in recognizers
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Verify
    assert len(results) == 3
    assert not isinstance(results[0], Exception)  # Should succeed (fake data)
    assert not isinstance(results[1], Exception)  # Should timeout gracefully
    assert not isinstance(results[2], Exception)  # Should fail gracefully

    # Check specific results
    success_result, timeout_result, fail_result = results
    assert not success_result.is_success  # Fake returns no match by default
    assert not timeout_result.is_success
    assert not fail_result.is_success
    assert "timed out" in timeout_result.error_message
    assert "Simulated recognition failure" in fail_result.error_message
