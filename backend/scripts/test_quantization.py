"""Standalone smoke test for quantization_service.

Usage:
    python scripts/test_quantization.py                       # first file in samples/, re-transcribes
    python scripts/test_quantization.py --file ../samples/sample2.mp3
    python scripts/test_quantization.py --from-cache sample2   # reuse storage/intermediate/sample2.notes.json
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.settings import SAMPLES_DIR
from app.services import quantization_service, transcription_service


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
    parser.add_argument(
        "--from-cache",
        metavar="STEM_NAME",
        help="Skip transcription; load storage/intermediate/<STEM_NAME>.notes.json instead",
    )
    args = parser.parse_args()

    if args.from_cache:
        note_events = transcription_service.load_note_events(args.from_cache)
        audio_candidates = list(SAMPLES_DIR.glob(f"{args.from_cache}.*"))
        if not audio_candidates:
            raise SystemExit(
                f"Loaded cached notes for '{args.from_cache}' but no matching audio file "
                f"in {SAMPLES_DIR} (needed for tempo estimation)."
            )
        audio_path = audio_candidates[0]
        print(f"Loaded cached note events for: {args.from_cache}")
    else:
        audio_path = Path(args.file) if args.file else pick_default_file()
        print(f"Transcribing: {audio_path}")
        note_events = transcription_service.run(str(audio_path))

    print(f"Raw note events: {len(note_events)}")

    result = quantization_service.run(note_events, audio_path=str(audio_path))

    print(f"Detected tempo: {result.tempo_bpm:.2f} BPM")
    print(f"Quantized note events: {len(result.notes)} (dropped {len(note_events) - len(result.notes)})")
    for note in result.notes[:10]:
        print(note)

    midi_path = quantization_service.to_midi(result, output_name=audio_path.stem)
    print(f"Quantized MIDI written to: {midi_path}")
    print(f"Quantization result cached to: storage/intermediate/{audio_path.stem}.quantized.json")


if __name__ == "__main__":
    main()
