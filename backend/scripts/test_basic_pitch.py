"""Standalone smoke test for transcription_service (Spotify Basic Pitch)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.settings import SAMPLES_DIR
from app.services.transcription_service import run


def main() -> None:
    candidates = sorted(
        p for p in SAMPLES_DIR.glob("*") if p.suffix.lower() in (".mp3", ".wav", ".flac", ".m4a")
    )
    if not candidates:
        raise SystemExit(f"No audio files found in {SAMPLES_DIR}")

    audio_path = candidates[0]
    print(f"Transcribing: {audio_path}")

    note_events = run(str(audio_path))

    print(f"Note events: {len(note_events)}")
    for note in note_events[:10]:
        print(note)


if __name__ == "__main__":
    main()
