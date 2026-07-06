import json
from pathlib import Path
from typing import List, Optional

import librosa
import pretty_midi

from app.config.settings import INTERMEDIATE_DIR, QUANTIZED_MIDI_DIR
from app.schemas.transcription import NoteEvent, QuantizationResult, QuantizedNoteEvent

GRID_SUBDIVISION = 0.25  # snap to 16th notes (in beats)
MIN_CONFIDENCE = 0.2


def run(
    note_events: List[NoteEvent],
    audio_path: str,
    tempo_bpm: Optional[float] = None,
) -> QuantizationResult:
    """Snap raw note events onto a fixed beat grid at a single global tempo.

    Backbone version: one tempo estimate for the whole clip, fixed 16th-note grid,
    drop notes that vanish after snapping or fall below a low confidence floor.
    """
    if tempo_bpm is None:
        y, sr = librosa.load(audio_path, sr=None)
        tempo_bpm, _ = librosa.beat.beat_track(y=y, sr=sr)
        tempo_bpm = float(tempo_bpm)

    beats_per_second = tempo_bpm / 60.0

    quantized_notes = []
    for note in note_events:
        if note.confidence < MIN_CONFIDENCE:
            continue

        onset_beat = _snap(note.onset * beats_per_second)
        offset_beat = _snap(note.offset * beats_per_second)

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
