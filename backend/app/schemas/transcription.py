from pydantic import BaseModel


class NoteEvent(BaseModel):
    pitch: int
    onset: float
    offset: float
    duration: float
    velocity: int
    confidence: float
    stem_label: str = "unknown"


class QuantizedNoteEvent(BaseModel):
    pitch: int
    onset_beat: float
    offset_beat: float
    duration_beats: float
    velocity: int
    confidence: float
    stem_label: str = "unknown"


class QuantizationResult(BaseModel):
    tempo_bpm: float
    stem_label: str = "unknown"
    time_signature: str = "4/4"
    notes: list[QuantizedNoteEvent]
