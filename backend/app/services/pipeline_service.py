"""Full pipeline: demucs (all 6 htdemucs_6s stems) -> (trust or verify label) ->
transcribe -> quantize -> reconcile tempo -> per-stem MusicXML -> combined
MusicXML -> combined MSCZ, for one audio file.

This is the importable form of what scripts/run_pipeline.py used to run as a
standalone script — moved here so both the CLI script and the async API
(app/api/transcribe.py) can call the same logic without duplicating it.
scripts/run_pipeline.py is now a thin wrapper that just prints progress to stdout;
run_full_pipeline() below takes an optional on_stage callback instead, so the API
can report progress via GET /status/{job_id} without depending on captured stdout.

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
  this is only LOGGED, not acted on — stem_label always stays the Demucs-
  identity label ("guitar_accompaniment" for guitar.wav, "piano_accompaniment"
  for piano.wav) regardless of what the classifier guesses, because stem_label
  also drives musicxml_service.py's notation staff layout (single-staff guitar
  vs. two-staff piano grand staff), and the Demucs stem the audio actually came
  from is a much more reliable signal for THAT than a rule-based heuristic
  whose thresholds were validated on synthetic test signals, not real audio
  (see classification_service.py). Previously the classifier's relabel was used
  as the final stem_label, which caused a real stem misidentified as piano to
  render as an (incorrect) two-staff grand staff instead of single-staff guitar
  notation — confirmed on a real run.

Combining: each stem is transcribed and quantized independently first (its own
tempo/key/notes). A reference tempo is then detected once from the ORIGINAL mixed
audio (before separation — the fullest, most reliable single signal for tempo,
rather than trying to reconcile 6 separated-stem estimates of varying reliability
against each other) via quantization_service.detect_tempo(). Any stem whose own
detected tempo disagrees with that reference (outside quantization_service's
TEMPO_AGREEMENT_TOLERANCE — this catches both the classic beat-tracker octave error
and other gross mismatches, e.g. from a sparse/bleed-heavy stem) is a CANDIDATE for
re-quantizing against the reference — but reconcile_tempo() only actually applies
it if doing so keeps the notated duration close to the real audio's actual length
(DURATION_RATIO_TOLERANCE); otherwise the stem keeps its own tempo, since a forced
mismatched reference can make the notation claim to finish playing far too early/
late even though the beat POSITIONS are correct (see quantization_service.py).
Only after reconciliation is each stem's MusicXML written separately to
storage/musicxml/stems/ (for inspecting/debugging one stem's transcription in
isolation), then all stems are merged into a single multi-part score — one
combined MusicXML + MSCZ, so the whole transcription opens as one file and can be
split apart by the user later in MuseScore or another notation program.

Time signature isn't part of this reconciliation: it's currently hardcoded to 4/4
for every stem (see quantization_service.DEFAULT_TIME_SIGNATURE), so there's
nothing to disagree on yet. If/when real time-signature detection is added, the
same reference-audio approach should apply.
"""

from pathlib import Path
from typing import Callable, Dict, List, Optional

from app.config.settings import DEMUCS_MODEL, MUSICXML_STEMS_DIR, STEMS_DIR, stem_output_dir
from app.schemas.job import JobStage
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

# Callback signature for progress reporting: (stage, message) -> None. message is a
# short human-readable line (what run_pipeline.py used to just print()); stage is
# one of JobStage so a caller like job_service can persist structured progress.
ProgressCallback = Callable[[JobStage, str], None]


def _report(on_stage: Optional[ProgressCallback], stage: JobStage, message: str) -> None:
    print(message)
    if on_stage is not None:
        on_stage(stage, message)


def run_transcription_stage(
    input_audio_path: str, on_stage: Optional[ProgressCallback] = None
) -> Dict[str, List[NoteEvent]]:
    """Run the separate -> label -> transcribe stage for one audio file.

    Returns a dict mapping stem name -> its transcribed note events.
    """
    input_stem = Path(input_audio_path).stem

    _report(on_stage, JobStage.SEPARATING, "Separating into stems (Demucs)...")
    stems = demucs_service.run(input_audio_path)

    _report(on_stage, JobStage.TRANSCRIBING, "Transcribing stems...")
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
        # Log-only: stem_label always stays expected_label (the Demucs stem's own
        # identity) regardless of what the classifier predicts — see this module's
        # docstring for why.
        if not matches:
            print(f"  [!] {stem_name}.wav: expected {expected_label!r}, "
                  f"re-check predicted {predicted_label!r} - keeping {expected_label!r} "
                  f"(logged only, doesn't change notation layout)")
        results[stem_name] = transcription_service.run(
            str(stems[stem_name]), stem_label=expected_label, input_stem=input_stem
        )

    return results


def stem_audio_paths(input_audio_path: str, stem_names) -> Dict[str, str]:
    """Map each stem name to its separated audio file on disk.

    Demucs writes each stem's wav under storage/stems/<model>/<input_stem>/
    <stem_name>.wav, matching demucs_service's output layout.
    """
    input_stem_dir = STEMS_DIR / DEMUCS_MODEL / Path(input_audio_path).stem
    return {name: str(input_stem_dir / f"{name}.wav") for name in stem_names}


def quantize_stems(
    input_audio_path: str, transcriptions: Dict[str, List[NoteEvent]]
) -> Dict[str, QuantizationResult]:
    """Quantize each stem's note events against its own independently-detected tempo.

    This is the FIRST quantization pass — before tempo reconciliation (see
    run_full_pipeline()). Each stem's tempo/beat grid here reflects only that
    stem's own separated audio, which may disagree with other stems (or be a
    straight-up octave error) since separation quality and how much real
    rhythmic content survives varies per stem.
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


def run_full_pipeline(input_audio_path: str, on_stage: Optional[ProgressCallback] = None) -> dict:
    """Run the complete audio -> combined MusicXML/MSCZ pipeline for one file.

    on_stage: optional callback(stage: JobStage, message: str), called at each
    pipeline stage transition — lets a caller (e.g. the async job API) persist
    progress without depending on stdout. If omitted, this only prints, same as
    the old scripts/run_pipeline.py behavior.

    Returns a dict with combined_musicxml_path, combined_mscz_path, and per-stem
    details (name, label, tempo, note count, musicxml path) — enough for
    app/api/transcribe.py to build a JobResult from.
    """
    input_audio_path = str(input_audio_path)
    output_name = Path(input_audio_path).stem

    transcriptions = run_transcription_stage(input_audio_path, on_stage)
    print("Transcription complete")
    for stem_name, notes in transcriptions.items():
        print(f"  {stem_name:8s}: {len(notes)} notes"
              + (f" (label={notes[0].stem_label})" if notes else ""))

    _report(on_stage, JobStage.QUANTIZING, "Quantizing notes...")
    quantized = quantize_stems(input_audio_path, transcriptions)
    print("Quantization complete (per-stem tempo, before reconciliation)")
    for stem_name, result in quantized.items():
        print(f"  {stem_name:8s}: {result.tempo_bpm:.2f} BPM, {len(result.notes)} quantized notes")

    if not quantized:
        raise RuntimeError("No stems produced any notes - nothing to combine.")

    _report(on_stage, JobStage.RECONCILING_TEMPO, "Reconciling tempo across stems...")
    # Reference tempo comes from the ORIGINAL mixed audio, not a vote among the
    # stems — the fullest, most reliable single signal (see this module's
    # docstring for the full reasoning).
    reference_tempo = quantization_service.detect_tempo(input_audio_path)
    print(f"Reference tempo (from original mixed audio): {reference_tempo:.2f} BPM")

    quantized = quantization_service.reconcile_tempo(
        reference_tempo,
        quantized,
        {name: transcriptions[name] for name in quantized},
        stem_audio_paths(input_audio_path, quantized.keys()),
        input_stem=output_name,
    )

    _report(on_stage, JobStage.RENDERING_MUSICXML, "Rendering MusicXML...")
    for stem_name, result in quantized.items():
        musicxml_service.write_stem_musicxml(result, output_name=stem_name, input_stem=output_name)
    print("Per-stem MusicXML written (storage/musicxml/stems/), reconciled to the reference tempo")

    combined_path = musicxml_service.run_combined(list(quantized.values()), output_name=output_name)
    print(f"Combined MusicXML written to: {combined_path}")

    _report(on_stage, JobStage.EXPORTING, "Exporting to MSCZ...")
    mscz_path = export_service.to_mscz(str(combined_path), output_name=output_name)
    print(f"Combined MSCZ written to: {mscz_path}")

    stems_dir = stem_output_dir(MUSICXML_STEMS_DIR, output_name)
    stem_details = [
        {
            "stem_name": stem_name,
            "stem_label": result.stem_label,
            "tempo_bpm": result.tempo_bpm,
            "note_count": len(result.notes),
            "musicxml_path": str(stems_dir / f"{stem_name}.musicxml"),
        }
        for stem_name, result in quantized.items()
    ]

    return {
        "combined_musicxml_path": str(combined_path),
        "combined_mscz_path": str(mscz_path),
        "stems": stem_details,
    }
