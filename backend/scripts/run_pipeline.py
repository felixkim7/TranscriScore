"""Script chain: demucs (guitar/drums/vocals/piano) -> (trust or verify
label) -> transcribe, for one audio file. This is the "script chain"
CLAUDE.md's build order calls for before any of this gets wrapped in a
FastAPI router (that's step 8, app/api/transcribe.py — not written yet).

Labeling:
- vocals, drums: trusted directly from Demucs, no verification — Demucs is
  documented as strongest on exactly these two sources.
- guitar, piano: come pre-split from htdemucs_6s, but re-checked against
  classify_stem()'s rule-based features before trusting the label, since
  Demucs's own docs flag its piano source as bleed-prone. On a mismatch,
  the re-checked label is used instead (may be "unknown_accompaniment").

Usage:
    python scripts/run_pipeline.py <audio_path>
"""

import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas.transcription import NoteEvent
from app.services import classification_service, demucs_service, transcription_service

TRUSTED_STEM_LABELS = {
    "vocals": "vocal_melody",
    "drums": "drums",
}
VERIFIED_STEM_LABELS = {
    "guitar": "guitar_accompaniment",
    "piano": "piano_accompaniment",
}


def run_pipeline(input_audio_path: str) -> Dict[str, List[NoteEvent]]:
    """Run the full separate -> label -> transcribe pipeline for one audio file.

    Returns a dict mapping stem name -> its transcribed note events.
    """
    stems = demucs_service.run(input_audio_path)
    results: Dict[str, List[NoteEvent]] = {}

    for stem_name, stem_label in TRUSTED_STEM_LABELS.items():
        results[stem_name] = transcription_service.run(str(stems[stem_name]), stem_label=stem_label)

    for stem_name, expected_label in VERIFIED_STEM_LABELS.items():
        matches, predicted_label = classification_service.check_stem_label_confidence(
            str(stems[stem_name]), expected_label
        )
        final_label = expected_label if matches else predicted_label
        if not matches:
            print(f"  [!] {stem_name}.wav: expected {expected_label!r}, "
                  f"re-check predicted {predicted_label!r} — using {final_label!r}")
        results[stem_name] = transcription_service.run(str(stems[stem_name]), stem_label=final_label)

    return results


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_pipeline.py <audio_path>")
        raise SystemExit(1)

    results = run_pipeline(sys.argv[1])

    print("Pipeline complete")
    for stem_name, notes in results.items():
        print(f"  {stem_name:8s}: {len(notes)} notes"
              + (f" (label={notes[0].stem_label})" if notes else ""))


if __name__ == "__main__":
    main()
