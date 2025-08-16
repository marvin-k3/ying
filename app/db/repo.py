"""Database repository layer for ying."""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import aiosqlite


class TrackRepository:
    """Repository for track operations."""

    def __init__(self, db_path: Path) -> None:
        """Initialize the repository.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = db_path

    async def upsert_track(
        self,
        provider: str,
        provider_track_id: str,
        title: str,
        artist: str,
        album: str | None = None,
        isrc: str | None = None,
        artwork_url: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Upsert a track (insert or update).

        Args:
            provider: The recognition provider (e.g., 'shazam', 'acoustid').
            provider_track_id: The provider's track ID.
            title: Track title.
            artist: Track artist.
            album: Track album (optional).
            isrc: ISRC code (optional).
            artwork_url: URL to track artwork (optional).
            metadata: Additional metadata as JSON (optional).

        Returns:
            The track ID.
        """
        async with aiosqlite.connect(self.db_path) as db:
            # Check if track exists
            cursor = await db.execute(
                "SELECT id FROM tracks WHERE provider = ? AND provider_track_id = ?",
                (provider, provider_track_id),
            )
            existing = await cursor.fetchone()

            if existing:
                # Update existing track
                track_id = existing[0]
                await db.execute(
                    """
                    UPDATE tracks
                    SET title = ?, artist = ?, album = ?, isrc = ?,
                        artwork_url = ?, metadata = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """,
                    (
                        title,
                        artist,
                        album,
                        isrc,
                        artwork_url,
                        json.dumps(metadata) if metadata else None,
                        track_id,
                    ),
                )
                await db.commit()
                return int(track_id)
            else:
                # Insert new track
                cursor = await db.execute(
                    """
                    INSERT INTO tracks (
                        provider, provider_track_id, title, artist, album,
                        isrc, artwork_url, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        provider,
                        provider_track_id,
                        title,
                        artist,
                        album,
                        isrc,
                        artwork_url,
                        json.dumps(metadata) if metadata else None,
                    ),
                )
                await db.commit()
                if cursor.lastrowid is None:
                    raise RuntimeError("Failed to insert track - no ID returned")
                return cursor.lastrowid

    async def get_track_by_provider_id(
        self, provider: str, provider_track_id: str
    ) -> dict[str, Any] | None:
        """Get a track by provider and provider track ID.

        Args:
            provider: The recognition provider.
            provider_track_id: The provider's track ID.

        Returns:
            Track data as dictionary or None if not found.
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM tracks WHERE provider = ? AND provider_track_id = ?
            """,
                (provider, provider_track_id),
            )
            row = await cursor.fetchone()

            if row:
                return dict(row)
            return None

    async def get_track_by_id(self, track_id: int) -> dict[str, Any] | None:
        """Get a track by ID.

        Args:
            track_id: The track ID.

        Returns:
            Track data as dictionary or None if not found.
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM tracks WHERE id = ?", (track_id,))
            row = await cursor.fetchone()

            if row:
                return dict(row)
            return None


class PlayRepository:
    """Repository for play operations."""

    def __init__(self, db_path: Path) -> None:
        """Initialize the repository.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = db_path

    async def insert_play(
        self,
        track_id: int,
        stream_id: int,
        recognized_at_utc: datetime,
        dedup_bucket: int,
        confidence: float | None = None,
    ) -> int:
        """Insert a play record.

        Args:
            track_id: The track ID.
            stream_id: The stream ID.
            recognized_at_utc: When the track was recognized.
            dedup_bucket: Deduplication bucket (timestamp / dedup_seconds).
            confidence: Recognition confidence (optional).

        Returns:
            The play ID.

        Raises:
            Exception: If duplicate play violates unique constraint.
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO plays (
                    track_id, stream_id, recognized_at_utc, dedup_bucket, confidence
                ) VALUES (?, ?, ?, ?, ?)
            """,
                (
                    track_id,
                    stream_id,
                    recognized_at_utc.isoformat(),
                    dedup_bucket,
                    confidence,
                ),
            )
            await db.commit()
            if cursor.lastrowid is None:
                raise RuntimeError("Failed to insert play - no ID returned")
            return cursor.lastrowid

    async def get_plays_by_date(
        self, target_date: date, stream_name: str | None = None
    ) -> list[dict[str, Any]]:
        """Get plays for a specific date.

        Args:
            target_date: The date to get plays for.
            stream_name: Optional stream name filter.

        Returns:
            List of play records with track and stream information.
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            if stream_name:
                # Filter by specific stream
                cursor = await db.execute(
                    """
                    SELECT p.*, t.title, t.artist, t.album, t.artwork_url, s.name as stream_name
                    FROM plays p
                    JOIN tracks t ON p.track_id = t.id
                    JOIN streams s ON p.stream_id = s.id
                    WHERE DATE(p.recognized_at_utc) = ? AND s.name = ?
                    ORDER BY p.recognized_at_utc DESC
                """,
                    (target_date.isoformat(), stream_name),
                )
            else:
                # Get all streams
                cursor = await db.execute(
                    """
                    SELECT p.*, t.title, t.artist, t.album, t.artwork_url, s.name as stream_name
                    FROM plays p
                    JOIN tracks t ON p.track_id = t.id
                    JOIN streams s ON p.stream_id = s.id
                    WHERE DATE(p.recognized_at_utc) = ?
                    ORDER BY p.recognized_at_utc DESC
                """,
                    (target_date.isoformat(),),
                )

            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


class RecognitionRepository:
    """Repository for recognition operations."""

    def __init__(self, db_path: Path) -> None:
        """Initialize the repository.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = db_path

    async def _get_stream_id(self, stream_name: str) -> int:
        """Get stream ID by name, creating if it doesn't exist.

        Args:
            stream_name: Name of the stream.

        Returns:
            Stream ID.
        """
        async with aiosqlite.connect(self.db_path) as db:
            # Try to find existing stream
            cursor = await db.execute(
                "SELECT id FROM streams WHERE name = ?", (stream_name,)
            )
            row = await cursor.fetchone()

            if row:
                return int(row[0])

            # Create new stream
            cursor = await db.execute(
                "INSERT INTO streams (name, url, enabled) VALUES (?, ?, ?)",
                (stream_name, f"rtsp://placeholder/{stream_name}", True),
            )
            await db.commit()
            if cursor.lastrowid is None:
                raise RuntimeError("Failed to insert stream - no ID returned")
            return cursor.lastrowid

    async def insert_recognition(
        self,
        stream_id: int,
        provider: str,
        recognized_at_utc: datetime,
        window_start_utc: datetime,
        window_end_utc: datetime,
        track_id: int | None = None,
        confidence: float | None = None,
        latency_ms: int | None = None,
        raw_response: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> int:
        """Insert a recognition record.

        Args:
            stream_id: The stream ID.
            provider: The recognition provider.
            recognized_at_utc: When the recognition was completed.
            window_start_utc: Start of the audio window.
            window_end_utc: End of the audio window.
            track_id: The recognized track ID (optional).
            confidence: Recognition confidence (optional).
            latency_ms: Recognition latency in milliseconds (optional).
            raw_response: Raw provider response (optional).
            error_message: Error message if recognition failed (optional).

        Returns:
            The recognition ID.
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO recognitions (
                    stream_id, provider, recognized_at_utc, window_start_utc,
                    window_end_utc, track_id, confidence, latency_ms,
                    raw_response, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    stream_id,
                    provider,
                    recognized_at_utc.isoformat(),
                    window_start_utc.isoformat(),
                    window_end_utc.isoformat(),
                    track_id,
                    confidence,
                    latency_ms,
                    json.dumps(raw_response) if raw_response else None,
                    error_message,
                ),
            )
            await db.commit()
            if cursor.lastrowid is None:
                raise RuntimeError("Failed to insert recognition - no ID returned")
            return cursor.lastrowid

    async def insert_recognition_by_name(
        self,
        stream_name: str,
        provider: str,
        provider_track_id: str,
        title: str,
        artist: str,
        album: str | None = None,
        isrc: str | None = None,
        artwork_url: str | None = None,
        confidence: float | None = None,
        recognized_at_utc: datetime | None = None,
        raw_response: dict[str, Any] | None = None,
    ) -> int:
        """Insert a recognition record using stream name.

        Args:
            stream_name: Name of the stream.
            provider: The recognition provider.
            provider_track_id: The provider-specific track ID.
            title: Track title.
            artist: Track artist.
            album: Optional album name.
            isrc: Optional ISRC code.
            artwork_url: Optional artwork URL.
            confidence: Optional confidence score.
            recognized_at_utc: When the recognition was completed (defaults to now).
            raw_response: Optional raw provider response.

        Returns:
            The ID of the inserted recognition record.
        """
        if recognized_at_utc is None:
            recognized_at_utc = datetime.now(UTC)

        # Get stream ID
        stream_id = await self._get_stream_id(stream_name)

        # Use a simplified insert - just the essential data for diagnostics
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO recognitions (
                    stream_id, provider, recognized_at_utc, window_start_utc,
                    window_end_utc, track_id, confidence, latency_ms,
                    raw_response, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    stream_id,
                    provider,
                    recognized_at_utc.isoformat(),
                    recognized_at_utc.isoformat(),  # Use same time for window start
                    recognized_at_utc.isoformat(),  # Use same time for window end
                    None,  # track_id - we don't have it in this simplified call
                    confidence,
                    None,  # latency_ms - we could calculate this later
                    json.dumps(raw_response) if raw_response else None,
                    None,  # error_message
                ),
            )
            await db.commit()
            if cursor.lastrowid is None:
                raise RuntimeError("Failed to insert recognition - no ID returned")
            return cursor.lastrowid

    async def get_recent_recognitions(
        self,
        limit: int = 100,
        stream_name: str | None = None,
        provider: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get recent recognition records.

        Args:
            limit: Maximum number of records to return.
            stream_name: Optional stream name filter.
            provider: Optional provider filter.

        Returns:
            List of recognition records ordered by recognized_at_utc DESC.
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            # Build query with optional filters
            query = """
                SELECT r.*, s.name as stream_name, t.title, t.artist
                FROM recognitions r
                JOIN streams s ON r.stream_id = s.id
                LEFT JOIN tracks t ON r.track_id = t.id
                WHERE 1=1
            """
            params: list[str | int] = []

            if stream_name:
                query += " AND s.name = ?"
                params.append(stream_name)

            if provider:
                query += " AND r.provider = ?"
                params.append(provider)

            query += " ORDER BY r.recognized_at_utc DESC LIMIT ?"
            params.append(limit)

            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
