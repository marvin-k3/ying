# Ying - RTSP Music Tagger

Like the Dr. Seuss character in One Fish Two Fish, Ying listens to multiple RTSP streams and identifies music playing in the background.

## Features

- **Multi-stream ingestion**: Monitor up to 5 RTSP streams simultaneously
- **Music recognition**: Uses Shazam and AcoustID to identify tracks
- **Smart deduplication**: Two-hit confirmation policy to avoid false positives
- **Web interface**: Day view, search, diagnostics, and clustering
- **Observability**: Prometheus metrics and structured logging
- **Hot reload**: Configuration changes without restart

## Quick Start

```bash
# Install dependencies
rye sync

# Run tests
rye run test

# Start development server
rye run dev
```

## Configuration

Set environment variables to configure streams and behavior:

```bash
export STREAM_COUNT=2
export STREAM_1_NAME=living_room
export STREAM_1_URL=rtsp://user:pass@192.168.1.100:554/stream1
export STREAM_1_ENABLED=true
export STREAM_2_NAME=yard
export STREAM_2_URL=rtsp://user:pass@192.168.1.101:554/stream2
export STREAM_2_ENABLED=true
export ACOUSTID_API_KEY=your_key_here
```

## Development

This project follows TDD principles with comprehensive test coverage. See `PLAN.md` for the full implementation roadmap.
