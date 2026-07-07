from pathlib import Path
from typing import List

from basic_pitch.inference import predict

from app.config.settings import MIDI_DIR
from app.schemas.transcription import NoteEvent


def run(input_path: str, stem_label: str = "unknown") -> List[NoteEvent]:
    """Transcribe an audio file into note events using Spotify Basic Pitch.

    Writes the resulting MIDI to storage/midi/ and returns the note events.

    Args:
        input_path: path to the audio stem to transcribe.
        stem_label: role of this stem (e.g. "piano_accompaniment"), typically
            from classification_service.classify_stem(). Defaults to
            "unknown" so existing callers that don't pass it keep working.
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

    return note_events
