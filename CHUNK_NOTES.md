# Ying RTSP Music Tagger - Implementation Progress

## Completed Milestones

### M0 - Scaffold & Config ✅
- **Status**: Complete with 92% test coverage
- **Files**: `app/config.py`, `tests/unit/test_config.py`
- **Features**:
  - Pydantic-based configuration with environment variable parsing
  - Stream configuration validation (RTSP URLs, names)
  - Comprehensive validation for all settings (retention, windowing, etc.)
  - Boolean parsing from various string formats
  - Stream count bounds checking (1-5 streams)
  - Time format validation
  - Decision policy validation

### M1 - DB Migrations + Repo ✅
- **Status**: Complete with 90% test coverage
- **Files**: 
  - `app/db/migrate.py`, `tests/unit/test_db_migrate.py`
  - `app/db/repo.py`, `tests/unit/test_db_repo.py`
  - `app/db/migrations/0001_init.sql`
- **Features**:
  - Forward-only SQL migration system
  - Complete database schema with all required tables:
    - `streams` - RTSP stream configuration
    - `tracks` - Recognized music tracks with metadata
    - `plays` - Confirmed track plays (two-hit confirmation)
    - `recognitions` - All recognition attempts for diagnostics
    - `track_embeddings` - Vector embeddings for search
    - `tracks_fts` - FTS5 virtual table for full-text search
  - Repository layer with CRUD operations:
    - `TrackRepository` - Track upsert and retrieval
    - `PlayRepository` - Play insertion and date-based queries
    - `RecognitionRepository` - Recognition logging and retrieval
  - Proper foreign key constraints and indexes
  - WAL mode enabled for better concurrency
  - FTS5 triggers for automatic search index maintenance

## Project Structure
```
ying/
├── app/
│   ├── __init__.py
│   ├── config.py              # Environment configuration
│   └── db/
│       ├── __init__.py
│       ├── migrate.py         # Migration management
│       ├── repo.py            # Database repositories
│       └── migrations/
│           ├── __init__.py
│           └── 0001_init.sql  # Initial schema
├── tests/
│   └── unit/
│       ├── test_config.py     # Configuration tests
│       ├── test_db_migrate.py # Migration tests
│       └── test_db_repo.py    # Repository tests
├── pyproject.toml             # Project configuration
├── README.md                  # Project documentation
└── CHUNK_NOTES.md            # This file
```

## Next Milestones

### M2 - Metrics, Logging, Tracing
- Prometheus metrics setup
- Structured JSON logging
- OpenTelemetry tracing configuration

### M3 - FFmpeg Runner
- Async FFmpeg process management
- RTSP stream ingestion
- Audio window extraction

### M4 - Scheduler + Two-Hit
- Windowing logic
- Two-hit confirmation policy
- Deduplication

## Development Commands
```bash
# Run tests
rye run test

# Run specific test files
rye run test tests/unit/test_config.py -v

# Run migrations
rye run migrate

# Development server
rye run dev
```

## Test Coverage
- **Total Coverage**: 90.27%
- **Config Module**: 92% (9 lines uncovered)
- **Migration Module**: 82% (12 lines uncovered)
- **Repository Module**: 95% (4 lines uncovered)

All tests pass and follow TDD principles with comprehensive validation.
