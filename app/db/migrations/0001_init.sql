
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
        