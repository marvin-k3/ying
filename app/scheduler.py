"""Scheduling and windowing logic for ying."""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import AsyncGenerator, Dict, List, Optional, Set

from .config import Config
from .recognizers.base import RecognitionResult


class Clock(ABC):
    """Abstract clock interface for time operations."""
    
    @abstractmethod
    def now(self) -> datetime:
        """Get current UTC time."""
        pass
    
    @abstractmethod
    async def sleep(self, seconds: float) -> None:
        """Sleep for the specified number of seconds."""
        pass


class RealClock(Clock):
    """Real clock implementation using system time."""
    
    def now(self) -> datetime:
        """Get current UTC time."""
        return datetime.utcnow()
    
    async def sleep(self, seconds: float) -> None:
        """Sleep for the specified number of seconds."""
        await asyncio.sleep(seconds)


class FakeClock(Clock):
    """Fake clock for testing."""
    
    def __init__(self, start_time: Optional[datetime] = None):
        """Initialize fake clock.
        
        Args:
            start_time: Initial time. Defaults to current UTC time.
        """
        self._current_time = start_time or datetime.utcnow()
        self._sleep_calls: List[float] = []
    
    def now(self) -> datetime:
        """Get current fake time."""
        return self._current_time
    
    async def sleep(self, seconds: float) -> None:
        """Record sleep call and advance time."""
        self._sleep_calls.append(seconds)
        self._current_time += timedelta(seconds=seconds)
    
    def advance(self, seconds: float) -> None:
        """Manually advance time without sleeping."""
        self._current_time += timedelta(seconds=seconds)
    
    def set_time(self, time: datetime) -> None:
        """Set the current time."""
        self._current_time = time
    
    @property
    def sleep_calls(self) -> List[float]:
        """Get list of sleep durations called."""
        return self._sleep_calls.copy()


@dataclass
class AudioWindow:
    """Represents an audio window for recognition."""
    
    start_utc: datetime
    end_utc: datetime
    wav_bytes: bytes
    
    @property
    def duration_seconds(self) -> float:
        """Get window duration in seconds."""
        return (self.end_utc - self.start_utc).total_seconds()
    
    @property
    def center_utc(self) -> datetime:
        """Get the center time of the window."""
        return self.start_utc + timedelta(seconds=self.duration_seconds / 2)


class WindowScheduler:
    """Schedules audio windows for recognition."""
    
    def __init__(self, config: Config, clock: Clock):
        """Initialize window scheduler.
        
        Args:
            config: Application configuration.
            clock: Clock implementation for time operations.
        """
        self.config = config
        self.clock = clock
        self.window_seconds = config.window_seconds
        self.hop_seconds = config.hop_seconds
    
    def calculate_next_window_start(self, current_time: datetime) -> datetime:
        """Calculate the start time of the next window.
        
        Args:
            current_time: Current time.
            
        Returns:
            Start time of the next window.
        """
        # Round down to the nearest hop boundary
        seconds_since_epoch = int(current_time.timestamp())
        hop_boundary = (seconds_since_epoch // self.hop_seconds) * self.hop_seconds
        
        # If we're past the window time in the current hop, move to the next hop
        if seconds_since_epoch >= hop_boundary + self.window_seconds:
            hop_boundary += self.hop_seconds
        
        return datetime.fromtimestamp(hop_boundary)
    
    async def schedule_windows(
        self, 
        audio_stream: AsyncGenerator[bytes, None]
    ) -> AsyncGenerator[AudioWindow, None]:
        """Schedule audio windows from a continuous audio stream.
        
        Args:
            audio_stream: Async generator yielding audio chunks.
            
        Yields:
            AudioWindow objects at scheduled intervals.
        """
        current_time = self.clock.now()
        next_window_start = self.calculate_next_window_start(current_time)
        
        # Calculate how long to wait until the next window
        wait_seconds = (next_window_start - current_time).total_seconds()
        if wait_seconds > 0:
            await self.clock.sleep(wait_seconds)
        
        audio_buffer = bytearray()
        window_start = next_window_start
        
        async for chunk in audio_stream:
            audio_buffer.extend(chunk)
            current_time = self.clock.now()
            
            # Check if we have enough audio for a window
            if current_time >= window_start + timedelta(seconds=self.window_seconds):
                # Create window from buffered audio
                window_end = window_start + timedelta(seconds=self.window_seconds)
                window = AudioWindow(
                    start_utc=window_start,
                    end_utc=window_end,
                    wav_bytes=bytes(audio_buffer)
                )
                
                yield window
                
                # Calculate next window start
                window_start = self.calculate_next_window_start(current_time)
                
                # Clear buffer and wait for next window
                audio_buffer.clear()
                wait_seconds = (window_start - current_time).total_seconds()
                if wait_seconds > 0:
                    await self.clock.sleep(wait_seconds)


@dataclass
class TwoHitState:
    """State for tracking two-hit confirmation."""
    
    track_id: str
    provider: str
    first_hit_time: datetime
    confidence: float
    
    def is_within_tolerance(self, second_hit_time: datetime, tolerance_hops: int, hop_seconds: int) -> bool:
        """Check if second hit is within tolerance window.
        
        Args:
            second_hit_time: Time of the second hit.
            tolerance_hops: Number of hops to tolerate between hits.
            hop_seconds: Hop interval in seconds.
            
        Returns:
            True if within tolerance.
        """
        time_diff = (second_hit_time - self.first_hit_time).total_seconds()
        max_tolerance_seconds = tolerance_hops * hop_seconds
        return time_diff <= max_tolerance_seconds


class TwoHitAggregator:
    """Implements two-hit confirmation policy."""
    
    def __init__(self, config: Config):
        """Initialize two-hit aggregator.
        
        Args:
            config: Application configuration.
        """
        self.config = config
        self.tolerance_hops = config.two_hit_hop_tolerance
        self.hop_seconds = config.hop_seconds
        
        # Track pending hits per stream
        self.pending_hits: Dict[str, Dict[str, TwoHitState]] = {}
    
    def process_recognition(
        self, 
        stream_name: str, 
        result: RecognitionResult
    ) -> Optional[RecognitionResult]:
        """Process a recognition result and check for two-hit confirmation.
        
        Args:
            stream_name: Name of the stream.
            result: Recognition result to process.
            
        Returns:
            Confirmed result if two-hit criteria met, None otherwise.
        """
        if not result.is_success:
            return None
        
        # Create unique track identifier
        track_key = f"{result.provider}:{result.provider_track_id}"
        
        # Initialize stream tracking if needed
        if stream_name not in self.pending_hits:
            self.pending_hits[stream_name] = {}
        
        stream_hits = self.pending_hits[stream_name]
        
        if track_key in stream_hits:
            # Second hit - check if within tolerance
            first_hit = stream_hits[track_key]
            if first_hit.is_within_tolerance(result.recognized_at_utc, self.tolerance_hops, self.hop_seconds):
                # Two-hit confirmed! Remove from pending and return
                del stream_hits[track_key]
                return result
            else:
                # Outside tolerance - replace with new hit
                stream_hits[track_key] = TwoHitState(
                    track_id=result.provider_track_id,
                    provider=result.provider,
                    first_hit_time=result.recognized_at_utc,
                    confidence=result.confidence or 0.0
                )
        else:
            # First hit - add to pending
            stream_hits[track_key] = TwoHitState(
                track_id=result.provider_track_id,
                provider=result.provider,
                first_hit_time=result.recognized_at_utc,
                confidence=result.confidence or 0.0
            )
        
        return None
    
    def cleanup_expired_hits(self, current_time: datetime) -> None:
        """Remove expired pending hits.
        
        Args:
            current_time: Current time for expiration check.
        """
        max_age_seconds = (self.tolerance_hops + 1) * self.hop_seconds
        
        for stream_name, stream_hits in self.pending_hits.items():
            expired_keys = [
                key for key, hit in stream_hits.items()
                if (current_time - hit.first_hit_time).total_seconds() > max_age_seconds
            ]
            
            for key in expired_keys:
                del stream_hits[key]
    
    def get_pending_hits_count(self, stream_name: Optional[str] = None) -> int:
        """Get count of pending hits.
        
        Args:
            stream_name: Optional stream name filter.
            
        Returns:
            Number of pending hits.
        """
        if stream_name:
            return len(self.pending_hits.get(stream_name, {}))
        
        return sum(len(hits) for hits in self.pending_hits.values())
