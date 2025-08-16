"""Tests for ShazamioRecognizer."""

import json
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.recognizers.shazamio_recognizer import ShazamioRecognizer, FakeShazamioRecognizer


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
    
    @pytest.mark.asyncio
    async def test_successful_recognition(self, shazam_fixtures, mock_shazam):
        """Test successful music recognition."""
        # Setup
        recognizer = ShazamioRecognizer()
        mock_shazam.recognize.return_value = shazam_fixtures["successful_match"]
        
        with patch("app.recognizers.shazamio_recognizer.Shazam", return_value=mock_shazam):
            # Execute
            result = await recognizer.recognize(b"fake_wav_data")
        
        # Verify
        assert result.is_success
        assert result.provider == "shazam"
        assert result.provider_track_id == "123456789"
        assert result.title == "Bohemian Rhapsody"
        assert result.artist == "Queen"
        assert result.album == "A Night At The Opera"
        assert result.isrc == "GBUM71505478"
        assert result.artwork_url is not None
        assert result.confidence > 0.8  # High confidence expected
        assert result.error_message is None
        assert result.raw_response == shazam_fixtures["successful_match"]
    
    @pytest.mark.asyncio
    async def test_high_confidence_recognition(self, shazam_fixtures, mock_shazam):
        """Test recognition with high confidence match."""
        # Setup
        recognizer = ShazamioRecognizer()
        mock_shazam.recognize.return_value = shazam_fixtures["high_confidence_match"]
        
        with patch("app.recognizers.shazamio_recognizer.Shazam", return_value=mock_shazam):
            # Execute
            result = await recognizer.recognize(b"fake_wav_data")
        
        # Verify
        assert result.is_success
        assert result.title == "Imagine"
        assert result.artist == "John Lennon"
        assert result.confidence > 0.9  # Very high confidence
    
    @pytest.mark.asyncio
    async def test_low_confidence_recognition(self, shazam_fixtures, mock_shazam):
        """Test recognition with low confidence match."""
        # Setup
        recognizer = ShazamioRecognizer()
        mock_shazam.recognize.return_value = shazam_fixtures["low_confidence_match"]
        
        with patch("app.recognizers.shazamio_recognizer.Shazam", return_value=mock_shazam):
            # Execute
            result = await recognizer.recognize(b"fake_wav_data")
        
        # Verify
        assert result.is_success
        assert result.title == "Unknown Song"
        assert result.artist == "Unknown Artist"
        assert result.confidence < 0.8  # Low confidence expected
    
    @pytest.mark.asyncio
    async def test_no_match_found(self, shazam_fixtures, mock_shazam):
        """Test when no match is found."""
        # Setup
        recognizer = ShazamioRecognizer()
        mock_shazam.recognize.return_value = shazam_fixtures["no_match"]
        
        with patch("app.recognizers.shazamio_recognizer.Shazam", return_value=mock_shazam):
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
    async def test_api_error_response(self, shazam_fixtures, mock_shazam):
        """Test handling of API error responses."""
        # Setup
        recognizer = ShazamioRecognizer()
        mock_shazam.recognize.return_value = shazam_fixtures["error_response"]
        
        with patch("app.recognizers.shazamio_recognizer.Shazam", return_value=mock_shazam):
            # Execute
            result = await recognizer.recognize(b"fake_wav_data")
        
        # Verify
        assert not result.is_success
        assert result.error_message == "Bad request"
        assert result.provider_track_id == ""
    
    @pytest.mark.asyncio
    async def test_timeout_handling(self, mock_shazam):
        """Test timeout handling."""
        # Setup
        recognizer = ShazamioRecognizer()
        mock_shazam.recognize.side_effect = Exception("Timeout simulation")
        
        with patch("app.recognizers.shazamio_recognizer.Shazam", return_value=mock_shazam):
            # Execute
            result = await recognizer.recognize(b"fake_wav_data", timeout_seconds=1.0)
        
        # Verify
        assert not result.is_success
        assert "Recognition failed" in result.error_message
        assert "Timeout simulation" in result.error_message
    
    @pytest.mark.asyncio
    async def test_confidence_calculation_high_quality(self):
        """Test confidence calculation for high quality matches."""
        recognizer = ShazamioRecognizer()
        
        # High quality match (low skews)
        match = {"timeskew": 0.00001, "frequencyskew": 0.000001}
        confidence = recognizer._calculate_confidence(match)
        
        assert confidence > 0.9
        assert confidence <= 1.0
    
    @pytest.mark.asyncio
    async def test_confidence_calculation_medium_quality(self):
        """Test confidence calculation for medium quality matches."""
        recognizer = ShazamioRecognizer()
        
        # Medium quality match
        match = {"timeskew": 0.0001, "frequencyskew": 0.00001}
        confidence = recognizer._calculate_confidence(match)
        
        assert 0.8 <= confidence <= 1.0
    
    @pytest.mark.asyncio
    async def test_confidence_calculation_low_quality(self):
        """Test confidence calculation for low quality matches."""
        recognizer = ShazamioRecognizer()
        
        # Low quality match (high skews)
        match = {"timeskew": 0.002, "frequencyskew": 0.0002}
        confidence = recognizer._calculate_confidence(match)
        
        assert confidence < 0.7
        assert confidence >= 0.0
    
    @pytest.mark.asyncio
    async def test_custom_timeout(self, shazam_fixtures, mock_shazam):
        """Test custom timeout parameter."""
        # Setup
        recognizer = ShazamioRecognizer(timeout_seconds=10.0)
        mock_shazam.recognize.return_value = shazam_fixtures["successful_match"]
        
        with patch("app.recognizers.shazamio_recognizer.Shazam", return_value=mock_shazam), \
             patch("asyncio.wait_for") as mock_wait:
            mock_wait.return_value = shazam_fixtures["successful_match"]
            
            # Execute with custom timeout
            await recognizer.recognize(b"fake_wav_data", timeout_seconds=5.0)
            
            # Verify timeout was used
            mock_wait.assert_called_once()
            args, kwargs = mock_wait.call_args
            assert kwargs["timeout"] == 5.0
    
    @pytest.mark.asyncio
    async def test_shazam_instance_reuse(self, shazam_fixtures):
        """Test that Shazam instance is reused across calls."""
        recognizer = ShazamioRecognizer()
        
        with patch("app.recognizers.shazamio_recognizer.Shazam") as mock_shazam_class:
            # Use MagicMock to avoid AsyncMock warnings
            mock_instance = MagicMock()
            call_count = 0
            # Configure the async method properly to avoid warnings
            async def mock_recognize(data):
                nonlocal call_count
                call_count += 1
                return shazam_fixtures["successful_match"]
            mock_instance.recognize = mock_recognize
            mock_shazam_class.return_value = mock_instance
            
            # Make multiple calls
            await recognizer.recognize(b"fake_wav_data1")
            await recognizer.recognize(b"fake_wav_data2")
            
            # Verify Shazam was only instantiated once
            mock_shazam_class.assert_called_once()
            assert call_count == 2


class TestFakeShazamioRecognizer:
    """Test cases for FakeShazamioRecognizer."""
    
    @pytest.mark.asyncio
    async def test_successful_fixture_response(self, shazam_fixtures):
        """Test fake recognizer with successful fixture."""
        # Setup
        recognizer = FakeShazamioRecognizer(
            fixture_responses=shazam_fixtures,
            current_fixture="successful_match"
        )
        
        # Execute
        result = await recognizer.recognize(b"fake_wav_data")
        
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
            fixture_responses=shazam_fixtures,
            current_fixture="no_match"
        )
        
        # Execute
        result = await recognizer.recognize(b"fake_wav_data")
        
        # Verify
        assert result.is_no_match
        assert not result.is_success
    
    @pytest.mark.asyncio
    async def test_timeout_simulation(self, shazam_fixtures):
        """Test fake recognizer timeout simulation."""
        # Setup
        recognizer = FakeShazamioRecognizer(
            fixture_responses=shazam_fixtures,
            should_timeout=True
        )
        
        # Execute
        result = await recognizer.recognize(b"fake_wav_data", timeout_seconds=5.0)
        
        # Verify
        assert not result.is_success
        assert "timed out after 5.0s" in result.error_message
    
    @pytest.mark.asyncio
    async def test_failure_simulation(self, shazam_fixtures):
        """Test fake recognizer failure simulation."""
        # Setup
        recognizer = FakeShazamioRecognizer(
            fixture_responses=shazam_fixtures,
            should_fail=True
        )
        
        # Execute
        result = await recognizer.recognize(b"fake_wav_data")
        
        # Verify
        assert not result.is_success
        assert "Simulated recognition failure" in result.error_message
    
    @pytest.mark.asyncio
    async def test_call_count_increment(self, shazam_fixtures):
        """Test that call count increments properly."""
        # Setup
        recognizer = FakeShazamioRecognizer(
            fixture_responses=shazam_fixtures,
            current_fixture="successful_match"
        )
        
        # Execute multiple calls
        await recognizer.recognize(b"fake_wav_data")
        await recognizer.recognize(b"fake_wav_data")
        await recognizer.recognize(b"fake_wav_data")
        
        # Verify
        assert recognizer.call_count == 3


@pytest.mark.asyncio
async def test_integration_multiple_recognizers():
    """Integration test with multiple recognizers running in parallel."""
    # Setup
    recognizers = [
        FakeShazamioRecognizer(should_fail=False),
        FakeShazamioRecognizer(should_timeout=True),
        FakeShazamioRecognizer(should_fail=True)
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
