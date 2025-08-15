#!/usr/bin/env python3
"""Generate a sample WAV file for integration testing.

This creates a 12-second audio file with a recognizable pattern that 
might be recognized by music identification services.
"""

import wave
import math
import struct
from pathlib import Path


def generate_sample_wav(output_path: Path, duration: int = 12):
    """Generate a sample WAV file with musical content.
    
    Args:
        output_path: Where to save the WAV file.
        duration: Duration in seconds.
    """
    sample_rate = 44100
    
    # Generate a simple melody (C major scale)
    notes = [261.63, 293.66, 329.63, 349.23, 392.00, 440.00, 493.88, 523.25]  # C4 to C5
    note_duration = duration / len(notes)
    
    samples = []
    
    for i, frequency in enumerate(notes):
        # Generate samples for this note
        start_sample = int(i * note_duration * sample_rate)
        end_sample = int((i + 1) * note_duration * sample_rate)
        
        for sample_idx in range(start_sample, end_sample):
            # Create a sine wave with some harmonic content
            t = sample_idx / sample_rate
            
            # Fundamental frequency
            value = 0.5 * math.sin(2 * math.pi * frequency * t)
            # Add some harmonics for richness
            value += 0.2 * math.sin(2 * math.pi * frequency * 2 * t)  # Octave
            value += 0.1 * math.sin(2 * math.pi * frequency * 3 * t)  # Fifth
            
            # Add envelope (fade in/out)
            note_progress = (sample_idx - start_sample) / (end_sample - start_sample)
            envelope = math.sin(math.pi * note_progress) ** 0.5
            value *= envelope
            
            # Convert to 16-bit signed integer
            sample_value = int(32767 * value * 0.7)  # Scale down to avoid clipping
            samples.append(struct.pack('<h', sample_value))
    
    # Write WAV file
    with wave.open(str(output_path), 'wb') as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 2 bytes per sample (16-bit)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b''.join(samples))
    
    print(f"Generated sample WAV file: {output_path}")
    print(f"Duration: {duration} seconds")
    print(f"Sample rate: {sample_rate} Hz")
    print(f"File size: {output_path.stat().st_size} bytes")


if __name__ == "__main__":
    output_file = Path(__file__).parent / "sample.wav"
    generate_sample_wav(output_file)
