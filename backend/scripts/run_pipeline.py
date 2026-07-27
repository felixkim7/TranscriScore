"""Full pipeline: demucs (all 6 htdemucs_6s stems) -> (trust or verify
label) -> transcribe -> quantize -> per-stem MusicXML -> combined MusicXML
-> combined MSCZ, for one audio file. This is the "script chain" CLAUDE.md's
build order calls for before any of this gets wrapped in a FastAPI router
(that's step 8, app/api/transcribe.py — not written yet).

Labeling:
- vocals, bass, other: trusted directly from Demucs, no verification. Demucs
  is documented as strongest on vocals specifically; bass and the catch-all
  "other" stem have no rule-based classifier worth building (classify_stem()
  only distinguishes guitar vs. piano), so they're trusted as-is too.
- drums: NOT run through transcription_service.run() (Basic Pitch) at all —
  Basic Pitch is a pitched-note model with no concept of unpitched percussion,
  confirmed to mostly miss real hits and mislabel what little it catches as
  near-arbitrary melodic pitches. Routed instead through
  drum_transcription_service.run() (onset detection + spectral kick/snare/
  hihat classification — see that module's docstring for the full reasoning).
- guitar, piano: come pre-split from htdemucs_6s, but re-checked against
  classify_stem()'s rule-based features before trusting the label, since
  Demucs's own docs flag its piano source as bleed-prone. On a mismatch,
  the re-checked label is used instead (may be "unknown_accompaniment").

Combining: each stem is transcribed and quantized independently first (its own
tempo/key/notes). A reference tempo is then detected once from the ORIGINAL mixed
audio (before separation — the fullest, most reliable single signal for tempo,
rather than trying to reconcile 6 separated-stem estimates of varying reliability
against each other) via quantization_service.detect_tempo(). Any stem whose own
detected tempo disagrees with that reference (outside quantization_service's
TEMPO_AGREEMENT_TOLERANCE — this catches both the classic beat-tracker octave error
and other gross mismatches, e.g. from a sparse/bleed-heavy stem) is re-quantized
from its raw note events against the reference tempo via
quantization_service.reconcile_tempo(), so its beat grid actually lines up with
the other stems instead of just sharing a tempo NUMBER. Only after reconciliation
is each stem's MusicXML written separately to storage/musicxml/stems/ (for
inspecting/debugging one stem's transcription in isolation), then all stems are
merged into a single multi-part score — one combined MusicXML + MSCZ, so the whole
transcription opens as one file and can be split apart by the user later in
MuseScore or another notation program.

Time signature isn't part of this reconciliation: it's currently hardcoded to 4/4
for every stem (see quantization_service.DEFAULT_TIME_SIGNATURE), so there's
nothing to disagree on yet. If/when real time-signature detection is added, the
same reference-audio approach should apply.

Usage:
    python scripts/run_pipeline.py <audio_path>
"""

import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas.transcription import NoteEvent, QuantizationResult
from app.services import (
    classification_service,
    demucs_service,
    drum_transcription_service,
    export_service,
    musicxml_service,
    quantization_service,
    transcription_service,
)

TRUSTED_STEM_LABELS = {
    "vocals": "vocal_melody",
    "bass": "bass",
    "other": "other_accompaniment",
}
VERIFIED_STEM_LABELS = {
    "guitar": "guitar_accompaniment",
    "piano": "piano_accompaniment",
}


def run_pipeline(input_audio_path: str) -> Dict[str, List[NoteEvent]]:
    """Run the separate -> label -> transcribe stage for one audio file.

    Returns a dict mapping stem name -> its transcribed note events.
    """
    input_stem = Path(input_audio_path).stem
    stems = demucs_service.run(input_audio_path)
    results: Dict[str, List[NoteEvent]] = {}

    results["drums"] = drum_transcription_service.run(
        str(stems["drums"]), stem_label="drums", input_stem=input_stem
    )

    for stem_name, stem_label in TRUSTED_STEM_LABELS.items():
        results[stem_name] = transcription_service.run(
            str(stems[stem_name]), stem_label=stem_label, input_stem=input_stem
        )

    for stem_name, expected_label in VERIFIED_STEM_LABELS.items():
        matches, predicted_label = classification_service.check_stem_label_confidence(
            str(stems[stem_name]), expected_label
        )
        final_label = expected_label if matches else predicted_label
        if not matches:
            print(f"  [!] {stem_name}.wav: expected {expected_label!r}, "
                  f"re-check predicted {predicted_label!r} - using {final_label!r}")
        results[stem_name] = transcription_service.run(
            str(stems[stem_name]), stem_label=final_label, input_stem=input_stem
        )

    return results


def stem_audio_paths(input_audio_path: str, stem_names) -> Dict[str, str]:
    """Map each stem name to its separated audio file on disk.

    Demucs writes each stem's wav under storage/stems/<model>/<input_stem>/
    <stem_name>.wav, matching demucs_service's output layout.
    """
    from app.config.settings import DEMUCS_MODEL, STEMS_DIR

    input_stem_dir = STEMS_DIR / DEMUCS_MODEL / Path(input_audio_path).stem
    return {name: str(input_stem_dir / f"{name}.wav") for name in stem_names}


def quantize_stems(
    input_audio_path: str, transcriptions: Dict[str, List[NoteEvent]]
) -> Dict[str, QuantizationResult]:
    """Quantize each stem's note events against its own independently-detected tempo.

    This is the FIRST quantization pass — before tempo reconciliation (see main()).
    Each stem's tempo/beat grid here reflects only that stem's own separated audio,
    which may disagree with other stems (or be a straight-up octave error) since
    separation quality and how much real rhythmic content survives varies per stem.
    """
    input_stem = Path(input_audio_path).stem
    audio_paths = stem_audio_paths(input_audio_path, transcriptions.keys())

    results: Dict[str, QuantizationResult] = {}
    for stem_name, note_events in transcriptions.items():
        if not note_events:
            print(f"  [!] {stem_name}: no note events, skipping quantization")
            continue
        results[stem_name] = quantization_service.run(
            note_events, audio_path=audio_paths[stem_name], input_stem=input_stem
        )

    return results


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_pipeline.py <audio_path>")
        raise SystemExit(1)

    input_audio_path = sys.argv[1]
    output_name = Path(input_audio_path).stem

    transcriptions = run_pipeline(input_audio_path)
    print("Transcription complete")
    for stem_name, notes in transcriptions.items():
        print(f"  {stem_name:8s}: {len(notes)} notes"
              + (f" (label={notes[0].stem_label})" if notes else ""))

    quantized = quantize_stems(input_audio_path, transcriptions)
    print("Quantization complete (per-stem tempo, before reconciliation)")
    for stem_name, result in quantized.items():
        print(f"  {stem_name:8s}: {result.tempo_bpm:.2f} BPM, {len(result.notes)} quantized notes")

    if not quantized:
        print("No stems produced any notes - nothing to combine.")
        raise SystemExit(1)

    # Reference tempo comes from the ORIGINAL mixed audio, not a vote among the
    # stems — the fullest, most reliable single signal (see run_pipeline.py's
    # module docstring for the full reasoning). Any stem whose own tempo disagrees
    # is re-quantized from its raw note events against this reference so its beat
    # grid actually lines up with the rest, not just its tempo NUMBER.
    reference_tempo = quantization_service.detect_tempo(input_audio_path)
    print(f"Reference tempo (from original mixed audio): {reference_tempo:.2f} BPM")

    quantized = quantization_service.reconcile_tempo(
        reference_tempo,
        quantized,
        {name: transcriptions[name] for name in quantized},
        stem_audio_paths(input_audio_path, quantized.keys()),
        input_stem=output_name,
    )

    for stem_name, result in quantized.items():
        musicxml_service.write_stem_musicxml(result, output_name=stem_name, input_stem=output_name)
    print("Per-stem MusicXML written (storage/musicxml/stems/), reconciled to the reference tempo")

    combined_path = musicxml_service.run_combined(list(quantized.values()), output_name=output_name)
    print(f"Combined MusicXML written to: {combined_path}")

    mscz_path = export_service.to_mscz(str(combined_path), output_name=output_name)
    print(f"Combined MSCZ written to: {mscz_path}")


if __name__ == "__main__":
    main()
