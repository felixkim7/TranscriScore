"""Standalone smoke test for classification_service (stem role classification)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.settings import SAMPLES_DIR
from app.services.classification_service import classify_stem


def main() -> None:
    candidates = sorted(
        p for p in SAMPLES_DIR.glob("*") if p.suffix.lower() in (".mp3", ".wav", ".flac", ".m4a")
    )
    if not candidates:
        raise SystemExit(f"No audio files found in {SAMPLES_DIR}")

    audio_path = candidates[0]
    print(f"Classifying: {audio_path}")

    label = classify_stem(str(audio_path))

    print(f"Predicted stem label: {label}")


if __name__ == "__main__":
    main()
