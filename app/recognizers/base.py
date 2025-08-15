"""Base recognition interface and models for ying."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class RecognitionResult:
    """Result from a music recognition attempt."""
    
    # Core identification
    provider: str
    provider_track_id: str
    title: str
    artist: str
    
    # Timing
    recognized_at_utc: datetime
    
    # Optional metadata
    album: Optional[str] = None
    isrc: Optional[str] = None
    artwork_url: Optional[str] = None
    
    # Recognition quality
    confidence: Optional[float] = None  # 0.0 to 1.0
    
    # Raw provider response for diagnostics
    raw_response: Optional[Dict[str, Any]] = None
    
    # Error information (if recognition failed)
    error_message: Optional[str] = None
    
    @property
    def is_success(self) -> bool:
        """Check if recognition was successful."""
        return self.error_message is None and self.provider_track_id is not None
    
    @property
    def is_no_match(self) -> bool:
        """Check if this represents a "no match" result."""
        return self.error_message is None and not self.provider_track_id


class MusicRecognizer(ABC):
    """Abstract interface for music recognition providers."""
    
    @abstractmethod
    async def recognize(
        self, 
        wav_bytes: bytes, 
        timeout_seconds: float = 30.0
    ) -> RecognitionResult:
        """Recognize music from WAV audio data.
        
        Args:
            wav_bytes: WAV audio data as bytes.
            timeout_seconds: Maximum time to wait for recognition.
            
        Returns:
            RecognitionResult with track information or error details.
        """
        pass


class FakeMusicRecognizer(MusicRecognizer):
    """Fake recognizer for testing."""
    
    def __init__(
        self,
        provider: str,
        results: Optional[list[RecognitionResult]] = None,
        should_fail: bool = False,
        failure_message: str = "Simulated failure"
    ):
        """Initialize fake recognizer.
        
        Args:
            provider: Provider name (e.g., 'shazam', 'acoustid').
            results: Pre-configured results to return in sequence.
            should_fail: Whether to simulate failures.
            failure_message: Error message for failures.
        """
        self.provider = provider
        self.results = results or []
        self.should_fail = should_fail
        self.failure_message = failure_message
        self.call_count = 0
    
    async def recognize(
        self, 
        wav_bytes: bytes, 
        timeout_seconds: float = 30.0
    ) -> RecognitionResult:
        """Return pre-configured results or simulate failure."""
        self.call_count += 1
        
        if self.should_fail:
            return RecognitionResult(
                provider=self.provider,
                provider_track_id="",
                title="",
                artist="",
                recognized_at_utc=datetime.utcnow(),
                error_message=self.failure_message
            )
        
        if self.results:
            # Return results in sequence, cycling back to first
            result = self.results[(self.call_count - 1) % len(self.results)]
            # Update timestamp to current time
            return RecognitionResult(
                **{**result.__dict__, 'recognized_at_utc': datetime.utcnow()}
            )
        
        # Default no-match result
        return RecognitionResult(
            provider=self.provider,
            provider_track_id="",
            title="",
            artist="",
            recognized_at_utc=datetime.utcnow()
        )
