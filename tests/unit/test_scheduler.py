"""Tests for scheduler module."""

import pytest
from datetime import datetime, timedelta
from typing import AsyncGenerator

from app.config import Config
from app.scheduler import (
    Clock, RealClock, FakeClock, WindowScheduler, AudioWindow, 
    TwoHitAggregator, TwoHitState
)
from app.recognizers.base import RecognitionResult


class TestClock:
    """Test clock implementations."""
    
    def test_real_clock_now(self):
        """Test real clock returns current time."""
        clock = RealClock()
        before = datetime.utcnow()
        now = clock.now()
        after = datetime.utcnow()
        
        assert before <= now <= after
    
    def test_fake_clock_initialization(self):
        """Test fake clock initialization."""
        start_time = datetime(2024, 1, 1, 12, 0, 0)
        clock = FakeClock(start_time)
        
        assert clock.now() == start_time
        assert clock.sleep_calls == []
    
    async def test_fake_clock_sleep(self):
        """Test fake clock sleep behavior."""
        start_time = datetime(2024, 1, 1, 12, 0, 0)
        clock = FakeClock(start_time)
        
        # Sleep should advance time and record the call
        await clock.sleep(5.0)
        
        expected_time = start_time + timedelta(seconds=5.0)
        assert clock.now() == expected_time
        assert clock.sleep_calls == [5.0]
    
    def test_fake_clock_advance(self):
        """Test fake clock manual time advancement."""
        start_time = datetime(2024, 1, 1, 12, 0, 0)
        clock = FakeClock(start_time)
        
        clock.advance(10.0)
        expected_time = start_time + timedelta(seconds=10.0)
        assert clock.now() == expected_time
        assert clock.sleep_calls == []  # Should not record manual advances
    
    def test_fake_clock_set_time(self):
        """Test fake clock time setting."""
        start_time = datetime(2024, 1, 1, 12, 0, 0)
        clock = FakeClock(start_time)
        
        new_time = datetime(2024, 1, 1, 15, 30, 0)
        clock.set_time(new_time)
        assert clock.now() == new_time


class TestAudioWindow:
    """Test AudioWindow dataclass."""
    
    def test_audio_window_properties(self):
        """Test AudioWindow computed properties."""
        start_time = datetime(2024, 1, 1, 12, 0, 0)
        end_time = datetime(2024, 1, 1, 12, 0, 12)  # 12 seconds later
        wav_data = b"fake_wav_data"
        
        window = AudioWindow(
            start_utc=start_time,
            end_utc=end_time,
            wav_bytes=wav_data
        )
        
        assert window.duration_seconds == 12.0
        assert window.center_utc == datetime(2024, 1, 1, 12, 0, 6)
        assert window.wav_bytes == wav_data


class TestWindowScheduler:
    """Test WindowScheduler functionality."""
    
    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return Config(
            window_seconds=12,
            hop_seconds=120,
            stream_count=1
        )
    
    @pytest.fixture
    def fake_clock(self):
        """Create fake clock for testing."""
        return FakeClock(datetime(2024, 1, 1, 12, 0, 0))
    
    @pytest.fixture
    def scheduler(self, config, fake_clock):
        """Create window scheduler for testing."""
        return WindowScheduler(config, fake_clock)
    
    def test_calculate_next_window_start_exact_boundary(self, scheduler):
        """Test window start calculation on exact boundary."""
        # Start at exactly a hop boundary
        current_time = datetime(2024, 1, 1, 12, 0, 0)  # 12:00:00
        next_start = scheduler.calculate_next_window_start(current_time)
        
        # Should start immediately
        assert next_start == current_time
    
    def test_calculate_next_window_start_mid_hop(self, scheduler):
        """Test window start calculation mid-hop."""
        # Start 30 seconds into a hop (past the 12-second window)
        current_time = datetime(2024, 1, 1, 12, 0, 30)
        next_start = scheduler.calculate_next_window_start(current_time)
        
        # Should start at the next hop boundary since we're past the window time
        expected_start = datetime(2024, 1, 1, 12, 2, 0)
        assert next_start == expected_start
    
    def test_calculate_next_window_start_past_window(self, scheduler):
        """Test window start calculation when past current window."""
        # Start 60 seconds into a hop (past the 12-second window)
        current_time = datetime(2024, 1, 1, 12, 1, 0)  # 12:01:00
        next_start = scheduler.calculate_next_window_start(current_time)
        
        # Should start at the next hop boundary
        expected_start = datetime(2024, 1, 1, 12, 2, 0)  # 12:02:00
        assert next_start == expected_start
    
    async def test_schedule_windows_single_window(self, scheduler, fake_clock):
        """Test scheduling a single window."""
        # Create a simple audio stream that yields enough data
        async def audio_stream() -> AsyncGenerator[bytes, None]:
            # Yield chunks that will accumulate to more than 12 seconds
            for _ in range(20):  # More chunks to ensure we get enough data
                yield b"audio_chunk_data"
                # Advance time to simulate real audio processing
                fake_clock.advance(1.0)
        
        windows = []
        async for window in scheduler.schedule_windows(audio_stream()):
            windows.append(window)
            break  # Only get the first window
        
        assert len(windows) == 1
        window = windows[0]
        
        # Check window timing
        expected_start = datetime(2024, 1, 1, 12, 0, 0)
        expected_end = datetime(2024, 1, 1, 12, 0, 12)
        
        assert window.start_utc == expected_start
        assert window.end_utc == expected_end
        assert window.duration_seconds == 12.0
        assert len(window.wav_bytes) > 0
    
    async def test_schedule_windows_multiple_windows(self, scheduler, fake_clock):
        """Test scheduling multiple windows."""
        # Create audio stream that yields data for multiple windows
        async def audio_stream() -> AsyncGenerator[bytes, None]:
            # Yield enough data for 3 windows
            for _ in range(60):  # More chunks to ensure we get enough data
                yield b"audio_chunk_data"
                # Advance time to simulate real audio processing
                fake_clock.advance(1.0)
        
        windows = []
        async for window in scheduler.schedule_windows(audio_stream()):
            windows.append(window)
            if len(windows) >= 3:
                break
        
        assert len(windows) == 3
        
        # Check timing of windows
        expected_starts = [
            datetime(2024, 1, 1, 12, 0, 0),
            datetime(2024, 1, 1, 12, 2, 0),
            datetime(2024, 1, 1, 12, 4, 0)
        ]
        
        for i, window in enumerate(windows):
            assert window.start_utc == expected_starts[i]
            assert window.duration_seconds == 12.0
    
    async def test_schedule_windows_initial_wait(self, scheduler, fake_clock):
        """Test that scheduler waits for next window boundary."""
        # Set clock to 30 seconds into a hop
        fake_clock.set_time(datetime(2024, 1, 1, 12, 0, 30))
        
        async def audio_stream() -> AsyncGenerator[bytes, None]:
            yield b"audio_chunk_data"
        
        # Should wait 90 seconds to get to next hop boundary
        windows = []
        async for window in scheduler.schedule_windows(audio_stream()):
            windows.append(window)
            break
        
        # Check that sleep was called to wait for next boundary
        assert len(fake_clock.sleep_calls) > 0
        # First sleep should be around 90 seconds (120 - 30)
        assert fake_clock.sleep_calls[0] > 85 and fake_clock.sleep_calls[0] < 95


class TestTwoHitState:
    """Test TwoHitState functionality."""
    
    def test_is_within_tolerance_within_bounds(self):
        """Test tolerance check within bounds."""
        first_hit_time = datetime(2024, 1, 1, 12, 0, 0)
        second_hit_time = datetime(2024, 1, 1, 12, 1, 30)  # 90 seconds later
        
        state = TwoHitState(
            track_id="test_track",
            provider="shazam",
            first_hit_time=first_hit_time,
            confidence=0.8
        )
        
        # With tolerance_hops=1 and hop_seconds=120, max tolerance is 120 seconds
        assert state.is_within_tolerance(second_hit_time, 1, 120) is True
    
    def test_is_within_tolerance_outside_bounds(self):
        """Test tolerance check outside bounds."""
        first_hit_time = datetime(2024, 1, 1, 12, 0, 0)
        second_hit_time = datetime(2024, 1, 1, 12, 3, 0)  # 180 seconds later
        
        state = TwoHitState(
            track_id="test_track",
            provider="shazam",
            first_hit_time=first_hit_time,
            confidence=0.8
        )
        
        # With tolerance_hops=1 and hop_seconds=120, max tolerance is 120 seconds
        assert state.is_within_tolerance(second_hit_time, 1, 120) is False
    
    def test_is_within_tolerance_exact_boundary(self):
        """Test tolerance check at exact boundary."""
        first_hit_time = datetime(2024, 1, 1, 12, 0, 0)
        second_hit_time = datetime(2024, 1, 1, 12, 2, 0)  # Exactly 120 seconds later
        
        state = TwoHitState(
            track_id="test_track",
            provider="shazam",
            first_hit_time=first_hit_time,
            confidence=0.8
        )
        
        # Should be exactly at the boundary
        assert state.is_within_tolerance(second_hit_time, 1, 120) is True


class TestTwoHitAggregator:
    """Test TwoHitAggregator functionality."""
    
    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return Config(
            two_hit_hop_tolerance=1,
            hop_seconds=120,
            stream_count=1
        )
    
    @pytest.fixture
    def aggregator(self, config):
        """Create two-hit aggregator for testing."""
        return TwoHitAggregator(config)
    
    @pytest.fixture
    def sample_result(self):
        """Create a sample recognition result."""
        return RecognitionResult(
            provider="shazam",
            provider_track_id="track_123",
            title="Test Song",
            artist="Test Artist",
            confidence=0.8,
            recognized_at_utc=datetime(2024, 1, 1, 12, 0, 0)
        )
    
    def test_process_recognition_first_hit(self, aggregator, sample_result):
        """Test processing first hit of a track."""
        result = aggregator.process_recognition("test_stream", sample_result)
        
        # Should not confirm on first hit
        assert result is None
        
        # Should have one pending hit
        assert aggregator.get_pending_hits_count("test_stream") == 1
    
    def test_process_recognition_two_hit_confirmation(self, aggregator, sample_result):
        """Test two-hit confirmation."""
        # First hit
        result1 = aggregator.process_recognition("test_stream", sample_result)
        assert result1 is None
        
        # Second hit within tolerance
        second_result = RecognitionResult(
            provider="shazam",
            provider_track_id="track_123",
            title="Test Song",
            artist="Test Artist",
            confidence=0.9,
            recognized_at_utc=datetime(2024, 1, 1, 12, 1, 0)  # 60 seconds later
        )
        
        result2 = aggregator.process_recognition("test_stream", second_result)
        
        # Should confirm on second hit
        assert result2 is not None
        assert result2.provider_track_id == "track_123"
        
        # Should have no pending hits
        assert aggregator.get_pending_hits_count("test_stream") == 0
    
    def test_process_recognition_outside_tolerance(self, aggregator, sample_result):
        """Test recognition outside tolerance window."""
        # First hit
        result1 = aggregator.process_recognition("test_stream", sample_result)
        assert result1 is None
        
        # Second hit outside tolerance
        second_result = RecognitionResult(
            provider="shazam",
            provider_track_id="track_123",
            title="Test Song",
            artist="Test Artist",
            confidence=0.9,
            recognized_at_utc=datetime(2024, 1, 1, 12, 3, 0)  # 180 seconds later
        )
        
        result2 = aggregator.process_recognition("test_stream", second_result)
        
        # Should not confirm
        assert result2 is None
        
        # Should replace the old hit with new one
        assert aggregator.get_pending_hits_count("test_stream") == 1
    
    def test_process_recognition_failed_recognition(self, aggregator):
        """Test processing failed recognition."""
        failed_result = RecognitionResult(
            provider="shazam",
            provider_track_id="",
            title="",
            artist="",
            error_message="Recognition failed",
            recognized_at_utc=datetime(2024, 1, 1, 12, 0, 0)
        )
        
        result = aggregator.process_recognition("test_stream", failed_result)
        
        # Should not process failed recognitions
        assert result is None
        assert aggregator.get_pending_hits_count("test_stream") == 0
    
    def test_process_recognition_different_providers(self, aggregator, sample_result):
        """Test that different providers are tracked separately."""
        # Shazam hit
        shazam_result = sample_result
        result1 = aggregator.process_recognition("test_stream", shazam_result)
        assert result1 is None
        
        # AcoustID hit for same track
        acoustid_result = RecognitionResult(
            provider="acoustid",
            provider_track_id="track_123",
            title="Test Song",
            artist="Test Artist",
            confidence=0.7,
            recognized_at_utc=datetime(2024, 1, 1, 12, 1, 0)
        )
        
        result2 = aggregator.process_recognition("test_stream", acoustid_result)
        
        # Should not confirm (different providers)
        assert result2 is None
        
        # Should have two pending hits
        assert aggregator.get_pending_hits_count("test_stream") == 2
    
    def test_cleanup_expired_hits(self, aggregator, sample_result):
        """Test cleanup of expired hits."""
        # Add a hit
        aggregator.process_recognition("test_stream", sample_result)
        assert aggregator.get_pending_hits_count("test_stream") == 1
        
        # Cleanup with time well past expiration
        cleanup_time = datetime(2024, 1, 1, 12, 5, 0)  # 5 minutes later
        aggregator.cleanup_expired_hits(cleanup_time)
        
        # Should have no pending hits
        assert aggregator.get_pending_hits_count("test_stream") == 0
    
    def test_get_pending_hits_count_all_streams(self, aggregator, sample_result):
        """Test getting pending hits count across all streams."""
        # Add hits to multiple streams
        aggregator.process_recognition("stream1", sample_result)
        aggregator.process_recognition("stream2", sample_result)
        
        # Should have 2 total pending hits
        assert aggregator.get_pending_hits_count() == 2
        
        # Should have 1 pending hit for specific stream
        assert aggregator.get_pending_hits_count("stream1") == 1
        assert aggregator.get_pending_hits_count("stream2") == 1
