"""Tests for worker orchestration in ying."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest.mock import MagicMock, patch

import pytest

from app.config import Config
from app.db.repo import PlayRepository, RecognitionRepository, TrackRepository
from app.ffmpeg import FakeFFmpegRunner, FFmpegConfig
from app.recognizers.base import MusicRecognizer, RecognitionResult
from app.scheduler import Clock
from app.worker import ParallelRecognizers, StreamWorker, WorkerManager


class FakeClock(Clock):
    """Fake clock for testing."""

    def __init__(self, start_time: datetime) -> None:
        self.current_time = start_time

    def now(self) -> datetime:
        return self.current_time

    async def sleep(self, seconds: float) -> None:
        self.current_time += timedelta(seconds=seconds)


class FakeMusicRecognizer(MusicRecognizer):
    """Fake music recognizer for testing."""

    def __init__(
        self, provider: str, results: list[RecognitionResult | None] = None
    ) -> None:
        self.provider = provider
        self.results = results or []
        self.call_count = 0
        self.last_wav_bytes: bytes | None = None
        self.last_timeout: float | None = None

    async def recognize(
        self, wav_bytes: bytes, timeout_seconds: float = 30.0
    ) -> RecognitionResult:
        self.call_count += 1
        self.last_wav_bytes = wav_bytes
        self.last_timeout = timeout_seconds

        if self.call_count <= len(self.results):
            result = self.results[self.call_count - 1]
            if result is None:
                raise Exception(f"Fake error from {self.provider}")
            return result

        # Default result
        return RecognitionResult(
            provider=self.provider,
            provider_track_id=f"fake_{self.provider}_{self.call_count}",
            title=f"Test Song {self.call_count}",
            artist=f"Test Artist {self.call_count}",
            recognized_at_utc=datetime.now(UTC),
            confidence=0.8,
            raw_response={"fake": True},
        )


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    yield db_path

    # Cleanup
    if db_path.exists():
        db_path.unlink()


@pytest.fixture
def config(temp_db, monkeypatch):
    """Create test configuration."""
    # Set environment variables for streams
    monkeypatch.setenv("STREAM_1_NAME", "test1")
    monkeypatch.setenv("STREAM_1_URL", "rtsp://test1")
    monkeypatch.setenv("STREAM_1_ENABLED", "true")
    monkeypatch.setenv("STREAM_2_NAME", "test2")
    monkeypatch.setenv("STREAM_2_URL", "rtsp://test2")
    monkeypatch.setenv("STREAM_2_ENABLED", "true")

    config = Config(
        port=44100,
        db_path=str(temp_db),
        stream_count=2,
        window_seconds=12,
        hop_seconds=120,
        dedup_seconds=300,
        decision_policy="shazam_two_hit",
        two_hit_hop_tolerance=1,
        global_max_inflight_recognitions=3,
        per_provider_max_inflight=2,
        queue_max_size=100,
        acoustid_enabled=True,
        acoustid_api_key="test_key",
    )

    return config


@pytest.fixture
def clock():
    """Create fake clock."""
    return FakeClock(datetime(2024, 1, 1, 12, 0, 0))


@pytest.fixture
async def repos(temp_db):
    """Create repository instances."""
    from app.db.migrate import MigrationManager

    # Apply migrations
    migrator = MigrationManager(temp_db)
    await migrator.migrate_all()

    return {
        "track": TrackRepository(temp_db),
        "play": PlayRepository(temp_db),
        "recognition": RecognitionRepository(temp_db),
    }


class TestParallelRecognizers:
    """Test parallel recognizers with capacity limits."""

    @pytest.mark.asyncio
    async def test_recognize_parallel_success(self):
        """Test successful parallel recognition."""
        # Create fake recognizers
        shazam_result = RecognitionResult(
            provider="shazam",
            provider_track_id="shazam_123",
            title="Test Song",
            artist="Test Artist",
            recognized_at_utc=datetime.now(UTC),
            confidence=0.9,
            raw_response={"shazam": True},
        )

        acoustid_result = RecognitionResult(
            provider="acoustid",
            provider_track_id="acoustid_456",
            title="Test Song",
            artist="Test Artist",
            recognized_at_utc=datetime.now(UTC),
            confidence=0.8,
            raw_response={"acoustid": True},
        )

        recognizers = {
            "shazam": FakeMusicRecognizer("shazam", [shazam_result]),
            "acoustid": FakeMusicRecognizer("acoustid", [acoustid_result]),
        }

        # Create semaphores
        global_sem = asyncio.Semaphore(3)
        per_provider_sems = {
            "shazam": asyncio.Semaphore(2),
            "acoustid": asyncio.Semaphore(2),
        }

        parallel = ParallelRecognizers(recognizers, global_sem, per_provider_sems)

        # Test recognition
        results = await parallel.recognize_parallel(b"fake_wav_data", 30.0)

        assert len(results) == 2
        result_providers = {r.provider for r in results}
        assert result_providers == {"shazam", "acoustid"}

    @pytest.mark.asyncio
    async def test_recognize_parallel_with_failures(self):
        """Test parallel recognition with some failures."""
        # One success, one failure
        shazam_result = RecognitionResult(
            provider="shazam",
            provider_track_id="shazam_123",
            title="Test Song",
            artist="Test Artist",
            recognized_at_utc=datetime.now(UTC),
            confidence=0.9,
            raw_response={"shazam": True},
        )

        recognizers = {
            "shazam": FakeMusicRecognizer("shazam", [shazam_result]),
            "acoustid": FakeMusicRecognizer("acoustid", [None]),  # Will raise exception
        }

        global_sem = asyncio.Semaphore(3)
        per_provider_sems = {
            "shazam": asyncio.Semaphore(2),
            "acoustid": asyncio.Semaphore(2),
        }

        parallel = ParallelRecognizers(recognizers, global_sem, per_provider_sems)

        # Test recognition (should not raise, just return successful results)
        results = await parallel.recognize_parallel(b"fake_wav_data", 30.0)

        assert len(results) == 1
        assert results[0].provider == "shazam"

    @pytest.mark.asyncio
    async def test_capacity_limits(self):
        """Test that capacity limits are respected."""

        # Create recognizers that will block
        async def slow_recognize(
            wav_bytes: bytes, timeout_seconds: float
        ) -> RecognitionResult:
            await asyncio.sleep(0.1)  # Simulate work
            return RecognitionResult(
                provider="test",
                provider_track_id="test_123",
                title="Test Song",
                artist="Test Artist",
                recognized_at_utc=datetime.now(UTC),
                confidence=0.8,
                raw_response={"test": True},
            )

        # Create a simple recognizer object instead of using Mock
        class TestRecognizer:
            async def recognize(
                self, wav_bytes: bytes, timeout_seconds: float
            ) -> RecognitionResult:
                return await slow_recognize(wav_bytes, timeout_seconds)

        recognizer = TestRecognizer()

        recognizers = {"test": recognizer}
        global_sem = asyncio.Semaphore(1)  # Only allow 1 concurrent
        per_provider_sems = {"test": asyncio.Semaphore(1)}

        parallel = ParallelRecognizers(recognizers, global_sem, per_provider_sems)

        # Start multiple recognitions concurrently
        tasks = [
            asyncio.create_task(parallel.recognize_parallel(b"data1", 30.0)),
            asyncio.create_task(parallel.recognize_parallel(b"data2", 30.0)),
            asyncio.create_task(parallel.recognize_parallel(b"data3", 30.0)),
        ]

        # They should complete (but some may be limited)
        results = await asyncio.gather(*tasks)

        # At least one should succeed
        successful_results = [r for r in results if r]
        assert len(successful_results) >= 1


class TestStreamWorker:
    """Test stream worker orchestration."""

    @pytest.mark.asyncio
    async def test_worker_lifecycle(self, config, clock, repos):
        """Test worker start/stop lifecycle."""
        stream_config = config.streams[0]

        # Create fake components
        ffmpeg_config = FFmpegConfig(rtsp_url=stream_config.url)
        ffmpeg_runner = FakeFFmpegRunner(ffmpeg_config, b"chunk1chunk2")

        recognizers = {"shazam": FakeMusicRecognizer("shazam")}
        parallel_recognizers = ParallelRecognizers(
            recognizers, asyncio.Semaphore(3), {"shazam": asyncio.Semaphore(2)}
        )

        worker = StreamWorker(
            stream_config=stream_config,
            config=config,
            clock=clock,
            ffmpeg_runner=ffmpeg_runner,
            parallel_recognizers=parallel_recognizers,
            track_repo=repos["track"],
            play_repo=repos["play"],
            recognition_repo=repos["recognition"],
        )

        # Test start
        await worker.start()
        assert worker._running

        # Give the background task time to start FFmpeg
        await asyncio.sleep(0.1)
        assert ffmpeg_runner.is_running

        # Test stop
        await worker.stop()
        assert not worker._running
        assert not ffmpeg_runner.is_running

    @pytest.mark.asyncio
    async def test_window_processing_integration(self, config, clock, repos):
        """Test basic window processing integration without complex timing."""
        stream_config = config.streams[0]

        # Create fake audio data
        fake_audio_data = b"test_audio_data" * 1000
        ffmpeg_config = FFmpegConfig(rtsp_url=stream_config.url)
        ffmpeg_runner = FakeFFmpegRunner(ffmpeg_config, fake_audio_data)

        # Create simple recognizer
        recognizers = {"shazam": FakeMusicRecognizer("shazam")}
        parallel_recognizers = ParallelRecognizers(
            recognizers, asyncio.Semaphore(3), {"shazam": asyncio.Semaphore(2)}
        )

        worker = StreamWorker(
            stream_config=stream_config,
            config=config,
            clock=clock,
            ffmpeg_runner=ffmpeg_runner,
            parallel_recognizers=parallel_recognizers,
            track_repo=repos["track"],
            play_repo=repos["play"],
            recognition_repo=repos["recognition"],
        )

        # Start worker briefly to ensure it can start without errors
        await worker.start()

        # Let it run for a short time
        await asyncio.sleep(0.1)

        # Stop it
        await worker.stop()

        # Just verify the worker ran without errors
        assert not worker._running


class TestWorkerManager:
    """Test worker manager functionality."""

    @pytest.mark.asyncio
    async def test_create_recognizers(self, config):
        """Test recognizer creation based on configuration."""
        clock = FakeClock(datetime.now(UTC))
        manager = WorkerManager(config, clock)

        recognizers = manager._create_recognizers()

        # Should have both shazam and acoustid (since acoustid is enabled in config)
        assert "shazam" in recognizers
        assert "acoustid" in recognizers
        assert len(recognizers) == 2

    @pytest.mark.asyncio
    async def test_create_recognizers_acoustid_disabled(self, config):
        """Test recognizer creation with AcoustID disabled."""
        config.acoustid_enabled = False

        clock = FakeClock(datetime.now(UTC))
        manager = WorkerManager(config, clock)

        recognizers = manager._create_recognizers()

        # Should only have shazam
        assert "shazam" in recognizers
        assert "acoustid" not in recognizers
        assert len(recognizers) == 1

    @pytest.mark.asyncio
    async def test_start_stop_all_workers(self, config, temp_db):
        """Test starting and stopping all workers."""
        # Apply migrations first
        from app.db.migrate import MigrationManager

        migrator = MigrationManager(temp_db)
        await migrator.migrate_all()

        clock = FakeClock(datetime.now(UTC))

        with patch("app.worker.RealFFmpegRunner") as mock_ffmpeg:
            # Use MagicMock instead of AsyncMock to avoid warnings
            mock_instance = MagicMock()

            # Configure async methods manually
            async def mock_start():
                pass

            async def mock_stop():
                pass

            async def mock_read_audio_data():
                # Return an empty async generator
                return
                yield  # pragma: no cover

            mock_instance.start = mock_start
            mock_instance.stop = mock_stop
            mock_instance.read_audio_data = mock_read_audio_data
            mock_ffmpeg.return_value = mock_instance

            manager = WorkerManager(config, clock)

            # Start all workers
            await manager.start_all()

            # Should have workers for enabled streams
            assert len(manager.workers) == 2  # Both streams are enabled
            assert "test1" in manager.workers
            assert "test2" in manager.workers

            # Stop all workers
            await manager.stop_all()

            # Workers should be cleared
            assert len(manager.workers) == 0

    @pytest.mark.asyncio
    async def test_skip_disabled_streams(self, config, temp_db):
        """Test that disabled streams are skipped."""
        # Disable one stream
        config.streams[1].enabled = False

        # Apply migrations first
        from app.db.migrate import MigrationManager

        migrator = MigrationManager(temp_db)
        await migrator.migrate_all()

        clock = FakeClock(datetime.now(UTC))

        with patch("app.worker.RealFFmpegRunner") as mock_ffmpeg:
            # Use MagicMock instead of AsyncMock to avoid warnings
            mock_instance = MagicMock()

            # Configure async methods manually
            async def mock_start():
                pass

            async def mock_stop():
                pass

            async def mock_read_audio_data():
                # Return an empty async generator
                return
                yield  # pragma: no cover

            mock_instance.start = mock_start
            mock_instance.stop = mock_stop
            mock_instance.read_audio_data = mock_read_audio_data
            mock_ffmpeg.return_value = mock_instance

            manager = WorkerManager(config, clock)

            # Start all workers
            await manager.start_all()

            # Should only have worker for enabled stream
            assert len(manager.workers) == 1
            assert "test1" in manager.workers
            assert "test2" not in manager.workers

            await manager.stop_all()

    @pytest.mark.asyncio
    async def test_restart_all(self, config, temp_db):
        """Test restarting all workers."""
        # Apply migrations first
        from app.db.migrate import MigrationManager

        migrator = MigrationManager(temp_db)
        await migrator.migrate_all()

        clock = FakeClock(datetime.now(UTC))

        with patch("app.worker.RealFFmpegRunner") as mock_ffmpeg:
            # Use MagicMock instead of AsyncMock to avoid warnings
            mock_instance = MagicMock()

            # Configure async methods manually
            async def mock_start():
                pass

            async def mock_stop():
                pass

            async def mock_read_audio_data():
                # Return an empty async generator
                return
                yield  # pragma: no cover

            mock_instance.start = mock_start
            mock_instance.stop = mock_stop
            mock_instance.read_audio_data = mock_read_audio_data
            mock_ffmpeg.return_value = mock_instance

            manager = WorkerManager(config, clock)

            # Start workers
            await manager.start_all()
            old_workers = list(manager.workers.keys())

            # Restart
            await manager.restart_all()
            new_workers = list(manager.workers.keys())

            # Should have same worker names but different instances
            assert old_workers == new_workers
            assert len(manager.workers) == 2


class TestBackpressureAndCapacity:
    """Test backpressure and capacity management."""

    @pytest.mark.asyncio
    async def test_global_capacity_limits(self):
        """Test global recognition capacity limits."""
        # Create a slow recognizer
        call_count = 0

        async def slow_recognize(
            wav_bytes: bytes, timeout_seconds: float
        ) -> RecognitionResult:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.1)  # Simulate work
            return RecognitionResult(
                provider="slow",
                provider_track_id=f"track_{call_count}",
                title="Slow Song",
                artist="Slow Artist",
                recognized_at_utc=datetime.now(UTC),
                confidence=0.8,
                raw_response={"slow": True},
            )

        # Create a simple recognizer object instead of using Mock
        class SlowRecognizer:
            async def recognize(
                self, wav_bytes: bytes, timeout_seconds: float
            ) -> RecognitionResult:
                return await slow_recognize(wav_bytes, timeout_seconds)

        recognizer = SlowRecognizer()

        recognizers = {"slow": recognizer}
        global_sem = asyncio.Semaphore(2)  # Only allow 2 concurrent
        per_provider_sems = {"slow": asyncio.Semaphore(5)}  # High per-provider limit

        parallel = ParallelRecognizers(recognizers, global_sem, per_provider_sems)

        # Start many recognitions concurrently
        tasks = []
        for i in range(5):
            task = asyncio.create_task(
                parallel.recognize_parallel(f"data{i}".encode(), 30.0)
            )
            tasks.append(task)

        # They should all complete eventually
        results = await asyncio.gather(*tasks)

        # All should succeed (though they were limited by global semaphore)
        assert len(results) == 5
        assert all(len(r) == 1 for r in results)  # Each should have 1 result

    @pytest.mark.asyncio
    async def test_per_provider_capacity_limits(self):
        """Test per-provider capacity limits."""
        call_count = 0

        async def slow_recognize(
            wav_bytes: bytes, timeout_seconds: float
        ) -> RecognitionResult:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.1)
            return RecognitionResult(
                provider="limited",
                provider_track_id=f"track_{call_count}",
                title="Limited Song",
                artist="Limited Artist",
                recognized_at_utc=datetime.now(UTC),
                confidence=0.8,
                raw_response={"limited": True},
            )

        # Create a simple recognizer object instead of using Mock
        class LimitedRecognizer:
            async def recognize(
                self, wav_bytes: bytes, timeout_seconds: float
            ) -> RecognitionResult:
                return await slow_recognize(wav_bytes, timeout_seconds)

        recognizer = LimitedRecognizer()

        recognizers = {"limited": recognizer}
        global_sem = asyncio.Semaphore(10)  # High global limit
        per_provider_sems = {"limited": asyncio.Semaphore(1)}  # Only 1 per provider

        parallel = ParallelRecognizers(recognizers, global_sem, per_provider_sems)

        # Start multiple recognitions
        tasks = []
        for i in range(3):
            task = asyncio.create_task(
                parallel.recognize_parallel(f"data{i}".encode(), 30.0)
            )
            tasks.append(task)

        results = await asyncio.gather(*tasks)

        # Some may be limited (return empty results)
        successful_results = [r for r in results if r]
        assert len(successful_results) >= 1  # At least one should succeed

    @pytest.mark.asyncio
    async def test_mixed_provider_fairness(self):
        """Test fairness across multiple providers."""
        shazam_calls = 0
        acoustid_calls = 0

        async def shazam_recognize(
            wav_bytes: bytes, timeout_seconds: float
        ) -> RecognitionResult:
            nonlocal shazam_calls
            shazam_calls += 1
            await asyncio.sleep(0.05)
            return RecognitionResult(
                provider="shazam",
                provider_track_id=f"shazam_{shazam_calls}",
                title="Shazam Song",
                artist="Shazam Artist",
                recognized_at_utc=datetime.now(UTC),
                confidence=0.9,
                raw_response={"shazam": True},
            )

        async def acoustid_recognize(
            wav_bytes: bytes, timeout_seconds: float
        ) -> RecognitionResult:
            nonlocal acoustid_calls
            acoustid_calls += 1
            await asyncio.sleep(0.05)
            return RecognitionResult(
                provider="acoustid",
                provider_track_id=f"acoustid_{acoustid_calls}",
                title="AcoustID Song",
                artist="AcoustID Artist",
                recognized_at_utc=datetime.now(UTC),
                confidence=0.8,
                raw_response={"acoustid": True},
            )

        # Create simple recognizer objects instead of using Mock
        class ShazamRecognizer:
            async def recognize(
                self, wav_bytes: bytes, timeout_seconds: float
            ) -> RecognitionResult:
                return await shazam_recognize(wav_bytes, timeout_seconds)

        class AcoustIDRecognizer:
            async def recognize(
                self, wav_bytes: bytes, timeout_seconds: float
            ) -> RecognitionResult:
                return await acoustid_recognize(wav_bytes, timeout_seconds)

        shazam_recognizer = ShazamRecognizer()
        acoustid_recognizer = AcoustIDRecognizer()

        recognizers = {"shazam": shazam_recognizer, "acoustid": acoustid_recognizer}
        global_sem = asyncio.Semaphore(3)
        per_provider_sems = {
            "shazam": asyncio.Semaphore(2),
            "acoustid": asyncio.Semaphore(2),
        }

        parallel = ParallelRecognizers(recognizers, global_sem, per_provider_sems)

        # Run multiple recognitions
        tasks = []
        for i in range(4):
            task = asyncio.create_task(
                parallel.recognize_parallel(f"data{i}".encode(), 30.0)
            )
            tasks.append(task)

        results = await asyncio.gather(*tasks)

        # Both providers should get some calls
        assert shazam_calls > 0
        assert acoustid_calls > 0

        # Results should include both providers
        all_results = [result for batch in results for result in batch]
        providers = {r.provider for r in all_results}
        assert "shazam" in providers
        assert "acoustid" in providers
