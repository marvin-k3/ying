# Integration Tests

This document describes how to run integration tests that use live APIs.

## Overview

Integration tests validate that our recognizer implementations work correctly with real music recognition services:

- **Shazam Integration**: Tests the `ShazamioRecognizer` with the actual Shazam API
- **AcoustID Integration**: Tests the `AcoustIDRecognizer` with the actual AcoustID/MusicBrainz APIs
- **Parallel Integration**: Tests running both recognizers simultaneously

## Setup

### Prerequisites

1. **Internet connection** - Required for API calls
2. **fpcalc binary** (for AcoustID tests):
   ```bash
   # Ubuntu/Debian
   sudo apt-get install libchromaprint-tools
   
   # macOS
   brew install chromaprint
   
   # Verify installation
   fpcalc --version
   ```

3. **AcoustID API Key** (optional, for AcoustID tests):
   - Sign up at https://acoustid.org/my
   - Get your API key from the account page

### Environment Variables

- `YING_ENABLE_LIVE_TESTS=1` - **Required** to enable integration tests
- `ACOUSTID_API_KEY=your_key` - Optional, enables AcoustID tests

## Running Integration Tests

### Quick Start

```bash
# Run all integration tests (Shazam only, no AcoustID)
rye run test-integration

# Or manually:
YING_ENABLE_LIVE_TESTS=1 rye run test tests/integration/ -v -s
```

### With AcoustID Support

```bash
# Run with AcoustID API key
YING_ENABLE_LIVE_TESTS=1 ACOUSTID_API_KEY=your_api_key rye run test tests/integration/ -v -s
```

### Specific Test Categories

```bash
# Test only Shazam integration
YING_ENABLE_LIVE_TESTS=1 rye run test tests/integration/test_recognizers_live.py::TestShazamIntegration -v -s

# Test only AcoustID integration (requires API key)
YING_ENABLE_LIVE_TESTS=1 ACOUSTID_API_KEY=your_key rye run test tests/integration/test_recognizers_live.py::TestAcoustIDIntegration -v -s

# Test parallel execution
YING_ENABLE_LIVE_TESTS=1 rye run test tests/integration/test_recognizers_live.py::TestParallelIntegration -v -s
```

## Test Audio

The integration tests use real audio files when available, falling back to synthetic audio:

### Real Music Files
- `william_tell_gallop.wav` - 25-second excerpt from Rossini's William Tell Overture (public domain)
  - **Shazam recognition**: ✅ Successfully identifies as "Overture to William Tell" by Timothy Foley & United States Marine Band
  - **Perfect confidence**: 1.00 with WAV format
  - **Full metadata**: Title, Artist, Album, ISRC all populated correctly
- `william_tell_gallop.ogg` - Same audio in OGG format (fallback)

### Synthetic Audio  
- `sample.wav` - Generated C major scale melody (12 seconds)
  - Contains musical content but likely returns "no match" (expected)
  - Used as fallback when real audio files are not available
  - Generated deterministically for consistent testing

**Note**: Real classical music provides excellent test cases because:
- It's likely to be in recognition databases
- It's public domain (no copyright issues)
- It demonstrates actual recognition capabilities vs. just API connectivity

## Test Results

### Expected Outcomes

1. **Shazam Tests**:
   - ✅ API calls complete without exceptions
   - 🎵 **Successfully recognizes classical music** (William Tell Overture with 1.00 confidence)
   - 🔍 Returns "no match" for synthetic audio (this is normal)
   - ✅ **Real music test case**: Demonstrates actual recognition accuracy

2. **AcoustID Tests**:
   - ✅ Fingerprint generation succeeds (if fpcalc is installed)
   - ✅ API calls complete without exceptions
   - 🔍 Likely returns "no match" for synthetic audio (this is normal)

3. **Parallel Tests**:
   - ✅ Both services can run simultaneously
   - ✅ Results are independent (one service failure doesn't affect the other)

### Understanding Results

The integration tests focus on **API connectivity and error handling** rather than recognition accuracy:

```bash
# Example output:
✅ Shazam recognized: 'Song Title' by 'Artist Name'     # Unexpected but valid
🔍 Shazam found no match for the audio sample          # Expected for synthetic audio
❌ Shazam API error: Rate limit exceeded               # Error handling working
```

## Using Real Audio

To test with real music (for manual verification):

1. Place a real WAV file at `tests/data/sample.wav`
2. Run the integration tests
3. Check if the services recognize the music correctly

```bash
# Example with a real music file
cp /path/to/your/music.wav tests/data/sample.wav
YING_ENABLE_LIVE_TESTS=1 rye run test-integration
```

## Troubleshooting

### Tests Are Skipped

```
SKIPPED [1] ... Live API tests disabled. Set YING_ENABLE_LIVE_TESTS=1 to enable.
```

**Solution**: Set the `YING_ENABLE_LIVE_TESTS=1` environment variable.

### AcoustID Tests Fail

```
❌ Failed to generate fingerprint (fpcalc may not be installed)
```

**Solution**: Install chromaprint tools:
```bash
# Ubuntu/Debian
sudo apt-get install libchromaprint-tools

# macOS  
brew install chromaprint
```

### Network/Timeout Errors

```
❌ Recognition failed: timeout
```

**Solutions**:
- Check internet connectivity
- Try increasing timeout values in test code
- Check if APIs are experiencing outages

### Rate Limiting

```
❌ Shazam API error: Rate limit exceeded
```

**Solution**: Wait a few minutes between test runs. The APIs have rate limits.

## CI/CD Integration

For automated testing in CI/CD:

```yaml
# Example GitHub Actions
- name: Run Integration Tests
  env:
    YING_ENABLE_LIVE_TESTS: 1
    ACOUSTID_API_KEY: ${{ secrets.ACOUSTID_API_KEY }}
  run: |
    # Install chromaprint
    sudo apt-get install libchromaprint-tools
    # Run tests
    rye run test-integration
```

**Note**: Be careful with API keys in CI - use secure secret management.

## Test Development

When adding new integration tests:

1. Always use the `@pytest.mark.skipif` decorator with `YING_ENABLE_LIVE_TESTS` check
2. Handle both success and failure cases gracefully
3. Don't assume specific recognition results (use synthetic audio)
4. Include proper cleanup (close HTTP sessions, etc.)
5. Add informative print statements for manual verification

Example:
```python
@pytest.mark.skipif(
    not os.getenv("YING_ENABLE_LIVE_TESTS"),
    reason="Live API tests disabled. Set YING_ENABLE_LIVE_TESTS=1 to enable."
)
@pytest.mark.asyncio
async def test_new_integration():
    # Your test code here
    pass
```
