"""Tests for app.db.repo module."""

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiosqlite
import pytest

from app.db.migrate import MigrationManager
from app.db.repo import PlayRepository, RecognitionRepository, TrackRepository


def ensure_migration_files() -> None:
    """Ensure migration files exist for testing."""
    migrations_dir = Path(__file__).parent.parent.parent / "app" / "db" / "migrations"
    migrations_dir.mkdir(parents=True, exist_ok=True)

    # Ensure the migration file exists
    migration_file = migrations_dir / "0001_init.sql"
    if not migration_file.exists():
        migration_file.write_text("""
            -- Initial database schema for ying RTSP music tagger
            -- Migration: 0001_init

            -- Enable WAL mode for better concurrency
            PRAGMA journal_mode = WAL;

            -- Streams table - stores RTSP stream configuration
            CREATE TABLE streams (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                url TEXT NOT NULL,
                enabled BOOLEAN NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- Tracks table - stores recognized music tracks
            CREATE TABLE tracks (
                id INTEGER PRIMARY KEY,
                provider TEXT NOT NULL,  -- 'shazam', 'acoustid'
                provider_track_id TEXT NOT NULL,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                album TEXT,
                isrc TEXT,
                artwork_url TEXT,
                metadata JSON,  -- Store additional provider-specific metadata
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(provider, provider_track_id)
            );

            -- Plays table - stores confirmed track plays (after two-hit confirmation)
            CREATE TABLE plays (
                id INTEGER PRIMARY KEY,
                track_id INTEGER NOT NULL,
                stream_id INTEGER NOT NULL,
                recognized_at_utc TIMESTAMP NOT NULL,
                dedup_bucket INTEGER NOT NULL,  -- recognized_at_utc / dedup_seconds
                confidence REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE,
                FOREIGN KEY (stream_id) REFERENCES streams(id) ON DELETE CASCADE,
                UNIQUE(track_id, stream_id, dedup_bucket)
            );

            -- Recognitions table - stores all recognition attempts for diagnostics
            CREATE TABLE recognitions (
                id INTEGER PRIMARY KEY,
                stream_id INTEGER NOT NULL,
                provider TEXT NOT NULL,  -- 'shazam', 'acoustid'
                recognized_at_utc TIMESTAMP NOT NULL,
                window_start_utc TIMESTAMP NOT NULL,
                window_end_utc TIMESTAMP NOT NULL,
                track_id INTEGER,  -- NULL if no match found
                confidence REAL,
                latency_ms INTEGER,  -- Recognition latency in milliseconds
                raw_response JSON,  -- Store complete provider response
                error_message TEXT,  -- NULL if successful
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (stream_id) REFERENCES streams(id) ON DELETE CASCADE,
                FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE SET NULL
            );

            -- Track embeddings table - stores vector embeddings for search
            CREATE TABLE track_embeddings (
                track_id INTEGER PRIMARY KEY,
                provider TEXT NOT NULL,
                dimension INTEGER NOT NULL,
                vector BLOB NOT NULL,  -- Serialized numpy array
                updated_at_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
            );

            -- FTS5 virtual table for full-text search
            CREATE VIRTUAL TABLE tracks_fts USING fts5(
                title,
                artist,
                content='tracks',
                content_rowid='id'
            );

            -- Triggers to keep FTS table in sync
            CREATE TRIGGER tracks_ai AFTER INSERT ON tracks BEGIN
                INSERT INTO tracks_fts(rowid, title, artist) VALUES (new.id, new.title, new.artist);
            END;

            CREATE TRIGGER tracks_ad AFTER DELETE ON tracks BEGIN
                INSERT INTO tracks_fts(tracks_fts, rowid, title, artist) VALUES('delete', old.id, old.title, old.artist);
            END;

            CREATE TRIGGER tracks_au AFTER UPDATE ON tracks BEGIN
                INSERT INTO tracks_fts(tracks_fts, rowid, title, artist) VALUES('delete', old.id, old.title, old.artist);
                INSERT INTO tracks_fts(rowid, title, artist) VALUES (new.id, new.title, new.artist);
            END;

            -- Indexes for performance
            CREATE INDEX idx_plays_recognized_at ON plays(recognized_at_utc);
            CREATE INDEX idx_plays_stream_dedup ON plays(stream_id, dedup_bucket);
            CREATE INDEX idx_plays_track_time ON plays(track_id, recognized_at_utc);

            CREATE INDEX idx_recognitions_stream_time ON recognitions(stream_id, recognized_at_utc);
            CREATE INDEX idx_recognitions_provider_time ON recognitions(provider, recognized_at_utc);
            CREATE INDEX idx_recognitions_track_time ON recognitions(track_id, recognized_at_utc);

            CREATE INDEX idx_tracks_provider_id ON tracks(provider, provider_track_id);
            CREATE INDEX idx_tracks_created_at ON tracks(created_at);

            CREATE INDEX idx_streams_name ON streams(name);
            CREATE INDEX idx_streams_enabled ON streams(enabled);

            -- Insert default streams (will be overridden by config)
            INSERT OR IGNORE INTO streams (id, name, url, enabled) VALUES
                (1, 'stream_1', 'rtsp://localhost/stream1', 0),
                (2, 'stream_2', 'rtsp://localhost/stream2', 0),
                (3, 'stream_3', 'rtsp://localhost/stream3', 0),
                (4, 'stream_4', 'rtsp://localhost/stream4', 0),
                (5, 'stream_5', 'rtsp://localhost/stream5', 0);
        """)


class TestTrackRepository:
    """Test TrackRepository functionality."""

    @pytest.fixture
    async def temp_db_path(self) -> Path:
        """Create a temporary database path."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
            yield db_path
            if db_path.exists():
                db_path.unlink()

    @pytest.fixture
    async def repo(self, temp_db_path: Path) -> TrackRepository:
        """Create a TrackRepository instance with initialized database."""
        ensure_migration_files()

        # Initialize database with migrations
        manager = MigrationManager(temp_db_path)
        await manager.migrate_all()

        repo = TrackRepository(temp_db_path)
        yield repo

    async def test_upsert_track_new(self, repo: TrackRepository) -> None:
        """Test upserting a new track."""
        track_data = {
            "provider": "shazam",
            "provider_track_id": "12345",
            "title": "Test Song",
            "artist": "Test Artist",
            "album": "Test Album",
            "isrc": "USRC12345678",
            "artwork_url": "https://example.com/artwork.jpg",
            "metadata": {"key": "value"},
        }

        track_id = await repo.upsert_track(**track_data)
        assert track_id > 0

        # Verify track was inserted
        async with aiosqlite.connect(repo.db_path) as db:
            cursor = await db.execute(
                "SELECT id, provider, provider_track_id, title, artist FROM tracks WHERE id = ?",
                (track_id,),
            )
            row = await cursor.fetchone()
            assert row is not None
            assert row[1] == "shazam"  # provider
            assert row[2] == "12345"  # provider_track_id
            assert row[3] == "Test Song"  # title
            assert row[4] == "Test Artist"  # artist

    async def test_upsert_track_existing(self, repo: TrackRepository) -> None:
        """Test upserting an existing track updates it."""
        # Insert initial track
        track_data = {
            "provider": "shazam",
            "provider_track_id": "12345",
            "title": "Original Title",
            "artist": "Original Artist",
            "album": "Original Album",
        }

        track_id1 = await repo.upsert_track(**track_data)

        # Update track with new data
        updated_data = {
            "provider": "shazam",
            "provider_track_id": "12345",
            "title": "Updated Title",
            "artist": "Updated Artist",
            "album": "Updated Album",
            "artwork_url": "https://example.com/new-artwork.jpg",
        }

        track_id2 = await repo.upsert_track(**updated_data)

        # Should return same ID
        assert track_id1 == track_id2

        # Verify track was updated
        async with aiosqlite.connect(repo.db_path) as db:
            cursor = await db.execute(
                "SELECT title, artist, album, artwork_url FROM tracks WHERE id = ?",
                (track_id1,),
            )
            row = await cursor.fetchone()
            assert row is not None
            assert row[0] == "Updated Title"
            assert row[1] == "Updated Artist"
            assert row[2] == "Updated Album"
            assert row[3] == "https://example.com/new-artwork.jpg"

    async def test_get_track_by_provider_id(self, repo: TrackRepository) -> None:
        """Test getting track by provider and provider_track_id."""
        # Insert a track
        track_data = {
            "provider": "shazam",
            "provider_track_id": "12345",
            "title": "Test Song",
            "artist": "Test Artist",
        }

        track_id = await repo.upsert_track(**track_data)

        # Get track
        track = await repo.get_track_by_provider_id("shazam", "12345")
        assert track is not None
        assert track["id"] == track_id
        assert track["title"] == "Test Song"
        assert track["artist"] == "Test Artist"

        # Test non-existent track
        track = await repo.get_track_by_provider_id("shazam", "nonexistent")
        assert track is None

    async def test_get_track_by_id(self, repo: TrackRepository) -> None:
        """Test getting track by ID."""
        # Insert a track
        track_data = {
            "provider": "shazam",
            "provider_track_id": "12345",
            "title": "Test Song",
            "artist": "Test Artist",
        }

        track_id = await repo.upsert_track(**track_data)

        # Get track
        track = await repo.get_track_by_id(track_id)
        assert track is not None
        assert track["id"] == track_id
        assert track["title"] == "Test Song"
        assert track["artist"] == "Test Artist"

        # Test non-existent track
        track = await repo.get_track_by_id(99999)
        assert track is None


class TestPlayRepository:
    """Test PlayRepository functionality."""

    @pytest.fixture
    async def temp_db_path(self) -> Path:
        """Create a temporary database path."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
            yield db_path
            if db_path.exists():
                db_path.unlink()

    @pytest.fixture
    async def repo(self, temp_db_path: Path) -> PlayRepository:
        """Create a PlayRepository instance with initialized database."""
        # Initialize database with migrations
        manager = MigrationManager(temp_db_path)
        await manager.migrate_all()

        repo = PlayRepository(temp_db_path)
        yield repo

    @pytest.fixture
    async def sample_track_id(self, repo: PlayRepository) -> int:
        """Create a sample track and return its ID."""
        async with aiosqlite.connect(repo.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO tracks (provider, provider_track_id, title, artist)
                VALUES (?, ?, ?, ?)
            """,
                ("shazam", "12345", "Test Song", "Test Artist"),
            )
            await db.commit()
            return cursor.lastrowid

    @pytest.fixture
    async def sample_stream_id(self, repo: PlayRepository) -> int:
        """Create a sample stream and return its ID."""
        async with aiosqlite.connect(repo.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO streams (name, url, enabled)
                VALUES (?, ?, ?)
            """,
                ("test_stream", "rtsp://test", 1),
            )
            await db.commit()
            return cursor.lastrowid

    async def test_insert_play_success(
        self, repo: PlayRepository, sample_track_id: int, sample_stream_id: int
    ) -> None:
        """Test successfully inserting a play."""
        recognized_at = datetime.now(UTC)
        dedup_bucket = int(recognized_at.timestamp()) // 300  # 5 minute buckets

        play_id = await repo.insert_play(
            track_id=sample_track_id,
            stream_id=sample_stream_id,
            recognized_at_utc=recognized_at,
            dedup_bucket=dedup_bucket,
            confidence=0.95,
        )

        assert play_id > 0

        # Verify play was inserted
        async with aiosqlite.connect(repo.db_path) as db:
            cursor = await db.execute("SELECT * FROM plays WHERE id = ?", (play_id,))
            row = await cursor.fetchone()
            assert row is not None
            assert row[1] == sample_track_id  # track_id
            assert row[2] == sample_stream_id  # stream_id
            assert row[5] == 0.95  # confidence

    async def test_insert_play_duplicate_fails(
        self, repo: PlayRepository, sample_track_id: int, sample_stream_id: int
    ) -> None:
        """Test that inserting duplicate play fails due to unique constraint."""
        recognized_at = datetime.now(UTC)
        dedup_bucket = int(recognized_at.timestamp()) // 300

        # Insert first play
        await repo.insert_play(
            track_id=sample_track_id,
            stream_id=sample_stream_id,
            recognized_at_utc=recognized_at,
            dedup_bucket=dedup_bucket,
            confidence=0.95,
        )

        # Try to insert duplicate
        with pytest.raises(
            (ValueError, RuntimeError, Exception)
        ):  # Should raise due to unique constraint
            await repo.insert_play(
                track_id=sample_track_id,
                stream_id=sample_stream_id,
                recognized_at_utc=recognized_at,
                dedup_bucket=dedup_bucket,
                confidence=0.90,
            )

    async def test_get_plays_by_date(
        self, repo: PlayRepository, sample_track_id: int, sample_stream_id: int
    ) -> None:
        """Test getting plays for a specific date."""
        # Insert plays for different dates
        base_time = datetime.now(UTC).replace(
            hour=12, minute=0, second=0, microsecond=0
        )

        # Play 1: today
        play1_time = base_time
        dedup1 = int(play1_time.timestamp()) // 300
        await repo.insert_play(
            sample_track_id, sample_stream_id, play1_time, dedup1, 0.95
        )

        # Play 2: yesterday
        play2_time = base_time.replace(day=base_time.day - 1)
        dedup2 = int(play2_time.timestamp()) // 300
        await repo.insert_play(
            sample_track_id, sample_stream_id, play2_time, dedup2, 0.90
        )

        # Get plays for today
        today_plays = await repo.get_plays_by_date(base_time.date())
        assert len(today_plays) == 1
        assert today_plays[0]["track_id"] == sample_track_id
        assert today_plays[0]["confidence"] == 0.95

        # Get plays for yesterday
        yesterday_plays = await repo.get_plays_by_date(
            (base_time.replace(day=base_time.day - 1)).date()
        )
        assert len(yesterday_plays) == 1
        assert yesterday_plays[0]["track_id"] == sample_track_id
        assert yesterday_plays[0]["confidence"] == 0.90

    async def test_get_plays_by_date_with_stream_filter(
        self, repo: PlayRepository, sample_track_id: int, sample_stream_id: int
    ) -> None:
        """Test getting plays for a specific date with stream filter."""
        # Create second stream
        async with aiosqlite.connect(repo.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO streams (name, url, enabled)
                VALUES (?, ?, ?)
            """,
                ("test_stream_2", "rtsp://test2", 1),
            )
            await db.commit()
            stream2_id = cursor.lastrowid

        base_time = datetime.now(UTC).replace(
            hour=12, minute=0, second=0, microsecond=0
        )
        dedup = int(base_time.timestamp()) // 300

        # Insert plays for different streams
        await repo.insert_play(
            sample_track_id, sample_stream_id, base_time, dedup, 0.95
        )
        await repo.insert_play(sample_track_id, stream2_id, base_time, dedup, 0.90)

        # Get plays for specific stream
        stream_plays = await repo.get_plays_by_date(
            base_time.date(), stream_name="test_stream"
        )
        assert len(stream_plays) == 1
        assert stream_plays[0]["confidence"] == 0.95

        # Get plays for all streams
        all_plays = await repo.get_plays_by_date(base_time.date())
        assert len(all_plays) == 2


class TestRecognitionRepository:
    """Test RecognitionRepository functionality."""

    @pytest.fixture
    async def temp_db_path(self) -> Path:
        """Create a temporary database path."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
            yield db_path
            if db_path.exists():
                db_path.unlink()

    @pytest.fixture
    async def repo(self, temp_db_path: Path) -> RecognitionRepository:
        """Create a RecognitionRepository instance with initialized database."""
        # Initialize database with migrations
        manager = MigrationManager(temp_db_path)
        await manager.migrate_all()

        repo = RecognitionRepository(temp_db_path)
        yield repo

    @pytest.fixture
    async def sample_stream_id(self, repo: RecognitionRepository) -> int:
        """Create a sample stream and return its ID."""
        async with aiosqlite.connect(repo.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO streams (name, url, enabled)
                VALUES (?, ?, ?)
            """,
                ("test_stream", "rtsp://test", 1),
            )
            await db.commit()
            return cursor.lastrowid

    async def test_insert_recognition_success(
        self, repo: RecognitionRepository, sample_stream_id: int
    ) -> None:
        """Test successfully inserting a recognition."""
        recognized_at = datetime.now(UTC)
        window_start = recognized_at - timedelta(seconds=12)
        window_end = recognized_at

        rec_id = await repo.insert_recognition(
            stream_id=sample_stream_id,
            provider="shazam",
            recognized_at_utc=recognized_at,
            window_start_utc=window_start,
            window_end_utc=window_end,
            track_id=None,  # No match
            confidence=None,
            latency_ms=1500,
            raw_response={"status": "no_match"},
            error_message=None,
        )

        assert rec_id > 0

        # Verify recognition was inserted
        async with aiosqlite.connect(repo.db_path) as db:
            cursor = await db.execute(
                "SELECT id, provider, stream_id, latency_ms FROM recognitions WHERE id = ?",
                (rec_id,),
            )
            row = await cursor.fetchone()
            assert row is not None
            assert row[1] == "shazam"  # provider
            assert row[2] == sample_stream_id  # stream_id
            assert row[3] == 1500  # latency_ms

    async def test_insert_recognition_with_track(
        self, repo: RecognitionRepository, sample_stream_id: int
    ) -> None:
        """Test inserting a recognition with a matched track."""
        # Create a track first
        async with aiosqlite.connect(repo.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO tracks (provider, provider_track_id, title, artist)
                VALUES (?, ?, ?, ?)
            """,
                ("shazam", "12345", "Test Song", "Test Artist"),
            )
            await db.commit()
            track_id = cursor.lastrowid

        recognized_at = datetime.now(UTC)
        window_start = recognized_at - timedelta(seconds=12)
        window_end = recognized_at

        rec_id = await repo.insert_recognition(
            stream_id=sample_stream_id,
            provider="shazam",
            recognized_at_utc=recognized_at,
            window_start_utc=window_start,
            window_end_utc=window_end,
            track_id=track_id,
            confidence=0.95,
            latency_ms=1200,
            raw_response={"track": {"title": "Test Song"}},
            error_message=None,
        )

        assert rec_id > 0

        # Verify recognition was inserted with track
        async with aiosqlite.connect(repo.db_path) as db:
            cursor = await db.execute(
                "SELECT track_id, confidence FROM recognitions WHERE id = ?", (rec_id,)
            )
            row = await cursor.fetchone()
            assert row is not None
            assert row[0] == track_id
            assert row[1] == 0.95

    async def test_get_recent_recognitions(
        self, repo: RecognitionRepository, sample_stream_id: int
    ) -> None:
        """Test getting recent recognitions."""
        # Insert multiple recognitions
        base_time = datetime.now(UTC)

        for i in range(5):
            rec_time = base_time - timedelta(minutes=i)
            window_start = rec_time - timedelta(seconds=12)
            window_end = rec_time

            await repo.insert_recognition(
                stream_id=sample_stream_id,
                provider="shazam",
                recognized_at_utc=rec_time,
                window_start_utc=window_start,
                window_end_utc=window_end,
                track_id=None,
                confidence=None,
                latency_ms=1000 + i,
                raw_response={"test": i},
                error_message=None,
            )

        # Get recent recognitions (default limit is 100)
        recent = await repo.get_recent_recognitions()
        assert len(recent) == 5

        # Get recent recognitions with limit
        recent = await repo.get_recent_recognitions(limit=3)
        assert len(recent) == 3

        # Verify they're ordered by recognized_at_utc DESC
        assert recent[0]["recognized_at_utc"] > recent[1]["recognized_at_utc"]
        assert recent[1]["recognized_at_utc"] > recent[2]["recognized_at_utc"]
