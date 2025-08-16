"""Shazam recognition implementation using shazamio library."""

import asyncio
import datetime as dt
import logging
from datetime import datetime
from typing import Any

from shazamio import Shazam  # type: ignore[import-untyped]

from .base import MusicRecognizer, RecognitionResult

logger = logging.getLogger(__name__)


class ShazamioRecognizer(MusicRecognizer):
    """Shazam music recognizer using the shazamio library."""

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        """Initialize Shazam recognizer.

        Args:
            timeout_seconds: Default timeout for recognition requests.
        """
        self.timeout_seconds = timeout_seconds
        self._shazam: Shazam | None = None

    async def _get_shazam(self) -> Shazam:
        """Get or create Shazam instance."""
        if self._shazam is None:
            self._shazam = Shazam()
        return self._shazam

    async def recognize(
        self, wav_bytes: bytes, timeout_seconds: float = 30.0
    ) -> RecognitionResult:
        """Recognize music using Shazam API.

        Args:
            wav_bytes: WAV audio data as bytes.
            timeout_seconds: Maximum time to wait for recognition.

        Returns:
            RecognitionResult with Shazam track information or error details.
        """
        recognized_at = dt.datetime.now(dt.UTC).replace(tzinfo=None)

        try:
            # Use provided timeout or default
            actual_timeout = timeout_seconds or self.timeout_seconds

            shazam = await self._get_shazam()

            # Perform recognition with timeout
            response = await asyncio.wait_for(
                shazam.recognize(wav_bytes), timeout=actual_timeout
            )

            logger.debug(f"Shazam response: {response}")

            # Parse response
            return self._parse_shazam_response(response, recognized_at)

        except TimeoutError:
            logger.warning(f"Shazam recognition timed out after {actual_timeout}s")
            return RecognitionResult(
                provider="shazam",
                provider_track_id="",
                title="",
                artist="",
                recognized_at_utc=recognized_at,
                error_message=f"Recognition timed out after {actual_timeout}s",
            )
        except Exception as e:
            logger.error(f"Shazam recognition failed: {e}")
            return RecognitionResult(
                provider="shazam",
                provider_track_id="",
                title="",
                artist="",
                recognized_at_utc=recognized_at,
                error_message=f"Recognition failed: {str(e)}",
            )

    def _parse_shazam_response(
        self, response: dict[str, Any], recognized_at: datetime
    ) -> RecognitionResult:
        """Parse Shazam API response into RecognitionResult.

        Args:
            response: Raw Shazam API response.
            recognized_at: Timestamp when recognition was performed.

        Returns:
            RecognitionResult with parsed track information.
        """
        # Check for error in response
        if "error" in response:
            error_msg = response["error"].get("message", "Unknown Shazam error")
            return RecognitionResult(
                provider="shazam",
                provider_track_id="",
                title="",
                artist="",
                recognized_at_utc=recognized_at,
                error_message=error_msg,
                raw_response=response,
            )

        # Check for matches
        matches = response.get("matches", [])
        track_data = response.get("track")

        if not matches or not track_data:
            # No match found
            logger.debug("No Shazam match found")
            return RecognitionResult(
                provider="shazam",
                provider_track_id="",
                title="",
                artist="",
                recognized_at_utc=recognized_at,
                raw_response=response,
            )

        # Extract track information
        track_id = track_data.get("key", "")
        title = track_data.get("title", "")
        artist = track_data.get("subtitle", "")  # Shazam uses 'subtitle' for artist

        # Extract optional metadata
        album = None
        isrc = track_data.get("isrc")
        artwork_url = None

        # Get album from sections metadata
        sections = track_data.get("sections", [])
        for section in sections:
            if section.get("type") == "SONG":
                metadata = section.get("metadata", [])
                for meta in metadata:
                    if meta.get("title") == "Album":
                        album = meta.get("text")
                        break
                break

        # Get artwork URL
        images = track_data.get("images", {})
        artwork_url = images.get("coverart") or images.get("background")

        # Calculate confidence based on match quality
        # Shazam doesn't provide explicit confidence, so we estimate based on:
        # - Time skew (lower is better)
        # - Frequency skew (lower is better)
        # - Offset (doesn't affect confidence much)
        confidence = self._calculate_confidence(matches[0])

        return RecognitionResult(
            provider="shazam",
            provider_track_id=track_id,
            title=title,
            artist=artist,
            recognized_at_utc=recognized_at,
            album=album,
            isrc=isrc,
            artwork_url=artwork_url,
            confidence=confidence,
            raw_response=response,
        )

    def _calculate_confidence(self, match: dict[str, Any]) -> float:
        """Calculate confidence score from Shazam match data.

        Args:
            match: Match data from Shazam response.

        Returns:
            Confidence score between 0.0 and 1.0.
        """
        # Extract skew values (default to 0 if missing)
        time_skew = abs(match.get("timeskew", 0.0))
        freq_skew = abs(match.get("frequencyskew", 0.0))

        # Empirical confidence calculation based on skew values
        # Lower skew = higher confidence
        # These thresholds are rough estimates based on observed Shazam behavior

        confidence = 1.0

        # Penalize time skew (significant impact)
        if time_skew > 0.001:  # 1ms
            confidence *= 0.6
        elif time_skew > 0.0001:  # 0.1ms
            confidence *= 0.8

        # Penalize frequency skew (moderate impact)
        if freq_skew > 0.0001:  # 0.01%
            confidence *= 0.7
        elif freq_skew > 0.00001:  # 0.001%
            confidence *= 0.9

        # Ensure confidence is in valid range
        return max(0.0, min(1.0, confidence))


class FakeShazamioRecognizer(MusicRecognizer):
    """Fake Shazam recognizer for testing."""

    def __init__(
        self,
        fixture_responses: dict[str, dict[str, Any]] | None = None,
        current_fixture: str = "successful_match",
        should_timeout: bool = False,
        should_fail: bool = False,
    ) -> None:
        """Initialize fake Shazam recognizer.

        Args:
            fixture_responses: Pre-loaded fixture responses.
            current_fixture: Which fixture to use for recognition.
            should_timeout: Whether to simulate timeouts.
            should_fail: Whether to simulate general failures.
        """
        self.fixture_responses = fixture_responses or {}
        self.current_fixture = current_fixture
        self.should_timeout = should_timeout
        self.should_fail = should_fail
        self.call_count = 0

    async def recognize(
        self, wav_bytes: bytes, timeout_seconds: float = 30.0
    ) -> RecognitionResult:
        """Return pre-configured fixture responses."""
        self.call_count += 1
        recognized_at = dt.datetime.now(dt.UTC).replace(tzinfo=None)

        # Simulate timeout
        if self.should_timeout:
            await asyncio.sleep(0.001)  # Brief sleep for realism
            return RecognitionResult(
                provider="shazam",
                provider_track_id="",
                title="",
                artist="",
                recognized_at_utc=recognized_at,
                error_message=f"Recognition timed out after {timeout_seconds}s",
            )

        # Simulate general failure
        if self.should_fail:
            return RecognitionResult(
                provider="shazam",
                provider_track_id="",
                title="",
                artist="",
                recognized_at_utc=recognized_at,
                error_message="Simulated recognition failure",
            )

        # Get fixture response
        response = self.fixture_responses.get(self.current_fixture, {})

        # Use real parser for consistency
        real_recognizer = ShazamioRecognizer()
        return real_recognizer._parse_shazam_response(response, recognized_at)
