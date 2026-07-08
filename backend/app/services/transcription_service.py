import json
from pathlib import Path
from typing import List

from basic_pitch.inference import predict

from app.config.settings import INTERMEDIATE_DIR, MIDI_DIR
from app.schemas.transcription import NoteEvent


def run(input_path: str, stem_label: str = "unknown") -> List[NoteEvent]:
    """Transcribe an audio file into note events using Spotify Basic Pitch.

    """Transcribe an audio file into note events using Spotify Basic Pitch.

    Writes the resulting MIDI to storage/midi/ and the note events as JSON to
    storage/intermediate/ (so later stages can be re-run without re-transcribing).

    Args:
        input_path: path to the audio stem to transcribe.
        stem_label: role of this stem (e.g. "piano_accompaniment"), typically
            from classification_service.classify_stem(). Defaults to
            "unknown" so existing callers that don't pass it keep working.
    """

    """
    audio_path = Path(input_path)

    _, midi_data, raw_note_events = predict(audio_path)

    MIDI_DIR.mkdir(parents=True, exist_ok=True)
    midi_path = MIDI_DIR / f"{audio_path.stem}.mid"
    midi_data.write(str(midi_path))

    note_events = [
        NoteEvent(
            pitch=pitch,
            onset=start,
            offset=end,
            duration=end - start,
            velocity=round(amplitude * 127),
            confidence=amplitude,
            stem_label=stem_label,
        )
        for start, end, pitch, amplitude, _pitch_bends in raw_note_events
    ]

    INTERMEDIATE_DIR.mkdir(parents=True, exist_ok=True)
    notes_path = INTERMEDIATE_DIR / f"{audio_path.stem}.notes.json"
    notes_path.write_text(
        json.dumps([note.model_dump() for note in note_events], indent=2)
    )

    return note_events


def load_note_events(stem_name: str) -> List[NoteEvent]:
    """Load previously transcribed note events from storage/intermediate/."""
    notes_path = INTERMEDIATE_DIR / f"{stem_name}.notes.json"
    if not notes_path.exists():
        raise FileNotFoundError(
            f"No saved note events for '{stem_name}' at {notes_path}. Run transcription first."
        )
    raw = json.loads(notes_path.read_text())
    return [NoteEvent(**item) for item in raw]
