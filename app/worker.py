"""Worker orchestration for ying - coordinates FFmpeg, scheduling, recognition, and DB."""

import asyncio
import logging
from pathlib import Path

from .config import Config, StreamConfig
from .db.repo import PlayRepository, RecognitionRepository, TrackRepository
from .ffmpeg import FFmpegRunner, RealFFmpegRunner
from .recognizers.acoustid_recognizer import AcoustIDRecognizer
from .recognizers.base import MusicRecognizer, RecognitionResult
from .recognizers.shazamio_recognizer import ShazamioRecognizer
from .scheduler import Clock, RealClock, TwoHitAggregator, WindowScheduler

logger = logging.getLogger(__name__)


class ParallelRecognizers:
    """Manages parallel recognition across multiple providers with capacity limits."""

    def __init__(
        self,
        recognizers: dict[str, MusicRecognizer],
        global_semaphore: asyncio.Semaphore,
        per_provider_semaphores: dict[str, asyncio.Semaphore],
    ) -> None:
        """Initialize parallel recognizers.

        Args:
            recognizers: Dict of provider name to recognizer instance.
            global_semaphore: Global semaphore for total recognition capacity.
            per_provider_semaphores: Per-provider semaphores for individual limits.
        """
        self.recognizers = recognizers
        self.global_semaphore = global_semaphore
        self.per_provider_semaphores = per_provider_semaphores

    async def recognize_parallel(
        self, wav_bytes: bytes, timeout_seconds: float = 30.0
    ) -> list[RecognitionResult]:
        """Run recognition in parallel across all enabled providers.

        Args:
            wav_bytes: WAV audio data to recognize.
            timeout_seconds: Timeout for each recognition attempt.

        Returns:
            List of recognition results (may be empty if all fail).
        """
        if not self.recognizers:
            return []

        # Create tasks for each recognizer
        tasks = []
        for provider_name, recognizer in self.recognizers.items():
            task = asyncio.create_task(
                self._recognize_with_limits(
                    provider_name, recognizer, wav_bytes, timeout_seconds
                )
            )
            tasks.append(task)

        # Wait for all to complete and gather results
        results: list[RecognitionResult] = []
        completed_tasks = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(completed_tasks):
            provider_name = list(self.recognizers.keys())[i]
            if isinstance(result, Exception):
                logger.warning(
                    f"Recognition failed for provider {provider_name}: {result}"
                )
            elif result is not None and isinstance(result, RecognitionResult):
                results.append(result)

        return results

    async def _recognize_with_limits(
        self,
        provider_name: str,
        recognizer: MusicRecognizer,
        wav_bytes: bytes,
        timeout_seconds: float,
    ) -> RecognitionResult | None:
        """Run recognition with capacity limits.

        Args:
            provider_name: Name of the provider.
            recognizer: Recognizer instance.
            wav_bytes: WAV audio data.
            timeout_seconds: Timeout for recognition.

        Returns:
            Recognition result or None if failed/limited.
        """
        # Check per-provider semaphore first (non-blocking)
        provider_sem = self.per_provider_semaphores.get(provider_name)
        if provider_sem and provider_sem.locked():
            logger.debug(f"Provider {provider_name} at capacity, skipping")
            return None

        # Acquire both global and provider semaphores
        async with self.global_semaphore:
            if provider_sem:
                async with provider_sem:
                    return await self._do_recognize(
                        provider_name, recognizer, wav_bytes, timeout_seconds
                    )
            else:
                return await self._do_recognize(
                    provider_name, recognizer, wav_bytes, timeout_seconds
                )

    async def _do_recognize(
        self,
        provider_name: str,
        recognizer: MusicRecognizer,
        wav_bytes: bytes,
        timeout_seconds: float,
    ) -> RecognitionResult | None:
        """Actually perform the recognition.

        Args:
            provider_name: Name of the provider.
            recognizer: Recognizer instance.
            wav_bytes: WAV audio data.
            timeout_seconds: Timeout for recognition.

        Returns:
            Recognition result or None if failed.
        """
        try:
            logger.debug(f"Starting recognition with {provider_name}")
            result = await recognizer.recognize(wav_bytes, timeout_seconds)
            logger.info(
                f"Recognition successful with {provider_name}: "
                f"{result.title} by {result.artist} (confidence: {result.confidence})"
            )
            return result
        except Exception as e:
            logger.warning(f"Recognition failed with {provider_name}: {e}")
            return None


class StreamWorker:
    """Worker for a single RTSP stream - orchestrates the full pipeline."""

    def __init__(
        self,
        stream_config: StreamConfig,
        config: Config,
        clock: Clock,
        ffmpeg_runner: FFmpegRunner,
        parallel_recognizers: ParallelRecognizers,
        track_repo: TrackRepository,
        play_repo: PlayRepository,
        recognition_repo: RecognitionRepository,
    ) -> None:
        """Initialize stream worker.

        Args:
            stream_config: Configuration for this stream.
            config: Global configuration.
            clock: Clock implementation for timing.
            ffmpeg_runner: FFmpeg runner for audio ingestion.
            parallel_recognizers: Parallel recognizers for music recognition.
            track_repo: Repository for track operations.
            play_repo: Repository for play operations.
            recognition_repo: Repository for recognition logging.
        """
        self.stream_config = stream_config
        self.config = config
        self.clock = clock
        self.ffmpeg_runner = ffmpeg_runner
        self.parallel_recognizers = parallel_recognizers
        self.track_repo = track_repo
        self.play_repo = play_repo
        self.recognition_repo = recognition_repo

        # Create scheduler and aggregator
        self.window_scheduler = WindowScheduler(config=config, clock=clock)

        self.two_hit_aggregator = TwoHitAggregator(config=config)

        # State tracking
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the worker."""
        if self._running:
            logger.warning(
                f"Worker for stream {self.stream_config.name} already running"
            )
            return

        logger.info(f"Starting worker for stream {self.stream_config.name}")
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Stop the worker."""
        if not self._running:
            return

        logger.info(f"Stopping worker for stream {self.stream_config.name}")
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # Stop FFmpeg
        await self.ffmpeg_runner.stop()

    async def _run(self) -> None:
        """Main worker loop."""
        try:
            # Start FFmpeg runner
            await self.ffmpeg_runner.start()
            logger.info(f"FFmpeg started for stream {self.stream_config.name}")

            # Process audio windows
            window_count = 0
            async for window in self.window_scheduler.schedule_windows(
                self.ffmpeg_runner.read_audio_data()
            ):
                if not self._running:
                    break

                window_count += 1
                if window_count == 1:
                    logger.info(
                        f"Received first audio window for stream {self.stream_config.name}"
                    )
                elif window_count % 10 == 0:  # Log every 10th window
                    logger.info(
                        f"Processed {window_count} audio windows for stream {self.stream_config.name}"
                    )

                await self._process_window(window.wav_bytes)

        except Exception as e:
            logger.error(f"Worker error for stream {self.stream_config.name}: {e}")
            raise
        finally:
            await self.ffmpeg_runner.stop()
            logger.info(f"FFmpeg stopped for stream {self.stream_config.name}")

    async def _process_window(self, window_bytes: bytes) -> None:
        """Process a single audio window.

        Args:
            window_bytes: WAV audio data for the window.
        """
        window_timestamp = self.clock.now()

        logger.debug(
            f"Processing window for stream {self.stream_config.name} "
            f"at {window_timestamp} ({len(window_bytes)} bytes)"
        )

        # Run parallel recognition
        recognition_results = await self.parallel_recognizers.recognize_parallel(
            window_bytes, timeout_seconds=30.0
        )

        # Log all recognitions for diagnostics
        for result in recognition_results:
            await self.recognition_repo.insert_recognition_by_name(
                stream_name=self.stream_config.name,
                provider=result.provider,
                provider_track_id=result.provider_track_id,
                title=result.title,
                artist=result.artist,
                album=result.album,
                isrc=result.isrc,
                artwork_url=result.artwork_url,
                confidence=result.confidence,
                recognized_at_utc=result.recognized_at_utc,
                raw_response=result.raw_response,
            )

        # Check for play confirmations (two-hit logic)
        confirmed_plays = []
        for result in recognition_results:
            confirmed_result = self.two_hit_aggregator.process_recognition(
                self.stream_config.name, result
            )
            if confirmed_result:
                confirmed_plays.append(confirmed_result)

        # Insert confirmed plays
        for result in confirmed_plays:
            # First ensure the track exists
            track_id = await self.track_repo.upsert_track(
                provider=result.provider,
                provider_track_id=result.provider_track_id,
                title=result.title,
                artist=result.artist,
                album=result.album,
                isrc=result.isrc,
                artwork_url=result.artwork_url,
                metadata=result.raw_response,
            )

            # Get stream_id and calculate dedup_bucket
            stream_id = await self.recognition_repo._get_stream_id(
                self.stream_config.name
            )
            dedup_bucket = (
                int(result.recognized_at_utc.timestamp()) // self.config.dedup_seconds
            )

            # Then insert the play
            await self.play_repo.insert_play(
                track_id=track_id,
                stream_id=stream_id,
                recognized_at_utc=result.recognized_at_utc,
                dedup_bucket=dedup_bucket,
                confidence=result.confidence,
            )

            logger.info(
                f"Confirmed play for stream {self.stream_config.name}: "
                f"{result.title} by {result.artist}"
            )


class WorkerManager:
    """Manages all stream workers with global capacity limits."""

    def __init__(self, config: Config, clock: Clock | None = None) -> None:
        """Initialize worker manager.

        Args:
            config: Global configuration.
            clock: Clock implementation (defaults to RealClock).
        """
        self.config = config
        self.clock = clock or RealClock()

        # Global capacity management
        self.global_semaphore = asyncio.Semaphore(
            config.global_max_inflight_recognitions
        )

        # Per-provider semaphores
        self.per_provider_semaphores: dict[str, asyncio.Semaphore] = {}
        if config.acoustid_enabled:
            self.per_provider_semaphores["acoustid"] = asyncio.Semaphore(
                config.per_provider_max_inflight
            )
        # Shazam is always enabled (no API key required)
        self.per_provider_semaphores["shazam"] = asyncio.Semaphore(
            config.per_provider_max_inflight
        )

        # Repositories
        self.track_repo = TrackRepository(Path(config.db_path))
        self.play_repo = PlayRepository(Path(config.db_path))
        self.recognition_repo = RecognitionRepository(Path(config.db_path))

        # Workers
        self.workers: dict[str, StreamWorker] = {}

        # Stats tracking
        self._stats_task: asyncio.Task | None = None
        self._running = False

    def _create_recognizers(self) -> dict[str, MusicRecognizer]:
        """Create recognizer instances based on configuration.

        Returns:
            Dict of provider name to recognizer instance.
        """
        recognizers: dict[str, MusicRecognizer] = {}

        # Shazam is always enabled
        recognizers["shazam"] = ShazamioRecognizer(timeout_seconds=30.0)

        # AcoustID is optional
        if self.config.acoustid_enabled and self.config.acoustid_api_key:
            recognizers["acoustid"] = AcoustIDRecognizer(
                api_key=self.config.acoustid_api_key,
                chromaprint_path=self.config.chromaprint_path,
                timeout_seconds=30.0,
            )

        return recognizers

    def _create_parallel_recognizers(self) -> ParallelRecognizers:
        """Create parallel recognizers with capacity limits.

        Returns:
            ParallelRecognizers instance.
        """
        recognizers = self._create_recognizers()
        return ParallelRecognizers(
            recognizers=recognizers,
            global_semaphore=self.global_semaphore,
            per_provider_semaphores=self.per_provider_semaphores,
        )

    def _create_worker(self, stream_config: StreamConfig) -> StreamWorker:
        """Create a worker for a stream.

        Args:
            stream_config: Configuration for the stream.

        Returns:
            StreamWorker instance.
        """
        # Create FFmpeg runner
        from .ffmpeg import FFmpegConfig

        ffmpeg_config = FFmpegConfig(
            rtsp_url=stream_config.url,
            window_seconds=self.config.window_seconds,
            sample_rate=44100,
            channels=1,
            rtsp_transport="tcp",
            rtsp_timeout=10000000,
            rw_timeout=15000000,
        )
        ffmpeg_runner = RealFFmpegRunner(ffmpeg_config)

        # Create parallel recognizers
        parallel_recognizers = self._create_parallel_recognizers()

        return StreamWorker(
            stream_config=stream_config,
            config=self.config,
            clock=self.clock,
            ffmpeg_runner=ffmpeg_runner,
            parallel_recognizers=parallel_recognizers,
            track_repo=self.track_repo,
            play_repo=self.play_repo,
            recognition_repo=self.recognition_repo,
        )

    async def start_all(self) -> None:
        """Start workers for all enabled streams."""
        logger.info("Starting all stream workers")

        # Log all configured streams at startup
        logger.info(f"Configured {len(self.config.streams)} streams:")
        for i, stream_config in enumerate(self.config.streams, 1):
            status = "ENABLED" if stream_config.enabled else "DISABLED"
            logger.info(f"  {i}. {stream_config.name}: {stream_config.url} ({status})")

        enabled_count = 0
        for stream_config in self.config.streams:
            if stream_config.enabled:
                worker = self._create_worker(stream_config)
                self.workers[stream_config.name] = worker
                await worker.start()
                logger.info(f"Started worker for stream {stream_config.name}")
                enabled_count += 1
            else:
                logger.info(f"Skipping disabled stream {stream_config.name}")

        logger.info(f"Started {enabled_count} active stream workers")

        # Start periodic stats logging
        self._running = True
        self._stats_task = asyncio.create_task(self._log_periodic_stats())

    async def stop_all(self) -> None:
        """Stop all workers."""
        logger.info("Stopping all stream workers")

        # Stop stats task
        self._running = False
        if self._stats_task:
            self._stats_task.cancel()
            try:
                await self._stats_task
            except asyncio.CancelledError:
                pass

        # Stop all workers in parallel
        stop_tasks = []
        for worker in self.workers.values():
            stop_tasks.append(asyncio.create_task(worker.stop()))

        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)

        self.workers.clear()
        logger.info("All stream workers stopped")

    async def restart_all(self) -> None:
        """Restart all workers (for hot reload)."""
        logger.info("Restarting all workers")
        await self.stop_all()
        await self.start_all()

    async def _log_periodic_stats(self) -> None:
        """Log periodic stats every 30 seconds."""
        while self._running:
            try:
                await asyncio.sleep(30)  # Log every 30 seconds

                # Collect stats from all workers
                stats = []
                for stream_name, worker in self.workers.items():
                    ffmpeg_status = (
                        "running" if worker.ffmpeg_runner.is_running else "stopped"
                    )
                    worker_status = "running" if worker._running else "stopped"

                    stats.append(
                        {
                            "stream": stream_name,
                            "worker": worker_status,
                            "ffmpeg": ffmpeg_status,
                            "url": worker.stream_config.url,
                        }
                    )

                # Log summary
                if stats:
                    logger.info(f"Stream status ({len(stats)} active streams):")
                    for stat in stats:
                        logger.info(
                            f"  {stat['stream']}: worker={stat['worker']}, ffmpeg={stat['ffmpeg']}"
                        )
                else:
                    logger.warning("No active streams found")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic stats logging: {e}")
                await asyncio.sleep(5)  # Brief pause on error
