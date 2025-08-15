"""AcoustID recognition implementation using chromaprint and AcoustID API."""

import asyncio
import json
import logging
import subprocess
import tempfile
from datetime import datetime
import datetime as dt
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp

from .base import MusicRecognizer, RecognitionResult

logger = logging.getLogger(__name__)


class AcoustIDRecognizer(MusicRecognizer):
    """AcoustID music recognizer using chromaprint and AcoustID API."""
    
    def __init__(
        self, 
        api_key: str,
        chromaprint_path: str = "/usr/bin/fpcalc",
        timeout_seconds: float = 30.0
    ) -> None:
        """Initialize AcoustID recognizer.
        
        Args:
            api_key: AcoustID API key.
            chromaprint_path: Path to fpcalc binary.
            timeout_seconds: Default timeout for recognition requests.
        """
        self.api_key = api_key
        self.chromaprint_path = chromaprint_path
        self.timeout_seconds = timeout_seconds
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout_seconds + 5)
            )
        return self._session
    
    async def close(self) -> None:
        """Clean up HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def recognize(
        self, 
        wav_bytes: bytes, 
        timeout_seconds: float = 30.0
    ) -> RecognitionResult:
        """Recognize music using AcoustID API.
        
        Args:
            wav_bytes: WAV audio data as bytes.
            timeout_seconds: Maximum time to wait for recognition.
            
        Returns:
            RecognitionResult with AcoustID track information or error details.
        """
        recognized_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        actual_timeout = timeout_seconds or self.timeout_seconds
        
        try:
            # Generate fingerprint from audio
            fingerprint = await self._generate_fingerprint(wav_bytes, actual_timeout)
            if not fingerprint:
                return RecognitionResult(
                    provider="acoustid",
                    provider_track_id="",
                    title="",
                    artist="",
                    recognized_at_utc=recognized_at,
                    error_message="Failed to generate audio fingerprint"
                )
            
            # Query AcoustID API
            response = await self._query_acoustid(fingerprint, actual_timeout)
            
            # Parse response
            return self._parse_acoustid_response(response, recognized_at)
            
        except asyncio.TimeoutError:
            logger.warning(f"AcoustID recognition timed out after {actual_timeout}s")
            return RecognitionResult(
                provider="acoustid",
                provider_track_id="",
                title="",
                artist="",
                recognized_at_utc=recognized_at,
                error_message=f"Recognition timed out after {actual_timeout}s"
            )
        except Exception as e:
            logger.error(f"AcoustID recognition failed: {e}")
            return RecognitionResult(
                provider="acoustid",
                provider_track_id="",
                title="",
                artist="",
                recognized_at_utc=recognized_at,
                error_message=f"Recognition failed: {str(e)}"
            )
    
    async def _generate_fingerprint(
        self, 
        wav_bytes: bytes, 
        timeout_seconds: float
    ) -> Optional[str]:
        """Generate acoustic fingerprint using fpcalc.
        
        Args:
            wav_bytes: WAV audio data.
            timeout_seconds: Timeout for fingerprint generation.
            
        Returns:
            Fingerprint string or None if generation failed.
        """
        try:
            # Write WAV data to temporary file
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
                tmp_file.write(wav_bytes)
                tmp_path = tmp_file.name
            
            try:
                # Run fpcalc to generate fingerprint
                process = await asyncio.create_subprocess_exec(
                    self.chromaprint_path,
                    "-json",
                    tmp_path,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout_seconds
                )
                
                if process.returncode != 0:
                    error_msg = stderr.decode() if stderr else "Unknown fpcalc error"
                    logger.error(f"fpcalc failed: {error_msg}")
                    return None
                
                # Parse JSON output
                result = json.loads(stdout.decode())
                fingerprint = result.get("fingerprint")
                
                if not fingerprint:
                    logger.error("fpcalc returned no fingerprint")
                    return None
                
                logger.debug(f"Generated fingerprint: {fingerprint[:50]}...")
                return fingerprint
                
            finally:
                # Clean up temporary file
                Path(tmp_path).unlink(missing_ok=True)
                
        except Exception as e:
            logger.error(f"Fingerprint generation failed: {e}")
            return None
    
    async def _query_acoustid(
        self, 
        fingerprint: str, 
        timeout_seconds: float
    ) -> Dict[str, Any]:
        """Query AcoustID API with fingerprint.
        
        Args:
            fingerprint: Audio fingerprint string.
            timeout_seconds: Timeout for API request.
            
        Returns:
            AcoustID API response as dictionary.
        """
        session = await self._get_session()
        
        # Prepare API request
        url = "https://api.acoustid.org/v2/lookup"
        data = {
            "client": self.api_key,
            "fingerprint": fingerprint,
            "meta": "recordings+releases+artists",
            "format": "json"
        }
        
        # Make API request
        async with session.post(url, data=data) as response:
            response_data = await response.json()
            
            logger.debug(f"AcoustID response status: {response.status}")
            
            if response.status != 200:
                error_msg = f"AcoustID API error: HTTP {response.status}"
                response_data["error"] = {"message": error_msg, "code": response.status}
            
            return response_data
    
    def _parse_acoustid_response(
        self, 
        response: Dict[str, Any], 
        recognized_at: datetime
    ) -> RecognitionResult:
        """Parse AcoustID API response into RecognitionResult.
        
        Args:
            response: Raw AcoustID API response.
            recognized_at: Timestamp when recognition was performed.
            
        Returns:
            RecognitionResult with parsed track information.
        """
        # Check for error in response
        if "error" in response:
            error_msg = response["error"].get("message", "Unknown AcoustID error")
            return RecognitionResult(
                provider="acoustid",
                provider_track_id="",
                title="",
                artist="",
                recognized_at_utc=recognized_at,
                error_message=error_msg,
                raw_response=response
            )
        
        # Check response status
        status = response.get("status")
        if status != "ok":
            error_msg = f"AcoustID API returned status: {status}"
            return RecognitionResult(
                provider="acoustid",
                provider_track_id="",
                title="",
                artist="",
                recognized_at_utc=recognized_at,
                error_message=error_msg,
                raw_response=response
            )
        
        # Check for results
        results = response.get("results", [])
        if not results:
            logger.debug("No AcoustID match found")
            return RecognitionResult(
                provider="acoustid",
                provider_track_id="",
                title="",
                artist="",
                recognized_at_utc=recognized_at,
                raw_response=response
            )
        
        # Get best match (highest score)
        best_result = max(results, key=lambda r: r.get("score", 0.0))
        
        # Extract track information
        track_id = best_result.get("id", "")
        score = best_result.get("score", 0.0)
        
        # Get recording information
        recordings = best_result.get("recordings", [])
        if not recordings:
            logger.debug("No recording data in AcoustID result")
            return RecognitionResult(
                provider="acoustid",
                provider_track_id=track_id,
                title="",
                artist="",
                recognized_at_utc=recognized_at,
                confidence=score,
                raw_response=response
            )
        
        # Use first recording (usually the most canonical)
        recording = recordings[0]
        title = recording.get("title", "")
        
        # Extract artist(s)
        artists = recording.get("artists", [])
        artist = ", ".join(a.get("name", "") for a in artists if a.get("name"))
        
        # Extract album from releases
        album = None
        releases = recording.get("releases", [])
        if releases:
            # Prefer releases with dates or specific countries
            release = self._select_best_release(releases)
            album = release.get("title")
        
        return RecognitionResult(
            provider="acoustid",
            provider_track_id=track_id,
            title=title,
            artist=artist,
            recognized_at_utc=recognized_at,
            album=album,
            confidence=score,
            raw_response=response
        )
    
    def _select_best_release(self, releases: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Select the best release from multiple options.
        
        Args:
            releases: List of release dictionaries.
            
        Returns:
            Best release dictionary.
        """
        if not releases:
            return {}
        
        # Prefer releases with dates
        dated_releases = [r for r in releases if r.get("date")]
        if dated_releases:
            releases = dated_releases
        
        # Prefer releases from major markets (US, GB, etc.)
        major_countries = {"US", "GB", "DE", "FR", "JP"}
        major_releases = [r for r in releases if r.get("country") in major_countries]
        if major_releases:
            releases = major_releases
        
        # Return first remaining release
        return releases[0]


class FakeAcoustIDRecognizer(MusicRecognizer):
    """Fake AcoustID recognizer for testing."""
    
    def __init__(
        self,
        fixture_responses: Optional[Dict[str, Dict[str, Any]]] = None,
        current_fixture: str = "successful_match",
        should_timeout: bool = False,
        should_fail: bool = False,
        fingerprint_should_fail: bool = False
    ) -> None:
        """Initialize fake AcoustID recognizer.
        
        Args:
            fixture_responses: Pre-loaded fixture responses.
            current_fixture: Which fixture to use for recognition.
            should_timeout: Whether to simulate timeouts.
            should_fail: Whether to simulate general failures.
            fingerprint_should_fail: Whether to simulate fingerprint generation failures.
        """
        self.fixture_responses = fixture_responses or {}
        self.current_fixture = current_fixture
        self.should_timeout = should_timeout
        self.should_fail = should_fail
        self.fingerprint_should_fail = fingerprint_should_fail
        self.call_count = 0
    
    async def recognize(
        self, 
        wav_bytes: bytes, 
        timeout_seconds: float = 30.0
    ) -> RecognitionResult:
        """Return pre-configured fixture responses."""
        self.call_count += 1
        recognized_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        
        # Simulate timeout
        if self.should_timeout:
            await asyncio.sleep(0.001)  # Brief sleep for realism
            return RecognitionResult(
                provider="acoustid",
                provider_track_id="",
                title="",
                artist="",
                recognized_at_utc=recognized_at,
                error_message=f"Recognition timed out after {timeout_seconds}s"
            )
        
        # Simulate fingerprint failure
        if self.fingerprint_should_fail:
            return RecognitionResult(
                provider="acoustid",
                provider_track_id="",
                title="",
                artist="",
                recognized_at_utc=recognized_at,
                error_message="Failed to generate audio fingerprint"
            )
        
        # Simulate general failure
        if self.should_fail:
            return RecognitionResult(
                provider="acoustid",
                provider_track_id="",
                title="",
                artist="",
                recognized_at_utc=recognized_at,
                error_message="Simulated recognition failure"
            )
        
        # Get fixture response
        response = self.fixture_responses.get(self.current_fixture, {})
        
        # Use real parser for consistency
        real_recognizer = AcoustIDRecognizer(api_key="fake", chromaprint_path="/fake")
        return real_recognizer._parse_acoustid_response(response, recognized_at)
    
    async def close(self) -> None:
        """No-op for fake recognizer."""
        pass
