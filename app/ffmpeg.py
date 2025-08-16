"""Async FFmpeg process management for RTSP stream ingestion."""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass

from app.metrics import ffmpeg_restarts_total
from app.tracing import get_tracer

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)


@dataclass
class FFmpegConfig:
    """Configuration for FFmpeg process."""

    rtsp_url: str
    window_seconds: int = 12
    sample_rate: int = 44100
    channels: int = 1
    rtsp_transport: str = "tcp"
    rtsp_timeout: int = 10000000  # 10 seconds in microseconds
    rw_timeout: int = 15000000  # 15 seconds in microseconds
    max_restart_attempts: int = 10
    restart_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 60.0


class FFmpegRunner(ABC):
    """Abstract base class for FFmpeg process management."""

    def __init__(self, config: FFmpegConfig):
        self.config = config
        self.process: asyncio.subprocess.Process | None = None
        self.restart_count = 0
        self.last_restart_time = 0.0
        self.is_running = False

    @abstractmethod
    async def start(self) -> None:
        """Start the FFmpeg process."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the FFmpeg process."""
        pass

    @abstractmethod
    async def read_audio_data(self) -> AsyncGenerator[bytes, None]:
        """Read audio data from FFmpeg stdout."""
        pass

    def _build_ffmpeg_args(self) -> list[str]:
        """Build FFmpeg command line arguments."""
        return [
            "ffmpeg",
            "-rtsp_transport",
            self.config.rtsp_transport,
            "-stimeout",
            str(self.config.rtsp_timeout),
            "-rw_timeout",
            str(self.config.rw_timeout),
            "-i",
            self.config.rtsp_url,
            "-vn",  # No video
            "-ac",
            str(self.config.channels),  # Audio channels
            "-ar",
            str(self.config.sample_rate),  # Sample rate
            "-f",
            "wav",  # WAV format
            "-loglevel",
            "error",  # Only errors
            "pipe:1",  # Output to stdout
        ]

    def _calculate_backoff(self) -> float:
        """Calculate exponential backoff delay."""
        if self.restart_count == 0:
            return 0.0

        backoff = self.config.restart_backoff_seconds * (2 ** (self.restart_count - 1))
        return min(backoff, self.config.max_backoff_seconds)

    async def _wait_for_backoff(self) -> None:
        """Wait for backoff delay if needed."""
        if self.restart_count > 0:
            delay = self._calculate_backoff()
            if delay > 0:
                logger.warning(
                    "FFmpeg restart backoff",
                    extra={
                        "restart_count": self.restart_count,
                        "backoff_seconds": delay,
                        "rtsp_url": self.config.rtsp_url,
                    },
                )
                await asyncio.sleep(delay)


class RealFFmpegRunner(FFmpegRunner):
    """Real FFmpeg process runner for production use."""

    async def start(self) -> None:
        """Start the FFmpeg process."""
        if self.is_running:
            return

        await self._wait_for_backoff()

        try:
            args = self._build_ffmpeg_args()
            logger.info(
                "Starting FFmpeg process",
                extra={
                    "ffmpeg_args": args,
                    "rtsp_url": self.config.rtsp_url,
                    "restart_count": self.restart_count,
                },
            )

            self.process = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            self.is_running = True
            self.last_restart_time = time.time()

            # Start stderr monitoring
            asyncio.create_task(self._monitor_stderr())

        except Exception as e:
            logger.error(
                "Failed to start FFmpeg process",
                extra={
                    "error": str(e),
                    "rtsp_url": self.config.rtsp_url,
                    "restart_count": self.restart_count,
                },
            )
            raise

    async def stop(self) -> None:
        """Stop the FFmpeg process."""
        if not self.is_running or not self.process:
            return

        try:
            logger.info(
                "Stopping FFmpeg process", extra={"rtsp_url": self.config.rtsp_url}
            )

            self.process.terminate()

            # Wait for graceful shutdown
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except TimeoutError:
                logger.warning(
                    "FFmpeg process did not terminate gracefully, killing",
                    extra={"rtsp_url": self.config.rtsp_url},
                )
                self.process.kill()
                await self.process.wait()

        except Exception as e:
            logger.error(
                "Error stopping FFmpeg process",
                extra={"error": str(e), "rtsp_url": self.config.rtsp_url},
            )
        finally:
            self.is_running = False
            self.process = None

    async def read_audio_data(self) -> AsyncGenerator[bytes, None]:
        """Read audio data from FFmpeg stdout."""
        if not self.is_running or not self.process:
            raise RuntimeError("FFmpeg process not running")

        try:
            while self.is_running and self.process:
                if self.process.stdout is None:
                    break

                # Read in chunks to avoid blocking
                chunk = await self.process.stdout.read(4096)
                if not chunk:
                    # EOF - process ended
                    break

                yield chunk

        except Exception as e:
            logger.error(
                "Error reading from FFmpeg stdout",
                extra={"error": str(e), "rtsp_url": self.config.rtsp_url},
            )
            raise
        finally:
            # Process ended, mark as not running
            self.is_running = False

    async def _monitor_stderr(self) -> None:
        """Monitor FFmpeg stderr for error messages."""
        if not self.process or not self.process.stderr:
            return

        try:
            while self.is_running and self.process:
                line = await self.process.stderr.readline()
                if not line:
                    break

                error_msg = line.decode().strip()
                if error_msg:
                    logger.warning(
                        "FFmpeg stderr",
                        extra={"error": error_msg, "rtsp_url": self.config.rtsp_url},
                    )

        except Exception as e:
            logger.error(
                "Error monitoring FFmpeg stderr",
                extra={"error": str(e), "rtsp_url": self.config.rtsp_url},
            )

    async def restart(self) -> None:
        """Restart the FFmpeg process with backoff."""
        if self.restart_count >= self.config.max_restart_attempts:
            logger.error(
                "Max FFmpeg restart attempts reached",
                extra={
                    "max_attempts": self.config.max_restart_attempts,
                    "rtsp_url": self.config.rtsp_url,
                },
            )
            raise RuntimeError("Max FFmpeg restart attempts reached")

        self.restart_count += 1

        # Record restart metric
        ffmpeg_restarts_total.labels(stream="unknown").inc()

        logger.warning(
            "Restarting FFmpeg process",
            extra={
                "restart_count": self.restart_count,
                "rtsp_url": self.config.rtsp_url,
            },
        )

        await self.stop()
        await self.start()


class FakeFFmpegRunner(FFmpegRunner):
    """Fake FFmpeg runner for testing."""

    def __init__(self, config: FFmpegConfig, audio_data: bytes | None = None):
        super().__init__(config)
        self.audio_data = audio_data or b"fake_audio_data"
        self._should_fail = False
        self._fail_after_chunks = 0
        self._chunks_yielded = 0

    def set_failure_mode(
        self, should_fail: bool = True, fail_after_chunks: int = 0
    ) -> None:
        """Configure failure mode for testing."""
        self._should_fail = should_fail
        self._fail_after_chunks = fail_after_chunks
        self._chunks_yielded = 0

    async def start(self) -> None:
        """Start the fake FFmpeg process."""
        if self._should_fail:
            raise RuntimeError("Fake FFmpeg start failure")
        self.is_running = True

    async def stop(self) -> None:
        """Stop the fake FFmpeg process."""
        self.is_running = False

    async def read_audio_data(self) -> AsyncGenerator[bytes, None]:
        """Yield fake audio data."""
        if not self.is_running:
            raise RuntimeError("Fake FFmpeg process not running")

        while self.is_running:
            # Check if we should fail after a certain number of chunks
            if (
                self._fail_after_chunks > 0
                and self._chunks_yielded >= self._fail_after_chunks
            ):
                self.is_running = False
                raise RuntimeError("Fake FFmpeg read failure")

            self._chunks_yielded += 1
            yield self.audio_data
            await asyncio.sleep(0.1)  # Simulate real-time data

    async def restart(self) -> None:
        """Restart the fake FFmpeg process."""
        self.restart_count += 1
        await self.stop()
        await self.start()


def create_ffmpeg_runner(
    config: FFmpegConfig, fake: bool = False, audio_data: bytes | None = None
) -> FFmpegRunner:
    """Factory function to create FFmpeg runner."""
    if fake:
        return FakeFFmpegRunner(config, audio_data)
    else:
        return RealFFmpegRunner(config)
