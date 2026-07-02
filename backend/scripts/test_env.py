"""Step 0 smoke test: confirm the environment can load a samples/ audio file."""

from pathlib import Path

import librosa

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"


def main() -> None:
    candidates = sorted(
        p for p in SAMPLES_DIR.glob("*") if p.suffix.lower() in (".mp3", ".wav", ".flac", ".m4a")
    )
    if not candidates:
        raise SystemExit(f"No audio files found in {SAMPLES_DIR}")

    audio_path = candidates[0]
    print(f"Loading: {audio_path}")

    y, sr = librosa.load(audio_path, sr=None)
    duration = librosa.get_duration(y=y, sr=sr)

    print(f"Sample rate: {sr} Hz")
    print(f"Samples: {len(y)}")
    print(f"Duration: {duration:.2f} s")


if __name__ == "__main__":
    main()
