#!/usr/bin/env python3
"""Convert OGG audio to WAV format for wider compatibility.

This script converts the william_tell_gallop.ogg to WAV format
so it can be used with AcoustID (fpcalc requires WAV input).
"""

import subprocess
import sys
from pathlib import Path


def convert_ogg_to_wav():
    """Convert OGG to WAV using ffmpeg."""
    input_file = Path(__file__).parent / "william_tell_gallop.ogg"
    output_file = Path(__file__).parent / "william_tell_gallop.wav"

    if not input_file.exists():
        print(f"❌ Input file not found: {input_file}")
        return False

    if output_file.exists():
        print(f"⚠️  Output file already exists: {output_file}")
        return True

    try:
        # Convert using ffmpeg
        cmd = [
            "ffmpeg",
            "-i",
            str(input_file),
            "-acodec",
            "pcm_s16le",  # 16-bit PCM
            "-ar",
            "44100",  # 44.1kHz sample rate
            "-ac",
            "1",  # Mono
            str(output_file),
        ]

        print(f"🔄 Converting {input_file.name} to WAV...")
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0:
            print(f"✅ Successfully converted to {output_file.name}")
            print(f"   Original: {input_file.stat().st_size:,} bytes")
            print(f"   Converted: {output_file.stat().st_size:,} bytes")
            return True
        else:
            print(f"❌ FFmpeg error: {result.stderr}")
            return False

    except FileNotFoundError:
        print("❌ ffmpeg not found. Please install ffmpeg first.")
        print("   Ubuntu/Debian: sudo apt-get install ffmpeg")
        print("   macOS: brew install ffmpeg")
        return False
    except Exception as e:
        print(f"❌ Conversion failed: {e}")
        return False


if __name__ == "__main__":
    success = convert_ogg_to_wav()
    sys.exit(0 if success else 1)
