from pydantic import BaseModel


class NoteEvent(BaseModel):
    pitch: int
    onset: float
    offset: float
    duration: float
    velocity: int
    confidence: float


class QuantizedNoteEvent(BaseModel):
    pitch: int
    onset_beat: float
    offset_beat: float
    duration_beats: float
    velocity: int
    confidence: float


class QuantizationResult(BaseModel):
    tempo_bpm: float
    notes: list[QuantizedNoteEvent]
