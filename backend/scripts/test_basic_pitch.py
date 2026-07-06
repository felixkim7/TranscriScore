"""Standalone smoke test for transcription_service (Spotify Basic Pitch).

Usage:
    python scripts/test_basic_pitch.py                       # first file found in samples/
    python scripts/test_basic_pitch.py --file ../samples/sample2.mp3
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.settings import SAMPLES_DIR
from app.services.transcription_service import run


def pick_default_file() -> Path:
    candidates = sorted(
        p for p in SAMPLES_DIR.glob("*") if p.suffix.lower() in (".mp3", ".wav", ".flac", ".m4a")
    )
    if not candidates:
        raise SystemExit(f"No audio files found in {SAMPLES_DIR}")
    return candidates[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", help="Path to an audio file (defaults to first file in samples/)")
    args = parser.parse_args()

    audio_path = Path(args.file) if args.file else pick_default_file()
    print(f"Transcribing: {audio_path}")

    note_events = run(str(audio_path))

    print(f"Note events: {len(note_events)}")
    for note in note_events[:10]:
        print(note)


if __name__ == "__main__":
    main()
