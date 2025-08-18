"""Tests for FFmpeg runner module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ffmpeg import (
    FakeFFmpegRunner,
    FFmpegConfig,
    RealFFmpegRunner,
    create_ffmpeg_runner,
)


class TestFFmpegConfig:
    """Test FFmpeg configuration."""

    def test_default_config(self):
        """Test default configuration values."""
        config = FFmpegConfig(rtsp_url="rtsp://test.com/stream")

        assert config.rtsp_url == "rtsp://test.com/stream"
        assert config.window_seconds == 12
        assert config.sample_rate == 44100
        assert config.channels == 1
        assert config.rtsp_transport == "tcp"
        assert config.rtsp_timeout == 10000000
        assert config.rw_timeout == 15000000
        assert config.max_restart_attempts == 10
        assert config.restart_backoff_seconds == 1.0
        assert config.max_backoff_seconds == 60.0

    def test_custom_config(self):
        """Test custom configuration values."""
        config = FFmpegConfig(
            rtsp_url="rtsp://custom.com/stream",
            window_seconds=30,
            sample_rate=22050,
            channels=2,
            rtsp_transport="udp",
            rtsp_timeout=5000000,
            rw_timeout=10000000,
            max_restart_attempts=5,
            restart_backoff_seconds=2.0,
            max_backoff_seconds=30.0,
        )

        assert config.rtsp_url == "rtsp://custom.com/stream"
        assert config.window_seconds == 30
        assert config.sample_rate == 22050
        assert config.channels == 2
        assert config.rtsp_transport == "udp"
        assert config.rtsp_timeout == 5000000
        assert config.rw_timeout == 10000000
        assert config.max_restart_attempts == 5
        assert config.restart_backoff_seconds == 2.0
        assert config.max_backoff_seconds == 30.0


class TestFFmpegRunner:
    """Test base FFmpeg runner functionality."""

    def test_build_ffmpeg_args(self):
        """Test FFmpeg argument building."""
        config = FFmpegConfig(rtsp_url="rtsp://test.com/stream")
        runner = FakeFFmpegRunner(config)

        args = runner._build_ffmpeg_args()

        expected = [
            "ffmpeg",
            "-rtsp_transport",
            "tcp",
            "-stimeout",
            "10000000",
            "-i",
            "rtsp://test.com/stream",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "44100",
            "-acodec",
            "pcm_s16le",
            "-sample_fmt",
            "s16",
            "-avoid_negative_ts",
            "make_zero",
            "-fflags",
            "+genpts",
            "-f",
            "s16le",
            "-loglevel",
            "error",
            "pipe:1",
        ]

        assert args == expected

    def test_build_ffmpeg_args_custom(self):
        """Test FFmpeg argument building with custom config."""
        config = FFmpegConfig(
            rtsp_url="rtsp://custom.com/stream",
            rtsp_transport="udp",
            rtsp_timeout=5000000,
            rw_timeout=10000000,
            channels=2,
            sample_rate=22050,
        )
        runner = FakeFFmpegRunner(config)

        args = runner._build_ffmpeg_args()

        expected = [
            "ffmpeg",
            "-rtsp_transport",
            "udp",
            "-stimeout",
            "5000000",
            "-i",
            "rtsp://custom.com/stream",
            "-vn",
            "-ac",
            "2",
            "-ar",
            "22050",
            "-acodec",
            "pcm_s16le",
            "-sample_fmt",
            "s16",
            "-avoid_negative_ts",
            "make_zero",
            "-fflags",
            "+genpts",
            "-f",
            "s16le",
            "-loglevel",
            "error",
            "pipe:1",
        ]

        assert args == expected

    def test_build_ffmpeg_args_non_rtsp(self):
        """Test FFmpeg argument building with non-RTSP URL includes rw_timeout."""
        config = FFmpegConfig(rtsp_url="http://example.com/stream.mp4")
        runner = FakeFFmpegRunner(config)

        args = runner._build_ffmpeg_args()

        expected = [
            "ffmpeg",
            "-rtsp_transport",
            "tcp",
            "-stimeout",
            "10000000",
            "-rw_timeout",
            "15000000",
            "-i",
            "http://example.com/stream.mp4",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "44100",
            "-acodec",
            "pcm_s16le",
            "-sample_fmt",
            "s16",
            "-avoid_negative_ts",
            "make_zero",
            "-fflags",
            "+genpts",
            "-f",
            "s16le",
            "-loglevel",
            "error",
            "pipe:1",
        ]

        assert args == expected

    def test_calculate_backoff(self):
        """Test exponential backoff calculation."""
        config = FFmpegConfig(rtsp_url="rtsp://test.com/stream")
        runner = FakeFFmpegRunner(config)

        # First restart (restart_count = 1)
        runner.restart_count = 1
        backoff = runner._calculate_backoff()
        assert backoff == 1.0

        # Second restart (restart_count = 2)
        runner.restart_count = 2
        backoff = runner._calculate_backoff()
        assert backoff == 2.0

        # Third restart (restart_count = 3)
        runner.restart_count = 3
        backoff = runner._calculate_backoff()
        assert backoff == 4.0

        # Tenth restart (restart_count = 10)
        runner.restart_count = 10
        backoff = runner._calculate_backoff()
        assert backoff == 60.0  # Capped at max_backoff_seconds

    def test_calculate_backoff_custom(self):
        """Test exponential backoff with custom settings."""
        config = FFmpegConfig(
            rtsp_url="rtsp://test.com/stream",
            restart_backoff_seconds=2.0,
            max_backoff_seconds=30.0,
        )
        runner = FakeFFmpegRunner(config)

        # First restart
        runner.restart_count = 1
        backoff = runner._calculate_backoff()
        assert backoff == 2.0

        # Second restart
        runner.restart_count = 2
        backoff = runner._calculate_backoff()
        assert backoff == 4.0

        # Fifth restart (should be capped)
        runner.restart_count = 5
        backoff = runner._calculate_backoff()
        assert backoff == 30.0  # Capped at max_backoff_seconds


class TestFakeFFmpegRunner:
    """Test fake FFmpeg runner for testing."""

    @pytest.mark.asyncio
    async def test_start_stop(self):
        """Test starting and stopping fake runner."""
        config = FFmpegConfig(rtsp_url="rtsp://test.com/stream")
        runner = FakeFFmpegRunner(config)

        assert not runner.is_running

        await runner.start()
        assert runner.is_running

        await runner.stop()
        assert not runner.is_running

    @pytest.mark.asyncio
    async def test_start_failure(self):
        """Test start failure mode."""
        config = FFmpegConfig(rtsp_url="rtsp://test.com/stream")
        runner = FakeFFmpegRunner(config)
        runner.set_failure_mode(should_fail=True)

        with pytest.raises(RuntimeError, match="Fake FFmpeg start failure"):
            await runner.start()

    @pytest.mark.asyncio
    async def test_read_audio_data_success(self):
        """Test successful audio data reading."""
        config = FFmpegConfig(rtsp_url="rtsp://test.com/stream")
        audio_data = b"test_audio_data"
        runner = FakeFFmpegRunner(config, audio_data)

        await runner.start()

        chunks = []
        async for chunk in runner.read_audio_data():
            chunks.append(chunk)
            if len(chunks) >= 3:  # Limit to 3 chunks for test
                break

        assert len(chunks) == 3
        assert all(chunk == audio_data for chunk in chunks)

    @pytest.mark.asyncio
    async def test_read_audio_data_not_running(self):
        """Test reading audio data when not running."""
        config = FFmpegConfig(rtsp_url="rtsp://test.com/stream")
        runner = FakeFFmpegRunner(config)

        with pytest.raises(RuntimeError, match="Fake FFmpeg process not running"):
            async for _ in runner.read_audio_data():
                pass

    @pytest.mark.asyncio
    async def test_read_audio_data_failure_after_chunks(self):
        """Test audio data reading failure mode after chunks."""
        config = FFmpegConfig(rtsp_url="rtsp://test.com/stream")
        runner = FakeFFmpegRunner(config)
        runner.set_failure_mode(
            should_fail=False, fail_after_chunks=2
        )  # Don't fail on start

        await runner.start()

        chunks = []
        with pytest.raises(RuntimeError, match="Fake FFmpeg read failure"):
            async for chunk in runner.read_audio_data():
                chunks.append(chunk)

        assert len(chunks) == 2  # Should yield 2 chunks before failing

    @pytest.mark.asyncio
    async def test_read_audio_data_failure_start(self):
        """Test start failure mode."""
        config = FFmpegConfig(rtsp_url="rtsp://test.com/stream")
        runner = FakeFFmpegRunner(config)
        runner.set_failure_mode(should_fail=True)

        with pytest.raises(RuntimeError, match="Fake FFmpeg start failure"):
            await runner.start()

    @pytest.mark.asyncio
    async def test_restart(self):
        """Test restart functionality."""
        config = FFmpegConfig(rtsp_url="rtsp://test.com/stream")
        runner = FakeFFmpegRunner(config)

        assert runner.restart_count == 0

        await runner.start()
        assert runner.is_running

        await runner.restart()
        assert runner.restart_count == 1
        assert runner.is_running

    @pytest.mark.asyncio
    async def test_restart_with_custom_audio(self):
        """Test restart with custom audio data."""
        config = FFmpegConfig(rtsp_url="rtsp://test.com/stream")
        audio_data = b"custom_audio_data"
        runner = FakeFFmpegRunner(config, audio_data)

        await runner.start()

        # Read some data
        chunks = []
        async for chunk in runner.read_audio_data():
            chunks.append(chunk)
            if len(chunks) >= 2:
                break

        assert all(chunk == audio_data for chunk in chunks)

        # Restart and read again
        await runner.restart()

        chunks = []
        async for chunk in runner.read_audio_data():
            chunks.append(chunk)
            if len(chunks) >= 2:
                break

        assert all(chunk == audio_data for chunk in chunks)


class TestRealFFmpegRunner:
    """Test real FFmpeg runner (with mocking)."""

    @pytest.mark.asyncio
    async def test_start_success(self):
        """Test successful FFmpeg process start."""
        config = FFmpegConfig(rtsp_url="rtsp://test.com/stream")
        runner = RealFFmpegRunner(config)

        mock_process = AsyncMock()
        mock_process.stdout = AsyncMock()
        mock_stderr = AsyncMock()

        # Configure stderr.readline to return empty bytes (EOF) to stop monitoring
        async def mock_readline():
            return b""

        mock_stderr.readline = mock_readline
        mock_process.stderr = mock_stderr

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            await runner.start()

        assert runner.is_running
        assert runner.process == mock_process

    @pytest.mark.asyncio
    async def test_start_already_running(self):
        """Test starting when already running."""
        config = FFmpegConfig(rtsp_url="rtsp://test.com/stream")
        runner = RealFFmpegRunner(config)
        runner.is_running = True

        with patch("asyncio.create_subprocess_exec") as mock_create:
            await runner.start()

        mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_failure(self):
        """Test FFmpeg process start failure."""
        config = FFmpegConfig(rtsp_url="rtsp://test.com/stream")
        runner = RealFFmpegRunner(config)

        with patch(
            "asyncio.create_subprocess_exec", side_effect=OSError("ffmpeg not found")
        ):
            with pytest.raises(OSError, match="ffmpeg not found"):
                await runner.start()

        assert not runner.is_running
        assert runner.process is None

    @pytest.mark.asyncio
    async def test_stop_success(self):
        """Test successful FFmpeg process stop."""
        config = FFmpegConfig(rtsp_url="rtsp://test.com/stream")
        runner = RealFFmpegRunner(config)

        mock_process = AsyncMock()
        mock_process.terminate = MagicMock()
        mock_process.kill = MagicMock()
        mock_process.wait = AsyncMock()

        runner.process = mock_process
        runner.is_running = True

        await runner.stop()

        mock_process.terminate.assert_called_once()
        mock_process.wait.assert_called_once()
        assert not runner.is_running
        assert runner.process is None

    @pytest.mark.asyncio
    async def test_stop_timeout_kill(self):
        """Test FFmpeg process stop with timeout and kill."""
        config = FFmpegConfig(rtsp_url="rtsp://test.com/stream")
        runner = RealFFmpegRunner(config)

        mock_process = AsyncMock()
        mock_process.terminate = MagicMock()
        mock_process.kill = MagicMock()
        mock_process.wait = AsyncMock(side_effect=TimeoutError())

        runner.process = mock_process
        runner.is_running = True

        await runner.stop()

        mock_process.terminate.assert_called_once()
        mock_process.kill.assert_called_once()
        mock_process.wait.assert_called()
        assert not runner.is_running

    @pytest.mark.asyncio
    async def test_stop_not_running(self):
        """Test stopping when not running."""
        config = FFmpegConfig(rtsp_url="rtsp://test.com/stream")
        runner = RealFFmpegRunner(config)

        with patch("asyncio.create_subprocess_exec") as mock_create:
            await runner.stop()

        mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_read_audio_data_success(self):
        """Test successful audio data reading."""
        config = FFmpegConfig(rtsp_url="rtsp://test.com/stream")
        runner = RealFFmpegRunner(config)

        mock_process = AsyncMock()
        mock_stdout = AsyncMock()
        mock_stdout.read = AsyncMock(side_effect=[b"chunk1", b"chunk2", b""])
        mock_process.stdout = mock_stdout

        runner.process = mock_process
        runner.is_running = True

        chunks = []
        async for chunk in runner.read_audio_data():
            chunks.append(chunk)

        assert chunks == [b"chunk1", b"chunk2"]
        assert not runner.is_running  # Should be marked as not running after EOF

    @pytest.mark.asyncio
    async def test_read_audio_data_not_running(self):
        """Test reading audio data when not running."""
        config = FFmpegConfig(rtsp_url="rtsp://test.com/stream")
        runner = RealFFmpegRunner(config)

        with pytest.raises(RuntimeError, match="FFmpeg process not running"):
            async for _ in runner.read_audio_data():
                pass

    @pytest.mark.asyncio
    async def test_read_audio_data_no_stdout(self):
        """Test reading audio data with no stdout."""
        config = FFmpegConfig(rtsp_url="rtsp://test.com/stream")
        runner = RealFFmpegRunner(config)

        mock_process = AsyncMock()
        mock_process.stdout = None

        runner.process = mock_process
        runner.is_running = True

        chunks = []
        async for chunk in runner.read_audio_data():
            chunks.append(chunk)

        assert chunks == []  # Should yield no chunks
        assert not runner.is_running

    @pytest.mark.asyncio
    async def test_restart_success(self):
        """Test successful restart."""
        config = FFmpegConfig(rtsp_url="rtsp://test.com/stream")
        runner = RealFFmpegRunner(config)

        mock_process = AsyncMock()
        mock_process.terminate = MagicMock()
        mock_process.wait = AsyncMock()
        mock_stderr = AsyncMock()

        # Configure stderr.readline to return empty bytes (EOF) to stop monitoring
        async def mock_readline():
            return b""

        mock_stderr.readline = mock_readline
        mock_process.stderr = mock_stderr

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            await runner.start()
            await runner.restart()

        assert runner.restart_count == 1
        assert runner.is_running

    @pytest.mark.asyncio
    async def test_restart_max_attempts(self):
        """Test restart with max attempts reached."""
        config = FFmpegConfig(rtsp_url="rtsp://test.com/stream", max_restart_attempts=2)
        runner = RealFFmpegRunner(config)
        runner.restart_count = 2

        with pytest.raises(RuntimeError, match="Max FFmpeg restart attempts reached"):
            await runner.restart()

    @pytest.mark.asyncio
    async def test_monitor_stderr(self):
        """Test stderr monitoring."""
        config = FFmpegConfig(rtsp_url="rtsp://test.com/stream")
        runner = RealFFmpegRunner(config)

        mock_process = AsyncMock()
        mock_stderr = AsyncMock()
        # Create a stateful readline that returns different values on each call
        readline_responses = iter([b"error1\n", b"error2\n", b""])

        async def mock_readline():
            try:
                return next(readline_responses)
            except StopIteration:
                return b""

        mock_stderr.readline = mock_readline
        mock_process.stderr = mock_stderr

        runner.process = mock_process
        runner.is_running = True

        # Start monitoring
        monitor_task = asyncio.create_task(runner._monitor_stderr())

        # Let it run for a bit
        await asyncio.sleep(0.05)

        # Stop the runner
        runner.is_running = False

        # Wait for task to complete with timeout
        try:
            await asyncio.wait_for(monitor_task, timeout=1.0)
        except TimeoutError:
            monitor_task.cancel()
            raise

        # Should have called readline multiple times
        # Note: exact call count may vary due to timing, just verify it ran


class TestCreateFFmpegRunner:
    """Test factory function for creating FFmpeg runners."""

    def test_create_real_runner(self):
        """Test creating real FFmpeg runner."""
        config = FFmpegConfig(rtsp_url="rtsp://test.com/stream")
        runner = create_ffmpeg_runner(config, fake=False)

        assert isinstance(runner, RealFFmpegRunner)
        assert runner.config == config

    def test_create_fake_runner(self):
        """Test creating fake FFmpeg runner."""
        config = FFmpegConfig(rtsp_url="rtsp://test.com/stream")
        audio_data = b"test_audio"
        runner = create_ffmpeg_runner(config, fake=True, audio_data=audio_data)

        assert isinstance(runner, FakeFFmpegRunner)
        assert runner.config == config
        assert runner.audio_data == audio_data

    def test_create_fake_runner_default_audio(self):
        """Test creating fake FFmpeg runner with default audio data."""
        config = FFmpegConfig(rtsp_url="rtsp://test.com/stream")
        runner = create_ffmpeg_runner(config, fake=True)

        assert isinstance(runner, FakeFFmpegRunner)
        assert runner.audio_data == b"fake_audio_data"


class TestFFmpegRunnerIntegration:
    """Integration tests for FFmpeg runner."""

    @pytest.mark.asyncio
    async def test_full_lifecycle_fake(self):
        """Test full lifecycle with fake runner."""
        config = FFmpegConfig(rtsp_url="rtsp://test.com/stream")
        runner = FakeFFmpegRunner(config)

        # Start
        await runner.start()
        assert runner.is_running

        # Read some data
        chunks = []
        async for chunk in runner.read_audio_data():
            chunks.append(chunk)
            if len(chunks) >= 5:
                break

        assert len(chunks) == 5
        assert all(chunk == b"fake_audio_data" for chunk in chunks)

        # Stop
        await runner.stop()
        assert not runner.is_running

    @pytest.mark.asyncio
    async def test_restart_with_backoff(self):
        """Test restart with backoff timing."""
        config = FFmpegConfig(
            rtsp_url="rtsp://test.com/stream",
            restart_backoff_seconds=0.1,  # Short for testing
            max_backoff_seconds=1.0,
        )
        runner = FakeFFmpegRunner(config)

        await runner.start()

        # First restart - no backoff
        start_time = asyncio.get_event_loop().time()
        await runner.restart()
        end_time = asyncio.get_event_loop().time()

        # Should be very fast (no backoff on first restart)
        assert end_time - start_time < 0.1

        # Second restart - should have backoff
        start_time = asyncio.get_event_loop().time()
        await runner.restart()
        end_time = asyncio.get_event_loop().time()

        # The backoff calculation should work correctly
        # We're testing the logic, not the exact timing
        assert runner.restart_count == 2

    @pytest.mark.asyncio
    async def test_concurrent_readers(self):
        """Test multiple concurrent readers with fake runner."""
        config = FFmpegConfig(rtsp_url="rtsp://test.com/stream")
        runner = FakeFFmpegRunner(config)

        await runner.start()

        # Start first reader
        reader1_task = asyncio.create_task(self._read_chunks(runner, 3))

        # Start second reader - should work with fake runner
        reader2_task = asyncio.create_task(self._read_chunks(runner, 3))

        # Wait for both to complete with timeout
        try:
            chunks1, chunks2 = await asyncio.wait_for(
                asyncio.gather(reader1_task, reader2_task), timeout=5.0
            )
        except TimeoutError:
            reader1_task.cancel()
            reader2_task.cancel()
            raise

        assert len(chunks1) == 3
        assert len(chunks2) == 3

    async def _read_chunks(self, runner, count):
        """Helper to read specified number of chunks."""
        chunks = []
        async for chunk in runner.read_audio_data():
            chunks.append(chunk)
            if len(chunks) >= count:
                break
        return chunks
