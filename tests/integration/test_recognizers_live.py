"""Integration tests for recognizers using live APIs.

These tests require real network access and API keys.
Run with: YING_ENABLE_LIVE_TESTS=1 rye run test tests/integration/
"""

import os
from pathlib import Path

import pytest

# AcoustID support removed - only Shazam is supported
from app.recognizers.shazamio_recognizer import ShazamioRecognizer

# Skip all tests in this module unless explicitly enabled
pytestmark = pytest.mark.skipif(
    not os.getenv("YING_ENABLE_LIVE_TESTS"),
    reason="Live API tests disabled. Set YING_ENABLE_LIVE_TESTS=1 to enable.",
)


@pytest.fixture
def sample_audio_data():
    """Load a sample audio file for testing.

    This fixture looks for real audio files in the test data directory.
    Priority order: real music files, then synthetic sample.
    """
    test_data_dir = Path(__file__).parent.parent / "data"

    # Try real music files first (most likely to be recognized)
    real_audio_files = [
        "william_tell_gallop.wav",  # Classical music (WAV for broad compatibility)
        "william_tell_gallop.ogg",  # Classical music (OGG fallback)
        "sample.wav",  # Our generated synthetic audio
    ]

    for filename in real_audio_files:
        audio_path = test_data_dir / filename
        if audio_path.exists():
            print(f"📂 Using audio file: {filename}")
            return audio_path.read_bytes()

    # Generate a simple synthetic WAV file (440Hz sine wave, 12 seconds)
    import math
    import struct
    import tempfile
    import wave

    # WAV parameters
    sample_rate = 44100
    duration = 12  # seconds
    frequency = 440  # Hz (A4 note)

    # Generate sine wave
    samples = []
    for i in range(int(sample_rate * duration)):
        value = int(32767 * math.sin(2 * math.pi * frequency * i / sample_rate))
        samples.append(struct.pack("<h", value))

    # Create WAV file in memory
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
        with wave.open(tmp_file.name, "wb") as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 2 bytes per sample
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(b"".join(samples))

        # Read the WAV data
        tmp_file.seek(0)
        wav_data = Path(tmp_file.name).read_bytes()

        # Clean up temp file
        os.unlink(tmp_file.name)

        return wav_data


class TestShazamIntegration:
    """Integration tests for Shazam API."""

    @pytest.mark.asyncio
    async def test_shazam_real_api_call(self, sample_audio_data):
        """Test actual Shazam API call with sample audio."""
        recognizer = ShazamioRecognizer(timeout_seconds=30.0)

        try:
            # Make real API call
            result = await recognizer.recognize(sample_audio_data, timeout_seconds=30.0)

            # Verify result structure (content depends on what Shazam recognizes)
            assert result.provider == "shazam"
            assert result.recognized_at_utc is not None
            assert result.raw_response is not None

            # Log result for manual verification
            if result.is_success:
                print(f"\n✅ Shazam recognized: '{result.title}' by '{result.artist}'")
                print(f"   Track ID: {result.provider_track_id}")
                print(f"   Confidence: {result.confidence}")
                if result.album:
                    print(f"   Album: {result.album}")
                if result.isrc:
                    print(f"   ISRC: {result.isrc}")
            elif result.is_no_match:
                print("\n🔍 Shazam found no match for the audio sample")
            else:
                print(f"\n❌ Shazam API error: {result.error_message}")

            # Should not have any exceptions or malformed responses
            assert (
                result.error_message is None
                or "Recognition failed:" not in result.error_message
            )

        except Exception as e:
            pytest.fail(f"Shazam integration test failed with exception: {e}")

    @pytest.mark.asyncio
    async def test_shazam_timeout_handling(self, sample_audio_data):
        """Test Shazam timeout handling with very short timeout."""
        recognizer = ShazamioRecognizer()

        # Use very short timeout to force timeout
        result = await recognizer.recognize(sample_audio_data, timeout_seconds=0.1)

        # Should handle timeout gracefully
        assert not result.is_success
        assert "timed out" in result.error_message.lower()
        assert result.provider == "shazam"

    @pytest.mark.asyncio
    async def test_shazam_invalid_audio_data(self):
        """Test Shazam with invalid audio data."""
        recognizer = ShazamioRecognizer()

        # Test with invalid audio data
        invalid_data = b"not_valid_audio_data"
        result = await recognizer.recognize(invalid_data, timeout_seconds=10.0)

        # Should handle gracefully (either error or no match)
        assert result.provider == "shazam"
        assert not result.is_success or result.is_no_match


# AcoustID integration tests removed - only Shazam is supported


class TestParallelIntegration:
    """Integration tests for parallel recognition with live APIs."""

    @pytest.mark.asyncio
    async def test_parallel_shazam_only_real_apis(self, sample_audio_data):
        """Test running Shazam recognition with real API."""
        # Setup recognizer
        shazam = ShazamioRecognizer(timeout_seconds=30.0)

        try:
            # Run recognition
            result = await shazam.recognize(sample_audio_data, timeout_seconds=30.0)

            # Verify no exceptions occurred
            if result.is_success:
                print(f"\n✅ Shazam: '{result.title}' by '{result.artist}'")
            elif result.is_no_match:
                print("\n🔍 Shazam: no match found")
            else:
                print(f"\n⚠️  Shazam: {result.error_message}")

            assert result.provider == "shazam"

        except Exception as e:
            pytest.fail(f"Shazam should not raise exceptions: {e}")


@pytest.mark.asyncio
async def test_integration_environment_check():
    """Test that the integration test environment is properly configured."""
    print("\n🔧 Integration test environment check:")

    # Check for live tests flag
    live_tests_enabled = os.getenv("YING_ENABLE_LIVE_TESTS")
    print(f"   YING_ENABLE_LIVE_TESTS: {live_tests_enabled}")

    # AcoustID support removed - only Shazam is supported

    # Basic connectivity test
    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.get("https://httpbin.org/get", timeout=5) as response:
                connectivity = response.status == 200
    except Exception:
        connectivity = False

    print(
        f"   Internet connectivity: {'✅ Available' if connectivity else '❌ Unavailable'}"
    )

    assert live_tests_enabled, "Live tests not enabled"
