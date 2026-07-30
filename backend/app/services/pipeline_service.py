"""Full pipeline: demucs (all 6 htdemucs_6s stems) -> (trust or verify label) ->
transcribe -> quantize -> reconcile tempo -> per-stem MusicXML -> combined
MusicXML -> combined MSCZ, for one audio file.

This is the importable form of what scripts/run_pipeline.py used to run as a
standalone script — moved here so both the CLI script and the async API
(app/api/upload.py, app/api/transcribe.py) can call the same logic without
duplicating it.

Split into three resumable phases (added for the review-checkpoint feature —
the user can inspect each phase's output and decide whether to continue before
the next one runs, rather than the whole pipeline running start-to-finish
uninterrupted):

  run_until_separation()   -> pauses after Demucs separation
  run_transcription_phase() -> pauses after transcribing all stems
  run_final_phase()         -> quantize -> reconcile tempo -> render -> export

Each phase is a plain function, not a generator/coroutine that "pauses" in the
Python sense — the actual pausing happens at the API layer (app/api/upload.py,
app/api/transcribe.py): a phase function runs to completion and returns, the
job's status is set to AWAITING_REVIEW, and nothing further runs until a
POST /jobs/{job_id}/continue call invokes the next phase as a NEW background
task. Between phases, all state needed to resume lives on disk (Demucs's stem
wavs, each stem's transcribed notes JSON) or in the job record itself
(stem_labels) — nothing is held in memory across the pause, so a server
restart between phases doesn't lose anything.

scripts/run_pipeline.py still runs all three phases back-to-back with no
pausing (a CLI script has no "review and click continue" concept), via
run_full_pipeline_no_pauses() at the bottom of this file.

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
  (see classification_service.py).

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

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np

from app.config.settings import DEMUCS_MODEL, DEMUCS_STEM_NAMES, MUSICXML_STEMS_DIR, STEMS_DIR, stem_output_dir
from app.schemas.job import JobStage
from app.schemas.transcription import NoteEvent, QuantizationResult
from app.services import (
    classification_service,
    demucs_service,
    drum_transcription_service,
    export_service,
    musicxml_service,
    preprocessing_service,
    quantization_service,
    transcription_service,
)


@dataclass
class SeparationPhaseResult:
    stem_names: List[str]
    # Tempo/beat tracking, detected once on the ORIGINAL pre-separation audio
    # (per the user's plan) rather than per-stem — the full mixed signal is the
    # most reliable single source for this (same reasoning already used for
    # quantization_service.detect_tempo()'s "reference tempo" in
    # run_final_phase(), just moved earlier so it's available right after
    # upload instead of only at the final phase). NOT yet consumed by
    # transcription/quantization anywhere — detected and persisted on the Job
    # for later use, per explicit instruction not to wire it in yet.
    reference_tempo_bpm: float
    reference_beat_times: List[float]

TRUSTED_STEM_LABELS = {
    "vocals": "vocal_melody",
    "bass": "bass",
    "other": "other_accompaniment",
}
VERIFIED_STEM_LABELS = {
    "guitar": "guitar_accompaniment",
    "piano": "piano_accompaniment",
}

# Synthetic "stem name" for single-instrument uploads that skip Demucs
# separation entirely (see run_until_separation()'s skip_separation param) —
# the original upload IS the one and only stem in this mode, so it needs a
# name of its own for the same per-stem storage keys (storage/midi/<job_id>/
# <name>.mid, storage/musicxml/stems/<job_id>/<name>.musicxml, etc.) that
# every Demucs stem name (vocals/drums/bass/guitar/piano/other) already uses —
# "main" rather than one of those 6 names specifically because none of them
# are semantically correct (this file was never actually separated FROM
# anything), and reusing e.g. "vocals" as a fake Demucs name risked being
# confused with a real separated vocals stem elsewhere in the codebase.
SINGLE_INSTRUMENT_STEM_NAME = "main"

# GM-instrument-family labels the user can pick when uploading a single-
# instrument recording (skip_separation=True) — the same stem_label
# vocabulary every Demucs-derived stem already gets routed through
# (TRUSTED_STEM_LABELS/VERIFIED_STEM_LABELS above, plus "drums"), so every
# downstream stage (MIDI GM program in transcription_service.py, staff
# layout/instrument in musicxml_service.py) already knows how to handle
# these without new branching — only WHICH label applies is decided
# differently (explicit user choice instead of "which Demucs stem produced
# this audio").
SINGLE_INSTRUMENT_LABELS = {
    "vocal_melody",
    "bass",
    "guitar_accompaniment",
    "piano_accompaniment",
    "drums",
    "other_accompaniment",
}

# Callback signature for progress reporting: (stage, message) -> None. message is a
# short human-readable line (what run_pipeline.py used to just print()); stage is
# one of JobStage so a caller like job_service can persist structured progress.
ProgressCallback = Callable[[JobStage, str], None]


def _report(on_stage: Optional[ProgressCallback], stage: JobStage, message: str) -> None:
    print(message)
    if on_stage is not None:
        on_stage(stage, message)


def readable_output_name(original_filename: str, job_id: str) -> str:
    """Build a human-readable final-output FILENAME stem for an API-driven job.

    This is a filename, not a title — see readable_title() below for what actually
    gets drawn on the sheet music. input_stem (== job_id, since app/api/upload.py
    deliberately saves uploads as <job_id>.<ext> to avoid collisions between two
    uploads sharing a name) is fine as the collision-proof key used for on-disk
    NESTING (stem_output_dir(), stems_dir, storage/intermediate/<job_id>/, etc.),
    but it's a raw UUID, so using it as the FINAL combined MusicXML/MSCZ filename
    (a flat, non-nested namespace — see musicxml_service.run_combined()/
    export_service.to_mscz()) is what made those files unreadable (surfaced by the
    user: storage/musicxml/ full of <uuid>.musicxml instead of names like the old
    CLI-script runs' sample2.musicxml).

    Sanitizes the ORIGINAL uploaded filename's stem for filesystem-safety, then
    appends a short slice of the job_id so two uploads named e.g. "song.mp3" still
    can't collide in that flat namespace. That job-id fragment is only ever meant
    to disambiguate a file ON DISK — musicxml_service.run_combined()'s separate
    `title` parameter (pass readable_title(), not this) is what keeps it off the
    visible score/instrument names and off the MSCZ (which is converted straight
    from the MusicXML, so whatever title is baked in there carries through).
    """
    stem = Path(original_filename).stem
    safe_stem = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_") or "track"
    return f"{safe_stem}-{job_id[:8]}"


def readable_title(original_filename: str) -> str:
    """Build the human-readable TITLE shown on the sheet music itself — no job id.

    Deliberately separate from readable_output_name() (the on-disk filename, which
    DOES carry a job-id suffix for collision-safety in the flat storage/musicxml/
    namespace): a job id has no business appearing on the rendered score or as an
    instrument/part name, only as a disambiguator for files on disk.
    """
    stem = Path(original_filename).stem
    return stem or "Untitled"


def stem_audio_paths(input_audio_path: str, stem_names) -> Dict[str, str]:
    """Map each stem name to its separated audio file on disk.

    Demucs writes each stem's wav under storage/stems/<model>/<input_stem>/
    <stem_name>.wav, matching demucs_service's output layout.

    SINGLE_INSTRUMENT_STEM_NAME ("main") is special-cased to map back to
    input_audio_path itself, not a Demucs output path — for a skip_separation
    job, no Demucs run ever happened, so there's no storage/stems/... file to
    find; the original upload IS the "stem." Every caller of this function
    (quantization, tempo reconciliation) only needs a real, valid audio file
    to read from here, not specifically a Demucs one — see _quantize_stems()'s
    docstring for confirmation that this path is only used for a duration
    fallback, not tempo detection itself.
    """
    input_stem_dir = STEMS_DIR / DEMUCS_MODEL / Path(input_audio_path).stem
    return {
        name: input_audio_path if name == SINGLE_INSTRUMENT_STEM_NAME else str(input_stem_dir / f"{name}.wav")
        for name in stem_names
    }


def run_until_separation(
    input_audio_path: str,
    on_stage: Optional[ProgressCallback] = None,
    skip_separation: bool = False,
) -> SeparationPhaseResult:
    """Phase 1: run Demucs separation, and detect tempo/beat tracking on the
    ORIGINAL pre-separation audio, then stop.

    Tempo/beat detection runs on input_audio_path BEFORE separation — the full
    mixed signal, not a lossy separated stem — matching the same "most reliable
    single source" reasoning already used for the final phase's reference-tempo
    reconciliation (see this module's docstring), just run earlier so it's
    available immediately after upload. Order relative to demucs_service.run()
    doesn't matter (separation doesn't modify or consume the original file), so
    it runs after separation simply so a Demucs failure still surfaces first.

    skip_separation: for a single-instrument recording, where running Demucs
    just to end up with one dominant "stem" (plus 5 mostly-empty ones) is
    wasted time and a real source of spurious content in the other 5 stems
    (bleed/silence Basic Pitch could still find phantom notes in). When True,
    demucs_service.run() is never called — the upload stays exactly as
    uploaded, and stem_names is [SINGLE_INSTRUMENT_STEM_NAME] instead of the
    real DEMUCS_STEM_NAMES list, so every later phase treats the original
    file as the one and only stem (see stem_audio_paths()'s special-casing
    of that name). Tempo/beat detection is unaffected either way — it always
    ran on the original pre-separation audio already, skip_separation or not.

    Returns stem names produced (matches settings.DEMUCS_STEM_NAMES — Demucs
    itself decides what it can split out, this doesn't vary per file — unless
    skip_separation, see above) plus the detected reference tempo/beat times.
    The actual stem audio is left on disk (storage/stems/...) for the caller
    to serve via GET /audio/{job_id}/{stem} and for run_transcription_phase()
    to read back later — not applicable when skip_separation, since there's
    no separated audio, only the original upload.
    """
    if skip_separation:
        _report(on_stage, JobStage.SEPARATING, "Skipping stem separation (single instrument)...")
        stem_names = [SINGLE_INSTRUMENT_STEM_NAME]
    else:
        _report(on_stage, JobStage.SEPARATING, "Separating into stems (Demucs)...")
        demucs_service.run(input_audio_path)
        stem_names = list(DEMUCS_STEM_NAMES)

    y, sr = preprocessing_service.load_audio(input_audio_path, sr=None)
    tempo_onset = preprocessing_service.detect_tempo_onset(y, sr)

    return SeparationPhaseResult(
        stem_names=stem_names,
        reference_tempo_bpm=tempo_onset.tempo_bpm,
        reference_beat_times=tempo_onset.beat_times.tolist(),
    )


def run_transcription_phase(
    input_audio_path: str,
    on_stage: Optional[ProgressCallback] = None,
    single_instrument_label: Optional[str] = None,
) -> Dict[str, str]:
    """Phase 2: preprocess + transcribe every stem (assumes separation already
    ran — phase 1), then stop.

    single_instrument_label: set when phase 1 ran with skip_separation=True
    (must be one of SINGLE_INSTRUMENT_LABELS — the same stem_label vocabulary
    every Demucs-derived stem already uses). When given, the ENTIRE Demucs-
    stem iteration below is bypassed — the original upload is transcribed
    directly, once, under SINGLE_INSTRUMENT_STEM_NAME ("main"), routed to
    drum_transcription_service.run() or transcription_service.run() by the
    same drums-vs-pitched rule as any other stem. No classification check
    (classification_service.check_stem_label_confidence() exists specifically
    to re-verify Demucs's OWN guitar/piano split — there's no Demucs split
    here to re-verify, the user's label IS the ground truth for this upload).

    Every PITCHED stem (everything except drums, which never goes through
    Basic Pitch — see this module's docstring) is preprocessed via
    preprocessing_service.preprocess_stem() BEFORE transcription_service.run()
    is called: loudness-normalized (written to a new wav — this is what
    actually changes the audio bytes Basic Pitch reads, since predict() only
    accepts a file path, not pre-loaded audio/features), then mel-spectrogram/
    tempo/beat/onset-detected. Only the loudness-normalized audio path is
    currently passed on to transcription_service.run() — the mel-spectrogram/
    tempo/beats/onsets are computed but not otherwise consumed here.

    Two other uses of this preprocessing pass were tried and REMOVED after
    real testing on sample7's vocals stem: passing settings.STEM_FREQUENCY_
    RANGES to predict()'s minimum_frequency/maximum_frequency (negligible
    effect, kept out mainly for being unvalidated), and cross-checking Basic
    Pitch's note onsets against preprocess_stem()'s independently-detected
    onset times to filter unsupported notes (REMOVED because it overfiltered:
    cut 190->109 notes, 43%, and on listening was found to cut real content,
    not just phantom notes — same failure mode as the frame_threshold=0.4
    experiment elsewhere in this project's history). See
    transcription_service.run()'s docstring for the full writeup.

    Drums deliberately skip preprocess_stem() — drum_transcription_service.run()
    already does its own load_audio()/detect_tempo_onset() at DRUM_SAMPLE_RATE
    (a fixed rate for its spectral classification, different from what
    preprocess_stem() would use), and doesn't call Basic Pitch at all, so
    loudness normalization (tuned for Basic Pitch's thresholds) doesn't apply.

    classification_service.check_stem_label_confidence() below still reads the
    RAW (non-preprocessed) stem — that's Teammate A's stage, and changing what
    audio it classifies from is out of scope here.

    Returns a dict of stem_name -> stem_label (the label decisions made here,
    e.g. after classification re-checks) — this needs to be persisted on the Job
    (job_service stores it as Job.stem_labels) so run_final_phase() can rebuild
    the same per-stem QuantizationResults later without re-running
    classification. The actual transcribed note events are left on disk
    (storage/intermediate/<job_id>/<stem>.notes.json, written by
    transcription_service.run()/drum_transcription_service.run()) rather than
    returned here or stored on the Job — reloaded via
    transcription_service.load_note_events() in run_final_phase().
    """
    input_stem = Path(input_audio_path).stem

    if single_instrument_label is not None:
        if single_instrument_label not in SINGLE_INSTRUMENT_LABELS:
            raise ValueError(
                f"single_instrument_label={single_instrument_label!r} is not one of {SINGLE_INSTRUMENT_LABELS}"
            )
        _report(on_stage, JobStage.TRANSCRIBING, "Transcribing...")
        stem_name = SINGLE_INSTRUMENT_STEM_NAME
        if single_instrument_label == "drums":
            drum_transcription_service.run(input_audio_path, stem_label="drums", input_stem=input_stem)
        else:
            preprocessed = preprocessing_service.preprocess_stem(input_audio_path, stem_name, input_stem=input_stem)
            transcription_service.run(
                preprocessed.normalized_audio_path,
                stem_label=single_instrument_label,
                input_stem=input_stem,
            )
        return {stem_name: single_instrument_label}

    stems = stem_audio_paths(input_audio_path, DEMUCS_STEM_NAMES)

    _report(on_stage, JobStage.TRANSCRIBING, "Transcribing stems...")
    stem_labels: Dict[str, str] = {}

    drum_transcription_service.run(stems["drums"], stem_label="drums", input_stem=input_stem)
    stem_labels["drums"] = "drums"

    def _transcribe_pitched(stem_name: str, stem_label: str) -> None:
        preprocessed = preprocessing_service.preprocess_stem(stems[stem_name], stem_name, input_stem=input_stem)
        transcription_service.run(
            preprocessed.normalized_audio_path,
            stem_label=stem_label,
            input_stem=input_stem,
        )

    for stem_name, stem_label in TRUSTED_STEM_LABELS.items():
        _transcribe_pitched(stem_name, stem_label)
        stem_labels[stem_name] = stem_label

    for stem_name, expected_label in VERIFIED_STEM_LABELS.items():
        matches, predicted_label = classification_service.check_stem_label_confidence(
            stems[stem_name], expected_label
        )
        # Log-only: stem_label always stays expected_label (the Demucs stem's own
        # identity) regardless of what the classifier predicts — see this
        # module's docstring for why.
        if not matches:
            print(f"  [!] {stem_name}.wav: expected {expected_label!r}, "
                  f"re-check predicted {predicted_label!r} - keeping {expected_label!r} "
                  f"(logged only, doesn't change notation layout)")
        _transcribe_pitched(stem_name, expected_label)
        stem_labels[stem_name] = expected_label

    return stem_labels


def run_final_phase(
    input_audio_path: str,
    stem_labels: Dict[str, str],
    on_stage: Optional[ProgressCallback] = None,
    output_name: Optional[str] = None,
    title: Optional[str] = None,
    reference_tempo_bpm: Optional[float] = None,
    reference_beat_times: Optional[List[float]] = None,
) -> dict:
    """Phase 3: quantize -> reconcile tempo -> render MusicXML -> export.
    Assumes phases 1 and 2 already ran (separation + transcription).

    reference_tempo_bpm / reference_beat_times: the tempo/beat grid detected
    ONCE from the original pre-separation mixed audio during phase 1
    (run_until_separation()'s SeparationPhaseResult, persisted as
    Job.reference_tempo_bpm/reference_beat_times) — EVERY stem is quantized
    against this SAME grid (see _quantize_stems()), replacing each stem's own
    independently-redetected tempo/beats. app/api/transcribe.py passes these
    from the Job record. When omitted (the CLI script, which has no Job to
    read from), falls back to detecting once here instead — still ONE
    detection shared by every stem, just not persisted anywhere durable
    between phases the way the API path's Job record is.

    stem_labels: stem_name -> stem_label, as returned by run_transcription_phase()
    (and persisted on the Job in between) — needed to reload each stem's note
    events with load_note_events() and to know which stem produced which
    QuantizationResult.stem_label for musicxml_service's staff-layout routing.

    output_name: the FINAL combined MusicXML/MSCZ FILENAME stem, not the title
    shown on the score (see title below). Defaults to input_stem (==
    Path(input_audio_path).stem) when omitted, matching the old behavior — which
    is correct for the CLI script (run_full_pipeline_no_pauses(), where
    input_audio_path is already the sample's own readable filename) but NOT
    for API-driven jobs, where input_audio_path is storage/uploads/<job_id>.<ext>
    (see app/api/upload.py) so input_stem is a raw UUID. app/api/transcribe.py
    passes readable_output_name(job.original_filename, job_id) instead, so that
    combined output ends up readable rather than UUID-named while per-stem/
    intermediate files (which stay job_id-nested — see stem_output_dir()) remain
    collision-proof.

    title: the human-readable name actually drawn on the score/MSCZ. Defaults to
    output_name when omitted (correct for the CLI script, whose output_name is
    already clean) — API-driven jobs pass readable_title(job.original_filename)
    instead, since output_name there carries a job-id suffix that must stay out
    of anything user-visible.

    Returns a dict with combined_musicxml_path, combined_mscz_path, and per-stem
    details (name, label, tempo, note count, musicxml path) — enough for
    app/api/transcribe.py to build a JobResult from.
    """
    input_audio_path = str(input_audio_path)
    input_stem = Path(input_audio_path).stem
    if output_name is None:
        output_name = input_stem

    if reference_tempo_bpm is None or reference_beat_times is None:
        # No Job record to read from (the CLI script) — detect once here
        # instead, from the same original pre-separation audio phase 1 would
        # have used, so every stem still shares ONE detection.
        y, sr = preprocessing_service.load_audio(input_audio_path, sr=None)
        tempo_onset = preprocessing_service.detect_tempo_onset(y, sr)
        reference_tempo_bpm = tempo_onset.tempo_bpm
        reference_beat_times = tempo_onset.beat_times.tolist()
    print(f"Reference tempo (from original mixed audio): {reference_tempo_bpm:.2f} BPM")

    transcriptions: Dict[str, List[NoteEvent]] = {
        stem_name: transcription_service.load_note_events(stem_name, input_stem=input_stem)
        for stem_name in stem_labels
    }

    _report(on_stage, JobStage.QUANTIZING, "Quantizing notes...")
    quantized = _quantize_stems(
        input_audio_path, transcriptions, reference_tempo_bpm, np.asarray(reference_beat_times, dtype=float)
    )
    print("Quantization complete (every stem against the shared reference tempo/beat grid)")
    for stem_name, result in quantized.items():
        print(f"  {stem_name:8s}: {result.tempo_bpm:.2f} BPM, {len(result.notes)} quantized notes")

    if not quantized:
        raise RuntimeError("No stems produced any notes - nothing to combine.")

    _report(on_stage, JobStage.RECONCILING_TEMPO, "Reconciling tempo across stems...")
    # Every stem was already quantized against the SAME reference tempo/beat
    # grid above, so this is now a guaranteed no-op (every result.tempo_bpm
    # already equals reference_tempo_bpm) — kept in place rather than removed,
    # since reconcile_tempo()'s duration-sanity-check logic is still real,
    # tested behavior that a future per-stem-tempo mode (if ever reintroduced)
    # would still need.
    quantized = quantization_service.reconcile_tempo(
        reference_tempo_bpm,
        quantized,
        {name: transcriptions[name] for name in quantized},
        stem_audio_paths(input_audio_path, quantized.keys()),
        input_stem=input_stem,
    )

    _report(on_stage, JobStage.RENDERING_MUSICXML, "Rendering MusicXML...")
    for stem_name, result in quantized.items():
        musicxml_service.write_stem_musicxml(result, output_name=stem_name, input_stem=input_stem)
    print("Per-stem MusicXML written (storage/musicxml/stems/), reconciled to the reference tempo")

    combined_path = musicxml_service.run_combined(list(quantized.values()), output_name=output_name, title=title)
    print(f"Combined MusicXML written to: {combined_path}")

    _report(on_stage, JobStage.EXPORTING, "Exporting to MSCZ...")
    mscz_path = export_service.to_mscz(str(combined_path), output_name=output_name)
    print(f"Combined MSCZ written to: {mscz_path}")

    stems_dir = stem_output_dir(MUSICXML_STEMS_DIR, input_stem)
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


def _quantize_stems(
    input_audio_path: str,
    transcriptions: Dict[str, List[NoteEvent]],
    reference_tempo_bpm: float,
    reference_beat_times: np.ndarray,
) -> Dict[str, QuantizationResult]:
    """Quantize every stem's note events against the SAME reference tempo/beat
    grid — detected once from the original pre-separation mixed audio (see
    run_final_phase()'s docstring), not each stem's own independently-detected
    tempo. Previously each stem redetected its own tempo/beats from its own
    (lossier, separated) audio here, which could disagree with other stems (or
    be a straight-up octave error) purely from separation-quality variance —
    reconcile_tempo() existed specifically to patch that up after the fact.
    Quantizing every stem against one shared, known-good detection from the
    start removes that disagreement at the source instead.

    audio_path is still passed to quantization_service.run() per stem — needed
    for _beat_grid()'s synthetic-grid fallback duration if reference_beat_times
    is too sparse to interpolate against, not for tempo/beat detection itself.
    """
    input_stem = Path(input_audio_path).stem
    audio_paths = stem_audio_paths(input_audio_path, transcriptions.keys())

    results: Dict[str, QuantizationResult] = {}
    for stem_name, note_events in transcriptions.items():
        if not note_events:
            print(f"  [!] {stem_name}: no note events, skipping quantization")
            continue
        results[stem_name] = quantization_service.run(
            note_events,
            audio_path=audio_paths[stem_name],
            tempo_bpm=reference_tempo_bpm,
            input_stem=input_stem,
            reference_beat_times=reference_beat_times,
        )

    return results


def run_full_pipeline_no_pauses(input_audio_path: str, on_stage: Optional[ProgressCallback] = None) -> dict:
    """Run all three phases back-to-back with no review checkpoints — used by
    scripts/run_pipeline.py (a CLI script has no "review and click continue"
    concept) so it still works as a single command.
    """
    separation_result = run_until_separation(input_audio_path, on_stage)
    stem_labels = run_transcription_phase(input_audio_path, on_stage)
    return run_final_phase(
        input_audio_path,
        stem_labels,
        on_stage,
        reference_tempo_bpm=separation_result.reference_tempo_bpm,
        reference_beat_times=separation_result.reference_beat_times,
    )
