from pydantic import BaseModel


class NoteEvent(BaseModel):
    pitch: int
    onset: float
    offset: float
    duration: float
    velocity: int
    confidence: float
