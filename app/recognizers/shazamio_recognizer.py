"""Shazam recognition implementation using shazamio library."""

import asyncio
import datetime as dt
import logging
import os
import struct
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from shazamio import Shazam  # type: ignore[import-untyped]

from .base import MusicRecognizer, RecognitionResult

logger = logging.getLogger(__name__)


def _validate_wav_header(wav_bytes: bytes) -> bool:
    """Validate WAV header format to ensure compatibility with Symphonia.

    Args:
            wav_bytes: WAV audio data as bytes.

    Returns:
            True if WAV header is valid, False otherwise.
    """
    if len(wav_bytes) < 44:  # Minimum WAV header size
        logger.warning("WAV data too short to contain valid header")
        return False

    try:
        # Check RIFF header
        if wav_bytes[:4] != b"RIFF":
            logger.warning("Invalid WAV header: missing RIFF signature")
            return False

        # Check WAVE format
        if wav_bytes[8:12] != b"WAVE":
            logger.warning("Invalid WAV header: missing WAVE format")
            return False

        # Check fmt chunk
        if wav_bytes[12:16] != b"fmt ":
            logger.warning("Invalid WAV header: missing fmt chunk")
            return False

        # Check audio format (should be PCM = 1)
        audio_format = struct.unpack("<H", wav_bytes[20:22])[0]
        if audio_format != 1:
            logger.warning(
                f"Invalid WAV audio format: {audio_format} (expected 1 for PCM)"
            )
            return False

        # Check channels
        channels = struct.unpack("<H", wav_bytes[22:24])[0]
        if channels not in [1, 2]:
            logger.warning(f"Invalid WAV channels: {channels} (expected 1 or 2)")
            return False

        # Check sample rate
        sample_rate = struct.unpack("<I", wav_bytes[24:28])[0]
        if sample_rate not in [8000, 11025, 16000, 22050, 44100, 48000]:
            logger.warning(f"Invalid WAV sample rate: {sample_rate}")
            return False

        # Check bits per sample
        bits_per_sample = struct.unpack("<H", wav_bytes[34:36])[0]
        if bits_per_sample != 16:
            logger.warning(
                f"Invalid WAV bits per sample: {bits_per_sample} (expected 16)"
            )
            return False

        return True

    except struct.error as e:
        logger.warning(f"Error parsing WAV header: {e}")
        return False


def _reconstruct_wav_header(
    pcm_data: bytes, sample_rate: int = 44100, channels: int = 1
) -> bytes:
    """Reconstruct a proper WAV header for raw PCM data.

    Args:
            pcm_data: Raw PCM audio data (16-bit signed little-endian).
            sample_rate: Sample rate in Hz (default: 44100).
            channels: Number of channels (default: 1).

    Returns:
            WAV data with proper header.
    """
    # Calculate sizes
    data_size = len(pcm_data)
    file_size = 36 + data_size  # 36 bytes for header + data

    # Build WAV header
    header = bytearray()

    # RIFF header
    header.extend(b"RIFF")
    header.extend(struct.pack("<I", file_size))
    header.extend(b"WAVE")

    # fmt chunk
    header.extend(b"fmt ")
    header.extend(struct.pack("<I", 16))  # fmt chunk size
    header.extend(struct.pack("<H", 1))  # PCM format
    header.extend(struct.pack("<H", channels))
    header.extend(struct.pack("<I", sample_rate))
    header.extend(struct.pack("<I", sample_rate * channels * 2))  # byte rate
    header.extend(struct.pack("<H", channels * 2))  # block align
    header.extend(struct.pack("<H", 16))  # bits per sample

    # data chunk
    header.extend(b"data")
    header.extend(struct.pack("<I", data_size))

    # Combine header and data
    return bytes(header) + pcm_data


def _maybe_dump_audio(wav_bytes: bytes, tag: str) -> None:
    """Optionally dump WAV bytes to disk for debugging if YING_AUDIO_DUMP_DIR is set."""
    dump_dir_str = os.environ.get("YING_AUDIO_DUMP_DIR")
    if not dump_dir_str:
        return
    try:
        dump_dir = Path(dump_dir_str)
        dump_dir.mkdir(parents=True, exist_ok=True)
        ts = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S_%fZ")
        file_name = f"{ts}_{tag}_{uuid.uuid4().hex}.wav"
        file_path = dump_dir / file_name
        file_path.write_bytes(wav_bytes)
        logger.info(
            "Dumped audio sample",
            extra={"path": str(file_path), "bytes": len(wav_bytes), "tag": tag},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to dump audio sample", extra={"error": str(exc)})


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
            # Validate WAV format before sending to Shazam
            if not _validate_wav_header(wav_bytes):
                _maybe_dump_audio(wav_bytes, tag="invalid_header")

                # Try to reconstruct WAV header if this looks like raw PCM data
                if (
                    len(wav_bytes) > 1024 and len(wav_bytes) % 2 == 0
                ):  # Reasonable size and even bytes
                    logger.info("Attempting to reconstruct WAV header for raw PCM data")
                    try:
                        reconstructed_wav = _reconstruct_wav_header(wav_bytes)
                        _maybe_dump_audio(reconstructed_wav, tag="reconstructed")

                        # Use the reconstructed WAV
                        wav_bytes = reconstructed_wav
                        logger.info("Successfully reconstructed WAV header")
                    except Exception as e:
                        logger.warning(f"Failed to reconstruct WAV header: {e}")
                        return RecognitionResult(
                            provider="shazam",
                            provider_track_id="",
                            title="",
                            artist="",
                            recognized_at_utc=recognized_at,
                            error_message="Invalid WAV format - cannot process audio",
                        )
                else:
                    return RecognitionResult(
                        provider="shazam",
                        provider_track_id="",
                        title="",
                        artist="",
                        recognized_at_utc=recognized_at,
                        error_message="Invalid WAV format - cannot process audio",
                    )

            # Optionally dump the clean WAV we're sending
            _maybe_dump_audio(wav_bytes, tag="to_shazam")

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

    async def close(self) -> None:
        """No-op for fake recognizer."""
        pass
