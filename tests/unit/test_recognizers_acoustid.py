"""Tests for AcoustIDRecognizer."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.recognizers.acoustid_recognizer import (
    AcoustIDRecognizer,
    FakeAcoustIDRecognizer,
)


@pytest.fixture
def acoustid_fixtures():
    """Load AcoustID test fixtures."""
    fixtures_path = Path(__file__).parent.parent / "data" / "acoustid_fixtures.json"
    with open(fixtures_path) as f:
        return json.load(f)


@pytest.fixture
def mock_aiohttp_session():
    """Mock aiohttp session."""
    session = AsyncMock()
    response = AsyncMock()

    # Properly mock the async context manager
    context_manager = AsyncMock()
    context_manager.__aenter__.return_value = response
    context_manager.__aexit__.return_value = None
    session.post.return_value = context_manager

    return session, response


class TestAcoustIDRecognizer:
    """Test cases for AcoustIDRecognizer."""

    @pytest.mark.asyncio
    async def test_successful_recognition(self, acoustid_fixtures):
        """Test successful music recognition."""
        # Setup
        recognizer = AcoustIDRecognizer(api_key="test_key")

        with (
            patch.object(
                recognizer, "_generate_fingerprint", return_value="fake_fingerprint"
            ),
            patch.object(
                recognizer,
                "_query_acoustid",
                return_value=acoustid_fixtures["successful_match"],
            ),
        ):
            # Execute
            result = await recognizer.recognize(b"fake_wav_data")

        # Verify
        assert result.is_success
        assert result.provider == "acoustid"
        assert result.provider_track_id == "abcd1234-5678-90ef-ghij-klmnopqrstuv"
        assert result.title == "Bohemian Rhapsody"
        assert result.artist == "Queen"
        assert result.album == "A Night At The Opera"
        assert result.confidence == 0.95
        assert result.error_message is None
        assert result.raw_response == acoustid_fixtures["successful_match"]

    @pytest.mark.asyncio
    async def test_high_confidence_recognition(self, acoustid_fixtures):
        """Test recognition with high confidence match."""
        # Setup
        recognizer = AcoustIDRecognizer(api_key="test_key")

        with (
            patch.object(
                recognizer, "_generate_fingerprint", return_value="fake_fingerprint"
            ),
            patch.object(
                recognizer,
                "_query_acoustid",
                return_value=acoustid_fixtures["high_confidence_match"],
            ),
        ):
            # Execute
            result = await recognizer.recognize(b"fake_wav_data")

        # Verify
        assert result.is_success
        assert result.title == "Imagine"
        assert result.artist == "John Lennon"
        assert result.confidence == 0.92

    @pytest.mark.asyncio
    async def test_low_confidence_recognition(self, acoustid_fixtures):
        """Test recognition with low confidence match."""
        # Setup
        recognizer = AcoustIDRecognizer(api_key="test_key")

        with (
            patch.object(
                recognizer, "_generate_fingerprint", return_value="fake_fingerprint"
            ),
            patch.object(
                recognizer,
                "_query_acoustid",
                return_value=acoustid_fixtures["low_confidence_match"],
            ),
        ):
            # Execute
            result = await recognizer.recognize(b"fake_wav_data")

        # Verify
        assert result.is_success
        assert result.title == "Unclear Song"
        assert result.artist == "Unclear Artist"
        assert result.confidence == 0.65

    @pytest.mark.asyncio
    async def test_no_match_found(self, acoustid_fixtures):
        """Test when no match is found."""
        # Setup
        recognizer = AcoustIDRecognizer(api_key="test_key")

        with (
            patch.object(
                recognizer, "_generate_fingerprint", return_value="fake_fingerprint"
            ),
            patch.object(
                recognizer,
                "_query_acoustid",
                return_value=acoustid_fixtures["no_match"],
            ),
        ):
            # Execute
            result = await recognizer.recognize(b"fake_wav_data")

        # Verify
        assert result.is_no_match
        assert not result.is_success
        assert result.provider_track_id == ""
        assert result.title == ""
        assert result.artist == ""
        assert result.error_message is None

    @pytest.mark.asyncio
    async def test_api_error_response(self, acoustid_fixtures):
        """Test handling of API error responses."""
        # Setup
        recognizer = AcoustIDRecognizer(api_key="test_key")

        with (
            patch.object(
                recognizer, "_generate_fingerprint", return_value="fake_fingerprint"
            ),
            patch.object(
                recognizer,
                "_query_acoustid",
                return_value=acoustid_fixtures["error_response"],
            ),
        ):
            # Execute
            result = await recognizer.recognize(b"fake_wav_data")

        # Verify
        assert not result.is_success
        assert result.error_message == "invalid fingerprint"
        assert result.provider_track_id == ""

    @pytest.mark.asyncio
    async def test_http_error_response(self):
        """Test handling of HTTP error responses."""
        # Setup
        recognizer = AcoustIDRecognizer(api_key="test_key")
        http_error_response = {
            "error": {"message": "AcoustID API error: HTTP 400", "code": 400}
        }

        with (
            patch.object(
                recognizer, "_generate_fingerprint", return_value="fake_fingerprint"
            ),
            patch.object(
                recognizer, "_query_acoustid", return_value=http_error_response
            ),
        ):
            # Execute
            result = await recognizer.recognize(b"fake_wav_data")

        # Verify
        assert not result.is_success
        assert "AcoustID API error: HTTP 400" in result.error_message

    @pytest.mark.asyncio
    async def test_fingerprint_generation_failure(self):
        """Test handling of fingerprint generation failure."""
        # Setup
        recognizer = AcoustIDRecognizer(api_key="test_key")

        with patch.object(recognizer, "_generate_fingerprint", return_value=None):
            # Execute
            result = await recognizer.recognize(b"fake_wav_data")

        # Verify
        assert not result.is_success
        assert "Failed to generate audio fingerprint" in result.error_message

    @pytest.mark.asyncio
    async def test_fingerprint_generation_success(self):
        """Test successful fingerprint generation."""
        # Setup
        recognizer = AcoustIDRecognizer(
            api_key="test_key", chromaprint_path="/fake/fpcalc"
        )

        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate.return_value = (
            b'{"fingerprint": "test_fingerprint_data"}',
            b"",
        )

        with (
            patch("asyncio.create_subprocess_exec", return_value=mock_process),
            patch("tempfile.NamedTemporaryFile") as mock_temp,
            patch("pathlib.Path.unlink"),
        ):
            mock_temp.return_value.__enter__.return_value.name = "/tmp/test.wav"

            # Execute
            fingerprint = await recognizer._generate_fingerprint(b"fake_wav_data", 30.0)

        # Verify
        assert fingerprint == "test_fingerprint_data"

    @pytest.mark.asyncio
    async def test_fingerprint_generation_fpcalc_failure(self):
        """Test fingerprint generation when fpcalc fails."""
        # Setup
        recognizer = AcoustIDRecognizer(
            api_key="test_key", chromaprint_path="/fake/fpcalc"
        )

        mock_process = AsyncMock()
        mock_process.returncode = 1
        mock_process.communicate.return_value = (b"", b"fpcalc error")

        with (
            patch("asyncio.create_subprocess_exec", return_value=mock_process),
            patch("tempfile.NamedTemporaryFile") as mock_temp,
            patch("pathlib.Path.unlink"),
        ):
            mock_temp.return_value.__enter__.return_value.name = "/tmp/test.wav"

            # Execute
            fingerprint = await recognizer._generate_fingerprint(b"fake_wav_data", 30.0)

        # Verify
        assert fingerprint is None

    @pytest.mark.asyncio
    async def test_fingerprint_generation_invalid_json(self):
        """Test fingerprint generation with invalid JSON output."""
        # Setup
        recognizer = AcoustIDRecognizer(
            api_key="test_key", chromaprint_path="/fake/fpcalc"
        )

        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate.return_value = (b"invalid json", b"")

        with (
            patch("asyncio.create_subprocess_exec", return_value=mock_process),
            patch("tempfile.NamedTemporaryFile") as mock_temp,
            patch("pathlib.Path.unlink"),
        ):
            mock_temp.return_value.__enter__.return_value.name = "/tmp/test.wav"

            # Execute
            fingerprint = await recognizer._generate_fingerprint(b"fake_wav_data", 30.0)

        # Verify
        assert fingerprint is None

    @pytest.mark.asyncio
    async def test_timeout_handling(self):
        """Test timeout handling."""
        # Setup
        recognizer = AcoustIDRecognizer(api_key="test_key", timeout_seconds=1.0)

        with patch.object(
            recognizer, "_generate_fingerprint", side_effect=Exception("Timeout")
        ):
            # Execute
            result = await recognizer.recognize(b"fake_wav_data", timeout_seconds=1.0)

        # Verify
        assert not result.is_success
        assert "Recognition failed" in result.error_message
        assert "Timeout" in result.error_message

    @pytest.mark.asyncio
    async def test_session_management(self):
        """Test HTTP session creation and reuse."""
        recognizer = AcoustIDRecognizer(api_key="test_key")

        # Get session twice
        session1 = await recognizer._get_session()
        session2 = await recognizer._get_session()

        # Should be the same instance
        assert session1 is session2

        # Test close
        await recognizer.close()
        # Session should be closed, next call creates new one
        session3 = await recognizer._get_session()
        assert session3 is not session1

    def test_select_best_release_with_dates(self):
        """Test release selection prioritizing dated releases."""
        recognizer = AcoustIDRecognizer(api_key="test_key")

        releases = [
            {"title": "Release 1"},
            {"title": "Release 2", "date": "2020"},
            {"title": "Release 3", "date": "2021"},
        ]

        best = recognizer._select_best_release(releases)
        assert "date" in best
        assert best["title"] in ["Release 2", "Release 3"]

    def test_select_best_release_with_countries(self):
        """Test release selection prioritizing major countries."""
        recognizer = AcoustIDRecognizer(api_key="test_key")

        releases = [
            {"title": "Release 1", "country": "XX"},
            {"title": "Release 2", "country": "US"},
            {"title": "Release 3", "country": "ZZ"},
        ]

        best = recognizer._select_best_release(releases)
        assert best["country"] == "US"

    def test_select_best_release_empty_list(self):
        """Test release selection with empty list."""
        recognizer = AcoustIDRecognizer(api_key="test_key")

        best = recognizer._select_best_release([])
        assert best == {}


class TestFakeAcoustIDRecognizer:
    """Test cases for FakeAcoustIDRecognizer."""

    @pytest.mark.asyncio
    async def test_successful_fixture_response(self, acoustid_fixtures):
        """Test fake recognizer with successful fixture."""
        # Setup
        recognizer = FakeAcoustIDRecognizer(
            fixture_responses=acoustid_fixtures, current_fixture="successful_match"
        )

        # Execute
        result = await recognizer.recognize(b"fake_wav_data")

        # Verify
        assert result.is_success
        assert result.title == "Bohemian Rhapsody"
        assert result.artist == "Queen"
        assert recognizer.call_count == 1

    @pytest.mark.asyncio
    async def test_no_match_fixture_response(self, acoustid_fixtures):
        """Test fake recognizer with no match fixture."""
        # Setup
        recognizer = FakeAcoustIDRecognizer(
            fixture_responses=acoustid_fixtures, current_fixture="no_match"
        )

        # Execute
        result = await recognizer.recognize(b"fake_wav_data")

        # Verify
        assert result.is_no_match
        assert not result.is_success

    @pytest.mark.asyncio
    async def test_timeout_simulation(self, acoustid_fixtures):
        """Test fake recognizer timeout simulation."""
        # Setup
        recognizer = FakeAcoustIDRecognizer(
            fixture_responses=acoustid_fixtures, should_timeout=True
        )

        # Execute
        result = await recognizer.recognize(b"fake_wav_data", timeout_seconds=5.0)

        # Verify
        assert not result.is_success
        assert "timed out after 5.0s" in result.error_message

    @pytest.mark.asyncio
    async def test_failure_simulation(self, acoustid_fixtures):
        """Test fake recognizer failure simulation."""
        # Setup
        recognizer = FakeAcoustIDRecognizer(
            fixture_responses=acoustid_fixtures, should_fail=True
        )

        # Execute
        result = await recognizer.recognize(b"fake_wav_data")

        # Verify
        assert not result.is_success
        assert "Simulated recognition failure" in result.error_message

    @pytest.mark.asyncio
    async def test_fingerprint_failure_simulation(self, acoustid_fixtures):
        """Test fake recognizer fingerprint failure simulation."""
        # Setup
        recognizer = FakeAcoustIDRecognizer(
            fixture_responses=acoustid_fixtures, fingerprint_should_fail=True
        )

        # Execute
        result = await recognizer.recognize(b"fake_wav_data")

        # Verify
        assert not result.is_success
        assert "Failed to generate audio fingerprint" in result.error_message

    @pytest.mark.asyncio
    async def test_call_count_increment(self, acoustid_fixtures):
        """Test that call count increments properly."""
        # Setup
        recognizer = FakeAcoustIDRecognizer(
            fixture_responses=acoustid_fixtures, current_fixture="successful_match"
        )

        # Execute multiple calls
        await recognizer.recognize(b"fake_wav_data")
        await recognizer.recognize(b"fake_wav_data")
        await recognizer.recognize(b"fake_wav_data")

        # Verify
        assert recognizer.call_count == 3

    @pytest.mark.asyncio
    async def test_close_method(self, acoustid_fixtures):
        """Test close method for fake recognizer."""
        recognizer = FakeAcoustIDRecognizer(fixture_responses=acoustid_fixtures)

        # Should not raise an exception
        await recognizer.close()


@pytest.mark.asyncio
async def test_integration_concurrent_recognizers():
    """Integration test with multiple AcoustID recognizers running concurrently."""
    # Setup
    recognizers = [
        FakeAcoustIDRecognizer(should_fail=False),
        FakeAcoustIDRecognizer(should_timeout=True),
        FakeAcoustIDRecognizer(fingerprint_should_fail=True),
        FakeAcoustIDRecognizer(should_fail=True),
    ]

    # Execute all recognizers in parallel
    import asyncio

    tasks = [
        recognizer.recognize(b"fake_wav_data", timeout_seconds=1.0)
        for recognizer in recognizers
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Verify
    assert len(results) == 4
    for result in results:
        assert not isinstance(result, Exception)  # All should handle errors gracefully

    # Check specific error types
    success_result, timeout_result, fingerprint_result, fail_result = results
    assert not success_result.is_success  # Fake returns no match by default
    assert not timeout_result.is_success
    assert not fingerprint_result.is_success
    assert not fail_result.is_success

    assert "timed out" in timeout_result.error_message
    assert "fingerprint" in fingerprint_result.error_message
    assert "Simulated recognition failure" in fail_result.error_message


@pytest.mark.asyncio
async def test_performance_multiple_parallel_calls():
    """Test performance with multiple parallel recognition calls."""
    import time

    # Setup multiple fake recognizers
    recognizers = [FakeAcoustIDRecognizer() for _ in range(10)]

    # Measure time for parallel execution
    start_time = time.time()

    import asyncio

    tasks = [recognizer.recognize(b"fake_wav_data") for recognizer in recognizers]
    results = await asyncio.gather(*tasks)

    end_time = time.time()

    # Verify
    assert len(results) == 10
    assert all(not isinstance(r, Exception) for r in results)

    # Should complete quickly (fake recognizers)
    assert end_time - start_time < 1.0  # Should be much faster than 1 second
