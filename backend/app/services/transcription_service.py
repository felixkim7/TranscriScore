from pathlib import Path
from typing import List

from basic_pitch.inference import predict

from app.config.settings import MIDI_DIR
from app.schemas.transcription import NoteEvent


def run(input_path: str) -> List[NoteEvent]:
    """Transcribe an audio file into note events using Spotify Basic Pitch.

    Writes the resulting MIDI to storage/midi/ and returns the note events.
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
        )
        for start, end, pitch, amplitude, _pitch_bends in raw_note_events
    ]

    return note_events
