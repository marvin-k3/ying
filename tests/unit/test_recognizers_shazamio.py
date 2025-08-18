"""Unit tests for Shazamio recognizer."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.recognizers.base import RecognitionResult
from app.recognizers.shazamio_recognizer import (
    FakeShazamioRecognizer,
    ShazamioRecognizer,
    _validate_wav_header,
)


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


class TestWavHeaderValidation:
    """Test WAV header validation function."""

    def test_valid_wav_header(self):
        """Test that valid WAV header passes validation."""
        # Create a minimal valid WAV header (44 bytes)
        wav_header = (
            b"RIFF"  # RIFF signature
            + b"\x24\x00\x00\x00"  # File size - 36 (little endian)
            + b"WAVE"  # WAVE format
            + b"fmt "  # fmt chunk
            + b"\x10\x00\x00\x00"  # fmt chunk size (16)
            + b"\x01\x00"  # Audio format (PCM = 1)
            + b"\x01\x00"  # Channels (1 = mono)
            + b"\x44\xac\x00\x00"  # Sample rate (44100)
            + b"\x88\x58\x01\x00"  # Byte rate (44100 * 2)
            + b"\x02\x00"  # Block align (2)
            + b"\x10\x00"  # Bits per sample (16)
            + b"data"  # data chunk
            + b"\x00\x00\x00\x00"  # data chunk size
        )

        assert _validate_wav_header(wav_header) is True

    def test_invalid_riff_signature(self):
        """Test that invalid RIFF signature fails validation."""
        wav_header = (
            b"RIFT"
            + b"\x24\x00\x00\x00"
            + b"WAVE"
            + b"fmt "
            + b"\x10\x00\x00\x00"
            + b"\x01\x00"
            + b"\x01\x00"
            + b"\x44\xac\x00\x00"
            + b"\x88\x58\x01\x00"
            + b"\x02\x00"
            + b"\x10\x00"
            + b"data"
            + b"\x00\x00\x00\x00"
        )
        assert _validate_wav_header(wav_header) is False

    def test_invalid_wave_format(self):
        """Test that invalid WAVE format fails validation."""
        wav_header = (
            b"RIFF"
            + b"\x24\x00\x00\x00"
            + b"WAFF"
            + b"fmt "
            + b"\x10\x00\x00\x00"
            + b"\x01\x00"
            + b"\x01\x00"
            + b"\x44\xac\x00\x00"
            + b"\x88\x58\x01\x00"
            + b"\x02\x00"
            + b"\x10\x00"
            + b"data"
            + b"\x00\x00\x00\x00"
        )
        assert _validate_wav_header(wav_header) is False

    def test_invalid_audio_format(self):
        """Test that non-PCM audio format fails validation."""
        wav_header = (
            b"RIFF"
            + b"\x24\x00\x00\x00"
            + b"WAVE"
            + b"fmt "
            + b"\x10\x00\x00\x00"
            + b"\x02\x00"
            + b"\x01\x00"
            + b"\x44\xac\x00\x00"
            + b"\x88\x58\x01\x00"
            + b"\x02\x00"
            + b"\x10\x00"
            + b"data"
            + b"\x00\x00\x00\x00"
        )
        assert _validate_wav_header(wav_header) is False

    def test_invalid_channels(self):
        """Test that invalid channel count fails validation."""
        wav_header = (
            b"RIFF"
            + b"\x24\x00\x00\x00"
            + b"WAVE"
            + b"fmt "
            + b"\x10\x00\x00\x00"
            + b"\x01\x00"
            + b"\x03\x00"
            + b"\x44\xac\x00\x00"
            + b"\x88\x58\x01\x00"
            + b"\x02\x00"
            + b"\x10\x00"
            + b"data"
            + b"\x00\x00\x00\x00"
        )
        assert _validate_wav_header(wav_header) is False

    def test_invalid_sample_rate(self):
        """Test that invalid sample rate fails validation."""
        wav_header = (
            b"RIFF"
            + b"\x24\x00\x00\x00"
            + b"WAVE"
            + b"fmt "
            + b"\x10\x00\x00\x00"
            + b"\x01\x00"
            + b"\x01\x00"
            + b"\x00\x00\x00\x00"
            + b"\x88\x58\x01\x00"
            + b"\x02\x00"
            + b"\x10\x00"
            + b"data"
            + b"\x00\x00\x00\x00"
        )
        assert _validate_wav_header(wav_header) is False

    def test_invalid_bits_per_sample(self):
        """Test that invalid bits per sample fails validation."""
        wav_header = (
            b"RIFF"
            + b"\x24\x00\x00\x00"
            + b"WAVE"
            + b"fmt "
            + b"\x10\x00\x00\x00"
            + b"\x01\x00"
            + b"\x01\x00"
            + b"\x44\xac\x00\x00"
            + b"\x88\x58\x01\x00"
            + b"\x02\x00"
            + b"\x08\x00"
            + b"data"
            + b"\x00\x00\x00\x00"
        )
        assert _validate_wav_header(wav_header) is False

    def test_short_data(self):
        """Test that data shorter than WAV header fails validation."""
        short_data = b"RIFF"
        assert _validate_wav_header(short_data) is False

    def test_stereo_wav_header(self):
        """Test that stereo WAV header passes validation."""
        wav_header = (
            b"RIFF"  # RIFF signature
            + b"\x24\x00\x00\x00"  # File size - 36 (little endian)
            + b"WAVE"  # WAVE format
            + b"fmt "  # fmt chunk
            + b"\x10\x00\x00\x00"  # fmt chunk size (16)
            + b"\x01\x00"  # Audio format (PCM = 1)
            + b"\x02\x00"  # Channels (2 = stereo)
            + b"\x44\xac\x00\x00"  # Sample rate (44100)
            + b"\x10\xb1\x02\x00"  # Byte rate (44100 * 4)
            + b"\x04\x00"  # Block align (4)
            + b"\x10\x00"  # Bits per sample (16)
            + b"data"  # data chunk
            + b"\x00\x00\x00\x00"  # data chunk size
        )

        assert _validate_wav_header(wav_header) is True


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
        # Create valid WAV data
        wav_data = (
            b"RIFF"  # RIFF signature
            + b"\x24\x00\x00\x00"  # File size - 36 (little endian)
            + b"WAVE"  # WAVE format
            + b"fmt "  # fmt chunk
            + b"\x10\x00\x00\x00"  # fmt chunk size (16)
            + b"\x01\x00"  # Audio format (PCM = 1)
            + b"\x01\x00"  # Channels (1 = mono)
            + b"\x44\xac\x00\x00"  # Sample rate (44100)
            + b"\x88\x58\x01\x00"  # Byte rate (44100 * 2)
            + b"\x02\x00"  # Block align (2)
            + b"\x10\x00"  # Bits per sample (16)
            + b"data"  # data chunk
            + b"\x00\x00\x00\x00"  # data chunk size
            + b"\x00\x00" * 2000  # Some audio data
        )

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

        result = await recognizer.recognize(wav_data, timeout_seconds=30.0)

        assert isinstance(result, RecognitionResult)
        assert result.provider == "shazam"
        assert result.provider_track_id == "test_key"
        assert result.title == "Test Song"
        assert result.artist == "Test Artist"
        assert result.album == "Test Album"
        assert (
            result.isrc is not None
        )  # ISRC might be None depending on response parsing
        assert result.is_success
        assert not result.is_no_match
        assert (
            result.error_message is None
        )  # Successful responses have None error_message

        # Verify Shazam was called
        recognizer._shazam.recognize.assert_called_once_with(wav_data)

    @pytest.mark.asyncio
    async def test_recognize_invalid_wav_format(self):
        """Test recognition with invalid WAV format."""
        invalid_wav_data = b"invalid_wav_data"

        recognizer = ShazamioRecognizer()

        result = await recognizer.recognize(invalid_wav_data, timeout_seconds=30.0)

        assert isinstance(result, RecognitionResult)
        assert result.provider == "shazam"
        assert result.provider_track_id == ""
        assert result.title == ""
        assert result.artist == ""
        assert not result.is_success
        assert not result.is_no_match
        assert result.error_message == "Invalid WAV format - cannot process audio"

    @pytest.mark.asyncio
    async def test_recognize_timeout(self):
        """Test recognition timeout."""
        # Create valid WAV data
        wav_data = (
            b"RIFF"  # RIFF signature
            + b"\x24\x00\x00\x00"  # File size - 36 (little endian)
            + b"WAVE"  # WAVE format
            + b"fmt "  # fmt chunk
            + b"\x10\x00\x00\x00"  # fmt chunk size (16)
            + b"\x01\x00"  # Audio format (PCM = 1)
            + b"\x01\x00"  # Channels (1 = mono)
            + b"\x44\xac\x00\x00"  # Sample rate (44100)
            + b"\x88\x58\x01\x00"  # Byte rate (44100 * 2)
            + b"\x02\x00"  # Block align (2)
            + b"\x10\x00"  # Bits per sample (16)
            + b"data"  # data chunk
            + b"\x00\x00\x00\x00"  # data chunk size
            + b"\x00\x00" * 2000  # Some audio data
        )

        recognizer = ShazamioRecognizer()
        recognizer._shazam = AsyncMock()
        recognizer._shazam.recognize.side_effect = TimeoutError("Operation timed out")

        result = await recognizer.recognize(wav_data, timeout_seconds=30.0)

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
        # Create valid WAV data
        wav_data = (
            b"RIFF"  # RIFF signature
            + b"\x24\x00\x00\x00"  # File size - 36 (little endian)
            + b"WAVE"  # WAVE format
            + b"fmt "  # fmt chunk
            + b"\x10\x00\x00\x00"  # fmt chunk size (16)
            + b"\x01\x00"  # Audio format (PCM = 1)
            + b"\x01\x00"  # Channels (1 = mono)
            + b"\x44\xac\x00\x00"  # Sample rate (44100)
            + b"\x88\x58\x01\x00"  # Byte rate (44100 * 2)
            + b"\x02\x00"  # Block align (2)
            + b"\x10\x00"  # Bits per sample (16)
            + b"data"  # data chunk
            + b"\x00\x00\x00\x00"  # data chunk size
            + b"\x00\x00" * 2000  # Some audio data
        )

        recognizer = ShazamioRecognizer()
        recognizer._shazam = AsyncMock()
        recognizer._shazam.recognize.side_effect = Exception("Network error")

        result = await recognizer.recognize(wav_data, timeout_seconds=30.0)

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
        # Create valid WAV data
        wav_data = (
            b"RIFF"  # RIFF signature
            + b"\x24\x00\x00\x00"  # File size - 36 (little endian)
            + b"WAVE"  # WAVE format
            + b"fmt "  # fmt chunk
            + b"\x10\x00\x00\x00"  # fmt chunk size (16)
            + b"\x01\x00"  # Audio format (PCM = 1)
            + b"\x01\x00"  # Channels (1 = mono)
            + b"\x44\xac\x00\x00"  # Sample rate (44100)
            + b"\x88\x58\x01\x00"  # Byte rate (44100 * 2)
            + b"\x02\x00"  # Block align (2)
            + b"\x10\x00"  # Bits per sample (16)
            + b"data"  # data chunk
            + b"\x00\x00\x00\x00"  # data chunk size
            + b"\x00\x00" * 2000  # Some audio data
        )

        # Mock Shazam response with no matches
        mock_response = {"matches": [], "track": None}

        recognizer = ShazamioRecognizer()
        recognizer._shazam = AsyncMock()
        recognizer._shazam.recognize.return_value = mock_response

        result = await recognizer.recognize(wav_data, timeout_seconds=30.0)

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
        # Create valid WAV data
        wav_data = (
            b"RIFF"  # RIFF signature
            + b"\x24\x00\x00\x00"  # File size - 36 (little endian)
            + b"WAVE"  # WAVE format
            + b"fmt "  # fmt chunk
            + b"\x10\x00\x00\x00"  # fmt chunk size (16)
            + b"\x01\x00"  # Audio format (PCM = 1)
            + b"\x01\x00"  # Channels (1 = mono)
            + b"\x44\xac\x00\x00"  # Sample rate (44100)
            + b"\x88\x58\x01\x00"  # Byte rate (44100 * 2)
            + b"\x02\x00"  # Block align (2)
            + b"\x10\x00"  # Bits per sample (16)
            + b"data"  # data chunk
            + b"\x00\x00\x00\x00"  # data chunk size
            + b"\x00\x00" * 2000  # Some audio data
        )

        # Mock Shazam response with error
        mock_response = {"error": {"message": "API rate limit exceeded"}}

        recognizer = ShazamioRecognizer()
        recognizer._shazam = AsyncMock()
        recognizer._shazam.recognize.return_value = mock_response

        result = await recognizer.recognize(wav_data, timeout_seconds=30.0)

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
        # Create valid WAV data
        wav_data = (
            b"RIFF"  # RIFF signature
            + b"\x24\x00\x00\x00"  # File size - 36 (little endian)
            + b"WAVE"  # WAVE format
            + b"fmt "  # fmt chunk
            + b"\x10\x00\x00\x00"  # fmt chunk size (16)
            + b"\x01\x00"  # Audio format (PCM = 1)
            + b"\x01\x00"  # Channels (1 = mono)
            + b"\x44\xac\x00\x00"  # Sample rate (44100)
            + b"\x88\x58\x01\x00"  # Byte rate (44100 * 2)
            + b"\x02\x00"  # Block align (2)
            + b"\x10\x00"  # Bits per sample (16)
            + b"data"  # data chunk
            + b"\x00\x00\x00\x00"  # data chunk size
            + b"\x00\x00" * 2000  # Some audio data
        )

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

        result = await recognizer.recognize(wav_data)  # No timeout specified

        assert result.is_success
        # Verify Shazam was called (timeout handling is done by asyncio.wait_for)
        recognizer._shazam.recognize.assert_called_once_with(wav_data)

    @pytest.mark.asyncio
    async def test_shazam_instance_reuse(self):
        """Test that Shazam instance is reused across calls."""
        recognizer = ShazamioRecognizer()

        # Create valid WAV data
        wav_data = (
            b"RIFF"  # RIFF signature
            + b"\x24\x00\x00\x00"  # File size - 36 (little endian)
            + b"WAVE"  # WAVE format
            + b"fmt "  # fmt chunk
            + b"\x10\x00\x00\x00"  # fmt chunk size (16)
            + b"\x01\x00"  # Audio format (PCM = 1)
            + b"\x01\x00"  # Channels (1 = mono)
            + b"\x44\xac\x00\x00"  # Sample rate (44100)
            + b"\x88\x58\x01\x00"  # Byte rate (44100 * 2)
            + b"\x02\x00"  # Block align (2)
            + b"\x10\x00"  # Bits per sample (16)
            + b"data"  # data chunk
            + b"\x00\x00\x00\x00"  # data chunk size
            + b"\x00\x00" * 2000  # Some audio data
        )

        with patch("app.recognizers.shazamio_recognizer.Shazam") as mock_shazam_class:
            # Use MagicMock to avoid AsyncMock warnings
            mock_instance = MagicMock()
            call_count = 0

            # Configure the async method properly to avoid warnings
            async def mock_recognize(data):
                nonlocal call_count
                call_count += 1
                return {
                    "matches": [{"key": "test_key"}],
                    "track": {"key": "test_key", "title": "Test", "subtitle": "Artist"},
                }

            mock_instance.recognize = mock_recognize
            mock_shazam_class.return_value = mock_instance

            # Make multiple calls
            await recognizer.recognize(wav_data)
            await recognizer.recognize(wav_data)

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

        # Create valid WAV data
        wav_data = (
            b"RIFF"  # RIFF signature
            + b"\x24\x00\x00\x00"  # File size - 36 (little endian)
            + b"WAVE"  # WAVE format
            + b"fmt "  # fmt chunk
            + b"\x10\x00\x00\x00"  # fmt chunk size (16)
            + b"\x01\x00"  # Audio format (PCM = 1)
            + b"\x01\x00"  # Channels (1 = mono)
            + b"\x44\xac\x00\x00"  # Sample rate (44100)
            + b"\x88\x58\x01\x00"  # Byte rate (44100 * 2)
            + b"\x02\x00"  # Block align (2)
            + b"\x10\x00"  # Bits per sample (16)
            + b"data"  # data chunk
            + b"\x00\x00\x00\x00"  # data chunk size
            + b"\x00\x00" * 2000  # Some audio data
        )

        # Execute
        result = await recognizer.recognize(wav_data)

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

        # Create valid WAV data
        wav_data = (
            b"RIFF"  # RIFF signature
            + b"\x24\x00\x00\x00"  # File size - 36 (little endian)
            + b"WAVE"  # WAVE format
            + b"fmt "  # fmt chunk
            + b"\x10\x00\x00\x00"  # fmt chunk size (16)
            + b"\x01\x00"  # Audio format (PCM = 1)
            + b"\x01\x00"  # Channels (1 = mono)
            + b"\x44\xac\x00\x00"  # Sample rate (44100)
            + b"\x88\x58\x01\x00"  # Byte rate (44100 * 2)
            + b"\x02\x00"  # Block align (2)
            + b"\x10\x00"  # Bits per sample (16)
            + b"data"  # data chunk
            + b"\x00\x00\x00\x00"  # data chunk size
            + b"\x00\x00" * 2000  # Some audio data
        )

        # Execute
        result = await recognizer.recognize(wav_data)

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

        # Create valid WAV data
        wav_data = (
            b"RIFF"  # RIFF signature
            + b"\x24\x00\x00\x00"  # File size - 36 (little endian)
            + b"WAVE"  # WAVE format
            + b"fmt "  # fmt chunk
            + b"\x10\x00\x00\x00"  # fmt chunk size (16)
            + b"\x01\x00"  # Audio format (PCM = 1)
            + b"\x01\x00"  # Channels (1 = mono)
            + b"\x44\xac\x00\x00"  # Sample rate (44100)
            + b"\x88\x58\x01\x00"  # Byte rate (44100 * 2)
            + b"\x02\x00"  # Block align (2)
            + b"\x10\x00"  # Bits per sample (16)
            + b"data"  # data chunk
            + b"\x00\x00\x00\x00"  # data chunk size
            + b"\x00\x00" * 2000  # Some audio data
        )

        # Execute
        result = await recognizer.recognize(wav_data, timeout_seconds=5.0)

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

        # Create valid WAV data
        wav_data = (
            b"RIFF"  # RIFF signature
            + b"\x24\x00\x00\x00"  # File size - 36 (little endian)
            + b"WAVE"  # WAVE format
            + b"fmt "  # fmt chunk
            + b"\x10\x00\x00\x00"  # fmt chunk size (16)
            + b"\x01\x00"  # Audio format (PCM = 1)
            + b"\x01\x00"  # Channels (1 = mono)
            + b"\x44\xac\x00\x00"  # Sample rate (44100)
            + b"\x88\x58\x01\x00"  # Byte rate (44100 * 2)
            + b"\x02\x00"  # Block align (2)
            + b"\x10\x00"  # Bits per sample (16)
            + b"data"  # data chunk
            + b"\x00\x00\x00\x00"  # data chunk size
            + b"\x00\x00" * 2000  # Some audio data
        )

        # Execute
        result = await recognizer.recognize(wav_data)

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

        # Create valid WAV data
        wav_data = (
            b"RIFF"  # RIFF signature
            + b"\x24\x00\x00\x00"  # File size - 36 (little endian)
            + b"WAVE"  # WAVE format
            + b"fmt "  # fmt chunk
            + b"\x10\x00\x00\x00"  # fmt chunk size (16)
            + b"\x01\x00"  # Audio format (PCM = 1)
            + b"\x01\x00"  # Channels (1 = mono)
            + b"\x44\xac\x00\x00"  # Sample rate (44100)
            + b"\x88\x58\x01\x00"  # Byte rate (44100 * 2)
            + b"\x02\x00"  # Block align (2)
            + b"\x10\x00"  # Bits per sample (16)
            + b"data"  # data chunk
            + b"\x00\x00\x00\x00"  # data chunk size
            + b"\x00\x00" * 2000  # Some audio data
        )

        # Execute multiple calls
        await recognizer.recognize(wav_data)
        await recognizer.recognize(wav_data)
        await recognizer.recognize(wav_data)

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
