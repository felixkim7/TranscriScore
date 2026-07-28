import json
from pathlib import Path
from typing import List, Optional

import librosa
import numpy as np
import pretty_midi
import soundfile as sf

from app.config.settings import INTERMEDIATE_DIR, QUANTIZED_MIDI_DIR, stem_output_dir
from app.schemas.transcription import NoteEvent, QuantizationResult, QuantizedNoteEvent

GRID_SUBDIVISION = 0.25  # snap to 16th notes (in beats)
CONFIDENCE_DROP_PERCENTILE = 10  # drop the bottom 10% of notes by confidence
SUSTAIN_MERGE_GAP_SECONDS = 0.08  # merge same-pitch notes touching within this gap...
SUSTAIN_MERGE_MAX_VELOCITY_INCREASE = 0  # ...only if velocity doesn't rise (decay = one held note, not a new strike)

# No automatic time-signature estimation: librosa has no downbeat/meter detection
# built in (checked its API directly), and the two real alternatives evaluated both
# failed on this platform — madmom needed a from-source Cython/MSVC build plus
# hand-patching 3 separate Python 3.11/numpy compatibility breaks in the installed
# package (not tracked by requirements.txt, and even after all that, the result
# measured well by note-overlap counts but sounded worse by ear on a full listen);
# Essentia has no Windows wheel at all and its source build fails immediately with
# an internal error in its own setup.py. 4/4 is used unconditionally instead — by far
# the most common meter, and a time-signature picker is planned in the frontend
# correction UI (see docs/frontend-plan.md) so the user can override it, same as the
# planned tempo picker.
DEFAULT_TIME_SIGNATURE = "4/4"

# How far a stem's own detected tempo may drift from the reference tempo (as a
# ratio, tempo / reference) before it's considered "disagreeing" and gets
# re-quantized against the reference instead of its own detection. Generous enough
# to absorb normal beat-tracker jitter between takes on genuinely-the-same tempo,
# tight enough to still catch real octave errors (ratio ~2.0 or ~0.5) and other
# gross mismatches (e.g. a sparse/bleed-heavy stem's tempo detection going wild).
TEMPO_AGREEMENT_TOLERANCE = 0.08  # +/- 8%
# Ratios close to these (within TEMPO_AGREEMENT_TOLERANCE) are treated as the
# classic beat-tracker octave error (locked onto the eighth-note or half-note pulse
# instead of the quarter-note pulse) rather than a genuine tempo mismatch — flagged
# distinctly in reconcile_tempo()'s output since it's a well-understood, common case.
OCTAVE_RATIOS = (2.0, 0.5)

# How far a re-quantized stem's NOTATED duration (last note's offset_beat, converted
# back to seconds via the tempo it was just labeled with) may differ from the real
# audio's actual duration before the forced tempo is rejected as invalid for that
# stem. This catches a real, confirmed bug: forcing tempo_bpm onto a stem does NOT
# rebuild its beat grid from that tempo — _beat_grid()/_time_to_beat() always anchor
# to the stem's own real detected beat positions, only the printed BPM number
# changes. If the reference tempo disagrees with a stem's own tempo by roughly an
# octave, forcing it produces an internally-INCONSISTENT result: real beat spacing
# from the stem's own (correct) detection, but labeled with a tempo that implies a
# different spacing — so the notation's claimed total playback time can end up
# wildly shorter (or longer) than the real audio. Confirmed on real data: forcing
# 4 stems onto one sample's reference tempo dropped their notated-duration-vs-real-
# audio ratio to 0.46-0.67 (i.e. the notation claims to finish 33-54% early even
# though it's the same real audio). A stem failing this check keeps its OWN tempo
# instead of the reference — its own tempo is evidently the musically correct one
# for that stem specifically, not a disagreement needing correction.
DURATION_RATIO_TOLERANCE = 0.15  # +/- 15%


def detect_tempo(audio_path: str) -> float:
    """Detect tempo (BPM) from an audio file using librosa's beat tracker.

    Factored out of run() so the same detection logic can be run once against the
    original, pre-separation mixed audio (the most reliable single source for a
    "reference" tempo — full signal, not a lossy separated stem) and reused by
    reconcile_tempo() below, independent of any one stem's own quantization pass.
    """
    y, sr = librosa.load(audio_path, sr=None)
    detected_tempo, _beat_frames = librosa.beat.beat_track(y=y, sr=sr, units="time")
    return float(np.asarray(detected_tempo).item())


def reconcile_tempo(
    reference_tempo_bpm: float,
    stem_results: dict,
    stem_note_events: dict,
    stem_audio_paths: dict,
    input_stem: Optional[str] = None,
) -> dict:
    """Re-quantize any stem whose own detected tempo disagrees with the reference.

    stem_results: dict of stem_name -> QuantizationResult (already quantized once,
    each against its own independently-detected tempo).
    stem_note_events: dict of stem_name -> the same stem's raw (seconds-based)
    NoteEvent list used to produce that QuantizationResult — re-quantization must
    start from these, not from the already-quantized (beat-based) notes, since
    re-running quantization_service.run() needs real onset/offset times in seconds.
    stem_audio_paths: dict of stem_name -> that stem's own separated audio file.
    Still needed even when forcing tempo_bpm: run() uses the audio to find real beat
    POSITIONS (the shape of the tempo curve within this stem's own audio), and only
    treats tempo_bpm as which BPM number to label those positions with — it does not
    substitute the reference stem's beat positions for this stem's own.
    input_stem: see run()'s docstring — forwarded to the re-quantization call so its
    saved output lands in the same per-sample subfolder as the first pass.

    A stem's tempo is considered agreeing with the reference if their ratio is
    within TEMPO_AGREEMENT_TOLERANCE of 1.0. Anything else (including the classic
    octave-doubling/halving error) is a CANDIDATE for re-quantizing against the
    reference — but only actually applied if doing so passes the duration-ratio
    sanity check (see DURATION_RATIO_TOLERANCE above): the re-quantized result's
    notated total duration must still be close to the real audio's actual duration.
    If forcing the reference tempo would make the notation claim a wildly different
    playback length than the real audio actually is, that's evidence the reference
    is wrong FOR THIS STEM specifically (not that the stem disagrees) — its own
    tempo is kept instead.

    Returns a new dict of stem_name -> QuantizationResult (reconciled), plus prints
    nothing itself — callers are expected to log/report using the returned data.
    """
    if reference_tempo_bpm <= 0:
        # librosa.beat.beat_track() can return 0 BPM on a degenerate/ambiguous
        # signal (confirmed possible via a real API run that hit this — not
        # reproducible on demand, likely TensorFlow/librosa run-to-run variance
        # rather than something deterministic about the specific file). A real
        # tempo can never be <= 0, so there's nothing valid to reconcile against;
        # skip reconciliation entirely and let every stem keep its own tempo
        # rather than raising (dividing by a zero/negative reference below) and
        # failing the whole job over what's ultimately a labeling step.
        print(
            f"  [tempo] reference tempo is {reference_tempo_bpm:.2f} BPM (invalid) - "
            f"skipping reconciliation, every stem keeps its own tempo"
        )
        return dict(stem_results)

    reconciled = {}
    for stem_name, result in stem_results.items():
        ratio = result.tempo_bpm / reference_tempo_bpm
        agrees = abs(ratio - 1.0) <= TEMPO_AGREEMENT_TOLERANCE
        if agrees:
            reconciled[stem_name] = result
            continue

        is_octave_error = any(abs(ratio - r) <= TEMPO_AGREEMENT_TOLERANCE for r in OCTAVE_RATIOS)
        reason = "octave error" if is_octave_error else "disagrees with reference"

        candidate = run(
            stem_note_events[stem_name],
            audio_path=stem_audio_paths[stem_name],
            tempo_bpm=reference_tempo_bpm,
            input_stem=input_stem,
        )

        real_duration_seconds = _audio_duration_seconds(stem_audio_paths[stem_name])
        duration_ok = _passes_duration_check(candidate, real_duration_seconds)

        if duration_ok:
            print(
                f"  [tempo] {stem_name}: {result.tempo_bpm:.2f} BPM vs. reference "
                f"{reference_tempo_bpm:.2f} BPM (ratio {ratio:.2f}, {reason}) - "
                f"re-quantizing against the reference tempo"
            )
            reconciled[stem_name] = candidate
        else:
            print(
                f"  [tempo] {stem_name}: {result.tempo_bpm:.2f} BPM vs. reference "
                f"{reference_tempo_bpm:.2f} BPM (ratio {ratio:.2f}, {reason}) - "
                f"reference REJECTED, notated duration would mismatch the real audio "
                f"length too much - keeping {stem_name}'s own tempo instead"
            )
            reconciled[stem_name] = result

    return reconciled


def _audio_duration_seconds(audio_path: str) -> float:
    """Real duration (seconds) of an audio file, via its sample count/rate — much
    cheaper than a full librosa.load() since only the header/frame count is read."""
    info = sf.info(audio_path)
    return info.frames / info.samplerate


def _passes_duration_check(result: QuantizationResult, real_duration_seconds: float) -> bool:
    """Whether a QuantizationResult's total notated duration (last note's
    offset_beat, converted to seconds via its own tempo_bpm) is close enough to
    the real audio's actual duration — see DURATION_RATIO_TOLERANCE."""
    if not result.notes or real_duration_seconds <= 0:
        return True  # nothing to check against; don't block on an edge case
    notated_seconds = max(n.offset_beat for n in result.notes) * 60.0 / result.tempo_bpm
    ratio = notated_seconds / real_duration_seconds
    return abs(ratio - 1.0) <= DURATION_RATIO_TOLERANCE


def run(
    note_events: List[NoteEvent],
    audio_path: str,
    tempo_bpm: Optional[float] = None,
    input_stem: Optional[str] = None,
) -> QuantizationResult:
    """Snap raw note events onto a beat grid derived from real detected beat positions.

    Basic Pitch sometimes emits one continuously-held/sustained note as two or more
    back-to-back same-pitch fragments (touching or nearly touching in time). These are
    merged into a single note first (see _merge_sustained_fragments) using a decaying-
    velocity check to tell a real sustain apart from a genuine repeated re-attack.

    Each note's onset/offset (in seconds) is mapped to a fractional beat position by
    interpolating between the two nearest detected beats (extrapolating at the clip's
    edges), so the grid follows the actual tempo curve instead of assuming one constant
    BPM for the whole clip. The result is then snapped to a 16th-note subdivision.
    Notes in the bottom CONFIDENCE_DROP_PERCENTILE of this clip's confidence
    distribution are dropped, along with any note that collapses to zero duration
    after snapping.

    If tempo_bpm is given explicitly (e.g. by reconcile_tempo(), forcing a stem onto
    a shared reference tempo instead of its own detection), audio_path is still used
    for beat POSITIONS (the shape of the tempo curve — where the beats actually fall
    in time), just not for what BPM number to treat those beats as.

    input_stem: the ORIGINAL sample's filename stem (e.g. "sample5"), not
    audio_path's own stem (e.g. "drums") — when given, nests the saved result
    under storage/intermediate/<input_stem>/ instead of writing flat. See
    transcription_service.run()'s docstring for the full reasoning (multi-stem
    runs on different samples would otherwise overwrite each other's same-named
    stem files).
    """
    note_events = _merge_sustained_fragments(note_events)

    y, sr = librosa.load(audio_path, sr=None)
    detected_tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units="time")
    detected_tempo = float(np.asarray(detected_tempo).item())
    if tempo_bpm is None:
        tempo_bpm = detected_tempo

    beat_times, beat_indices = _beat_grid(beat_frames, y, sr, tempo_bpm)

    confidence_floor = (
        float(np.percentile([n.confidence for n in note_events], CONFIDENCE_DROP_PERCENTILE))
        if note_events
        else 0.0
    )

    quantized_notes = []
    for note in note_events:
        if note.confidence < confidence_floor:
            continue

        onset_beat = _snap(_time_to_beat(note.onset, beat_times, beat_indices))
        offset_beat = _snap(_time_to_beat(note.offset, beat_times, beat_indices))

        if offset_beat <= onset_beat:
            continue

        quantized_notes.append(
            QuantizedNoteEvent(
                pitch=note.pitch,
                onset_beat=onset_beat,
                offset_beat=offset_beat,
                duration_beats=offset_beat - onset_beat,
                velocity=note.velocity,
                confidence=note.confidence,
                stem_label=note.stem_label,
            )
        )

    # transcription_service.run() is called once per stem, so every note in
    # note_events shares the same stem_label — take it from the first note
    # rather than re-deriving it, and fall back to "unknown" for an empty list.
    result_stem_label = note_events[0].stem_label if note_events else "unknown"

    result = QuantizationResult(
        tempo_bpm=tempo_bpm,
        stem_label=result_stem_label,
        time_signature=DEFAULT_TIME_SIGNATURE,
        notes=quantized_notes,
    )

    intermediate_dir = stem_output_dir(INTERMEDIATE_DIR, input_stem)
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    result_path = intermediate_dir / f"{Path(audio_path).stem}.quantized.json"
    result_path.write_text(result.model_dump_json(indent=2))

    return result


def load_quantization_result(stem_name: str, input_stem: Optional[str] = None) -> QuantizationResult:
    """Load a previously saved QuantizationResult from storage/intermediate/.

    input_stem: see run()'s docstring — pass the same value used when this stem
    was quantized, to find it under the matching per-sample subfolder.
    """
    result_path = stem_output_dir(INTERMEDIATE_DIR, input_stem) / f"{stem_name}.quantized.json"
    if not result_path.exists():
        raise FileNotFoundError(
            f"No saved quantization result for '{stem_name}' at {result_path}. Run quantization first."
        )
    return QuantizationResult.model_validate_json(result_path.read_text())


def _merge_sustained_fragments(note_events: List[NoteEvent]) -> List[NoteEvent]:
    """Merge same-pitch note fragments that are really one continuous held note.

    Basic Pitch occasionally emits a sustained note as two+ back-to-back notes at the
    same pitch (near-zero gap between one's offset and the next's onset) rather than
    one continuous note. Distinguish this from a genuine repeated re-attack using the
    physical signature of a struck note: a real strike decays (velocity flat or drops)
    into its sustain tail, while a fresh key press produces a new, often louder, onset.
    Only merge consecutive same-pitch fragments where the gap is small AND velocity
    doesn't increase; chains of 3+ fragments merge transitively into one note.
    """
    by_pitch: dict = {}
    for i, n in enumerate(note_events):
        by_pitch.setdefault(n.pitch, []).append((i, n))

    merged_away = set()
    replacements: dict = {}

    for pitch, indexed_notes in by_pitch.items():
        indexed_notes.sort(key=lambda pair: pair[1].onset)
        current_idx, current = indexed_notes[0]
        for next_idx, nxt in indexed_notes[1:]:
            gap = nxt.onset - current.offset
            is_sustain_tail = (
                -0.01 <= gap <= SUSTAIN_MERGE_GAP_SECONDS
                and nxt.velocity - current.velocity <= SUSTAIN_MERGE_MAX_VELOCITY_INCREASE
            )
            if is_sustain_tail:
                current = NoteEvent(
                    pitch=current.pitch,
                    onset=current.onset,
                    offset=nxt.offset,
                    duration=nxt.offset - current.onset,
                    velocity=current.velocity,
                    confidence=max(current.confidence, nxt.confidence),
                    stem_label=current.stem_label,
                )
                merged_away.add(next_idx)
            else:
                replacements[current_idx] = current
                current_idx, current = next_idx, nxt
        replacements[current_idx] = current

    return [replacements[i] for i in range(len(note_events)) if i not in merged_away]


def _beat_grid(beat_frames: np.ndarray, y: np.ndarray, sr: int, fallback_tempo: float):
    """Return (beat_times, beat_indices) arrays for _time_to_beat.

    Falls back to a synthetic fixed-tempo grid if librosa detects too few beats to
    interpolate against (e.g. a very short or ambiguous clip).
    """
    if len(beat_frames) >= 2:
        return np.asarray(beat_frames, dtype=float), np.arange(len(beat_frames), dtype=float)

    duration = len(y) / sr
    seconds_per_beat = 60.0 / fallback_tempo
    n_beats = max(2, int(duration / seconds_per_beat) + 1)
    synthetic_times = np.arange(n_beats) * seconds_per_beat
    return synthetic_times, np.arange(n_beats, dtype=float)


def _time_to_beat(t: float, beat_times: np.ndarray, beat_indices: np.ndarray) -> float:
    """Map a time in seconds to a fractional beat position, extrapolating at the edges
    (np.interp alone clamps out-of-range values instead of extrapolating, which would
    incorrectly collapse notes before the first/after the last detected beat)."""
    if t < beat_times[0]:
        interval = beat_times[1] - beat_times[0]
        extrapolated = beat_indices[0] - (beat_times[0] - t) / interval
        # Extrapolating backward using the interval between the first two detected
        # beats breaks down when the first detected beat itself is far from t=0 (e.g.
        # a mostly-silent separated stem where librosa's beat tracker only picks up
        # rhythm near the end) — the tight interval between beats 0 and 1 gets
        # projected across that whole silent gap, producing wildly negative beat
        # positions (observed: -101 beats on a real Demucs "piano" stem whose first
        # detected beat was 42s into a 53s clip). A note genuinely can't sound before
        # the clip starts, so floor the result at 0 rather than let it run away.
        return max(0.0, extrapolated)
    if t > beat_times[-1]:
        interval = beat_times[-1] - beat_times[-2]
        return beat_indices[-1] + (t - beat_times[-1]) / interval
    return float(np.interp(t, beat_times, beat_indices))


def _snap(beat: float) -> float:
    return round(beat / GRID_SUBDIVISION) * GRID_SUBDIVISION


def to_midi(result: QuantizationResult, output_name: str, input_stem: Optional[str] = None) -> Path:
    """Render a QuantizationResult back to a MIDI file for listening/inspection.

    Converts beat-grid timings back to seconds using result.tempo_bpm, so the
    output can be A/B compared against the raw transcription MIDI.

    input_stem: see run()'s docstring — nests under storage/midi/quantized/<input_stem>/
    instead of writing flat, when given.
    """
    seconds_per_beat = 60.0 / result.tempo_bpm

    midi = pretty_midi.PrettyMIDI(initial_tempo=result.tempo_bpm)
    instrument = pretty_midi.Instrument(program=0)  # acoustic grand piano

    for note in result.notes:
        instrument.notes.append(
            pretty_midi.Note(
                velocity=note.velocity,
                pitch=note.pitch,
                start=note.onset_beat * seconds_per_beat,
                end=note.offset_beat * seconds_per_beat,
            )
        )

    midi.instruments.append(instrument)

    quantized_midi_dir = stem_output_dir(QUANTIZED_MIDI_DIR, input_stem)
    quantized_midi_dir.mkdir(parents=True, exist_ok=True)
    output_path = quantized_midi_dir / f"{output_name}.mid"
    midi.write(str(output_path))

    return output_path
