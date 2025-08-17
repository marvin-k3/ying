"""Integration tests for ying RTSP Music Tagger.

These tests require real network access and may use live APIs.
They are disabled by default to keep regular test runs fast.

To run integration tests:
    YING_ENABLE_LIVE_TESTS=1 rye run test tests/integration/

AcoustID support has been removed - only Shazam is supported
"""
