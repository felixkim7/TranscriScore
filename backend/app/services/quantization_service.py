import json
from pathlib import Path
from typing import List, Optional

import librosa
import numpy as np
import pretty_midi

from app.config.settings import INTERMEDIATE_DIR, QUANTIZED_MIDI_DIR
from app.schemas.transcription import NoteEvent, QuantizationResult, QuantizedNoteEvent

GRID_SUBDIVISION = 0.25  # snap to 16th notes (in beats)
CONFIDENCE_DROP_PERCENTILE = 10  # drop the bottom 10% of notes by confidence


def run(
    note_events: List[NoteEvent],
    audio_path: str,
    tempo_bpm: Optional[float] = None,
) -> QuantizationResult:
    """Snap raw note events onto a beat grid derived from real detected beat positions.

    Each note's onset/offset (in seconds) is mapped to a fractional beat position by
    interpolating between the two nearest detected beats (extrapolating at the clip's
    edges), so the grid follows the actual tempo curve instead of assuming one constant
    BPM for the whole clip. The result is then snapped to a 16th-note subdivision.
    Notes in the bottom CONFIDENCE_DROP_PERCENTILE of this clip's confidence
    distribution are dropped, along with any note that collapses to zero duration
    after snapping.
    """
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
            )
        )

    result = QuantizationResult(tempo_bpm=tempo_bpm, notes=quantized_notes)

    INTERMEDIATE_DIR.mkdir(parents=True, exist_ok=True)
    result_path = INTERMEDIATE_DIR / f"{Path(audio_path).stem}.quantized.json"
    result_path.write_text(result.model_dump_json(indent=2))

    return result


def load_quantization_result(stem_name: str) -> QuantizationResult:
    """Load a previously saved QuantizationResult from storage/intermediate/."""
    result_path = INTERMEDIATE_DIR / f"{stem_name}.quantized.json"
    if not result_path.exists():
        raise FileNotFoundError(
            f"No saved quantization result for '{stem_name}' at {result_path}. Run quantization first."
        )
    return QuantizationResult.model_validate_json(result_path.read_text())


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
        return beat_indices[0] - (beat_times[0] - t) / interval
    if t > beat_times[-1]:
        interval = beat_times[-1] - beat_times[-2]
        return beat_indices[-1] + (t - beat_times[-1]) / interval
    return float(np.interp(t, beat_times, beat_indices))


def _snap(beat: float) -> float:
    return round(beat / GRID_SUBDIVISION) * GRID_SUBDIVISION


def to_midi(result: QuantizationResult, output_name: str) -> Path:
    """Render a QuantizationResult back to a MIDI file for listening/inspection.

    Converts beat-grid timings back to seconds using result.tempo_bpm, so the
    output can be A/B compared against the raw transcription MIDI.
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

    QUANTIZED_MIDI_DIR.mkdir(parents=True, exist_ok=True)
    output_path = QUANTIZED_MIDI_DIR / f"{output_name}.mid"
    midi.write(str(output_path))

    return output_path
