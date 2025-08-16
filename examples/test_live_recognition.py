#!/usr/bin/env python3
"""Example script demonstrating live music recognition.

This script shows how to use the recognizers with real audio files.
"""

import asyncio
import sys
from pathlib import Path

# Add the parent directory to the path so we can import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.recognizers.acoustid_recognizer import AcoustIDRecognizer
from app.recognizers.shazamio_recognizer import ShazamioRecognizer


async def recognize_audio_file(audio_path: Path):
    """Recognize audio using both Shazam and AcoustID."""

    if not audio_path.exists():
        print(f"❌ Audio file not found: {audio_path}")
        return

    # Read audio data
    audio_data = audio_path.read_bytes()
    print(f"🎵 Recognizing audio: {audio_path.name} ({len(audio_data)} bytes)")

    # Setup recognizers
    shazam = ShazamioRecognizer(timeout_seconds=30.0)

    # AcoustID requires API key
    import os

    acoustid_key = os.getenv("ACOUSTID_API_KEY")
    acoustid = None
    if acoustid_key:
        acoustid = AcoustIDRecognizer(api_key=acoustid_key, timeout_seconds=30.0)
    else:
        print("⚠️  ACOUSTID_API_KEY not set - skipping AcoustID recognition")

    try:
        # Run recognizers in parallel
        tasks = [shazam.recognize(audio_data)]
        if acoustid:
            tasks.append(acoustid.recognize(audio_data))

        print("🔍 Running recognition...")
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        providers = ["Shazam"] + (["AcoustID"] if acoustid else [])

        for i, (provider, result) in enumerate(zip(providers, results, strict=False)):
            print(f"\n{'=' * 20} {provider} Results {'=' * 20}")

            if isinstance(result, Exception):
                print(f"❌ {provider} failed with exception: {result}")
                continue

            if result.is_success:
                print(f"✅ {provider} recognized:")
                print(f"   Title: {result.title}")
                print(f"   Artist: {result.artist}")
                if result.album:
                    print(f"   Album: {result.album}")
                if result.confidence is not None:
                    print(f"   Confidence: {result.confidence:.2f}")
                if result.isrc:
                    print(f"   ISRC: {result.isrc}")
                print(f"   Track ID: {result.provider_track_id}")

            elif result.is_no_match:
                print(f"🔍 {provider} found no match")

            else:
                print(f"❌ {provider} error: {result.error_message}")

    finally:
        # Cleanup
        if acoustid:
            await acoustid.close()


async def main():
    """Main function."""
    print("🎵 Live Music Recognition Demo")
    print("=" * 40)

    # Try to find the best available audio file
    test_data_dir = Path(__file__).parent.parent / "tests" / "data"

    if len(sys.argv) > 1:
        audio_path = Path(sys.argv[1])
    else:
        # Look for real music files first, then fallback
        audio_candidates = [
            test_data_dir / "william_tell_gallop.wav",  # Real classical music (WAV)
            test_data_dir / "william_tell_gallop.ogg",  # Real classical music (OGG)
            test_data_dir / "sample.wav",  # Synthetic audio fallback
        ]

        audio_path = None
        for candidate in audio_candidates:
            if candidate.exists():
                audio_path = candidate
                break

        if not audio_path:
            print("❌ No audio files found in tests/data/")
            return

        print(f"Using audio file: {audio_path.name}")

    await recognize_audio_file(audio_path)

    print("\n" + "=" * 40)
    print("✅ Recognition complete!")


if __name__ == "__main__":
    print(
        "Note: Set ACOUSTID_API_KEY environment variable to enable AcoustID recognition"
    )
    print("Usage: python examples/test_live_recognition.py [audio_file.wav]")
    print()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)
