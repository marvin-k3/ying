"""Integration tests for recognizers using live APIs.

These tests require real network access and API keys.
Run with: YING_ENABLE_LIVE_TESTS=1 rye run test tests/integration/
"""

import os
import pytest
from pathlib import Path

from app.recognizers.shazamio_recognizer import ShazamioRecognizer
from app.recognizers.acoustid_recognizer import AcoustIDRecognizer


# Skip all tests in this module unless explicitly enabled
pytestmark = pytest.mark.skipif(
    not os.getenv("YING_ENABLE_LIVE_TESTS"),
    reason="Live API tests disabled. Set YING_ENABLE_LIVE_TESTS=1 to enable."
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
        "sample.wav"  # Our generated synthetic audio
    ]
    
    for filename in real_audio_files:
        audio_path = test_data_dir / filename
        if audio_path.exists():
            print(f"📂 Using audio file: {filename}")
            return audio_path.read_bytes()
    
    # Generate a simple synthetic WAV file (440Hz sine wave, 12 seconds)
    import wave
    import math
    import struct
    import tempfile
    
    # WAV parameters
    sample_rate = 44100
    duration = 12  # seconds
    frequency = 440  # Hz (A4 note)
    
    # Generate sine wave
    samples = []
    for i in range(int(sample_rate * duration)):
        value = int(32767 * math.sin(2 * math.pi * frequency * i / sample_rate))
        samples.append(struct.pack('<h', value))
    
    # Create WAV file in memory
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
        with wave.open(tmp_file.name, 'wb') as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 2 bytes per sample
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(b''.join(samples))
        
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
                print(f"\n🔍 Shazam found no match for the audio sample")
            else:
                print(f"\n❌ Shazam API error: {result.error_message}")
            
            # Should not have any exceptions or malformed responses
            assert result.error_message is None or "Recognition failed:" not in result.error_message
            
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


class TestAcoustIDIntegration:
    """Integration tests for AcoustID API."""
    
    @pytest.fixture
    def acoustid_api_key(self):
        """Get AcoustID API key from environment."""
        api_key = os.getenv("ACOUSTID_API_KEY")
        if not api_key:
            pytest.skip("ACOUSTID_API_KEY environment variable not set")
        return api_key
    
    @pytest.mark.asyncio
    async def test_acoustid_real_api_call(self, sample_audio_data, acoustid_api_key):
        """Test actual AcoustID API call with sample audio."""
        recognizer = AcoustIDRecognizer(
            api_key=acoustid_api_key,
            chromaprint_path="/usr/bin/fpcalc",  # May need adjustment based on system
            timeout_seconds=30.0
        )
        
        try:
            # Make real API call
            result = await recognizer.recognize(sample_audio_data, timeout_seconds=30.0)
            
            # Verify result structure
            assert result.provider == "acoustid"
            assert result.recognized_at_utc is not None
            assert result.raw_response is not None
            
            # Log result for manual verification
            if result.is_success:
                print(f"\n✅ AcoustID recognized: '{result.title}' by '{result.artist}'")
                print(f"   Track ID: {result.provider_track_id}")
                print(f"   Confidence: {result.confidence}")
                if result.album:
                    print(f"   Album: {result.album}")
            elif result.is_no_match:
                print(f"\n🔍 AcoustID found no match for the audio sample")
            else:
                print(f"\n❌ AcoustID error: {result.error_message}")
            
            # Should not have any exceptions or malformed responses
            assert result.error_message is None or "Recognition failed:" not in result.error_message
            
        except Exception as e:
            pytest.fail(f"AcoustID integration test failed with exception: {e}")
        finally:
            # Clean up HTTP session
            await recognizer.close()
    
    @pytest.mark.asyncio
    async def test_acoustid_fingerprint_generation(self, sample_audio_data, acoustid_api_key):
        """Test fingerprint generation with real audio."""
        recognizer = AcoustIDRecognizer(
            api_key=acoustid_api_key,
            chromaprint_path="/usr/bin/fpcalc"
        )
        
        try:
            # Test fingerprint generation directly
            fingerprint = await recognizer._generate_fingerprint(sample_audio_data, 30.0)
            
            if fingerprint:
                print(f"\n🔢 Generated fingerprint: {fingerprint[:50]}...")
                assert isinstance(fingerprint, str)
                assert len(fingerprint) > 0
            else:
                print(f"\n❌ Failed to generate fingerprint (fpcalc may not be installed)")
                pytest.skip("Could not generate fingerprint - fpcalc may not be available")
        
        finally:
            await recognizer.close()
    
    @pytest.mark.asyncio
    async def test_acoustid_invalid_api_key(self, sample_audio_data):
        """Test AcoustID with invalid API key."""
        recognizer = AcoustIDRecognizer(
            api_key="invalid_key_12345",
            chromaprint_path="/usr/bin/fpcalc"
        )
        
        try:
            result = await recognizer.recognize(sample_audio_data, timeout_seconds=10.0)
            
            # Should handle invalid API key gracefully
            assert result.provider == "acoustid"
            # Depending on AcoustID's response, this might be an error or no match
            
        finally:
            await recognizer.close()


class TestParallelIntegration:
    """Integration tests for parallel recognition with live APIs."""
    
    @pytest.mark.asyncio
    async def test_parallel_shazam_acoustid_real_apis(self, sample_audio_data):
        """Test running Shazam and AcoustID in parallel with real APIs."""
        # Setup recognizers
        shazam = ShazamioRecognizer(timeout_seconds=30.0)
        
        acoustid_key = os.getenv("ACOUSTID_API_KEY")
        if acoustid_key:
            acoustid = AcoustIDRecognizer(
                api_key=acoustid_key,
                chromaprint_path="/usr/bin/fpcalc",
                timeout_seconds=30.0
            )
        else:
            print("\n⚠️  ACOUSTID_API_KEY not set, testing Shazam only")
            acoustid = None
        
        try:
            # Run in parallel
            import asyncio
            tasks = [shazam.recognize(sample_audio_data, timeout_seconds=30.0)]
            if acoustid:
                tasks.append(acoustid.recognize(sample_audio_data, timeout_seconds=30.0))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Verify no exceptions occurred
            for i, result in enumerate(results):
                provider = "shazam" if i == 0 else "acoustid"
                if isinstance(result, Exception):
                    print(f"\n❌ {provider} failed with exception: {result}")
                else:
                    if result.is_success:
                        print(f"\n✅ {provider}: '{result.title}' by '{result.artist}'")
                    elif result.is_no_match:
                        print(f"\n🔍 {provider}: no match found")
                    else:
                        print(f"\n⚠️  {provider}: {result.error_message}")
                
                assert not isinstance(result, Exception), f"{provider} should not raise exceptions"
            
        finally:
            if acoustid:
                await acoustid.close()


@pytest.mark.asyncio
async def test_integration_environment_check():
    """Test that the integration test environment is properly configured."""
    print("\n🔧 Integration test environment check:")
    
    # Check for live tests flag
    live_tests_enabled = os.getenv("YING_ENABLE_LIVE_TESTS")
    print(f"   YING_ENABLE_LIVE_TESTS: {live_tests_enabled}")
    
    # Check for AcoustID API key
    acoustid_key = os.getenv("ACOUSTID_API_KEY")
    print(f"   ACOUSTID_API_KEY: {'✅ Set' if acoustid_key else '❌ Not set'}")
    
    # Check for fpcalc binary
    import shutil
    fpcalc_path = shutil.which("fpcalc")
    print(f"   fpcalc binary: {'✅ Found at ' + fpcalc_path if fpcalc_path else '❌ Not found'}")
    
    # Basic connectivity test
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get("https://httpbin.org/get", timeout=5) as response:
                connectivity = response.status == 200
    except Exception:
        connectivity = False
    
    print(f"   Internet connectivity: {'✅ Available' if connectivity else '❌ Unavailable'}")
    
    assert live_tests_enabled, "Live tests not enabled"
