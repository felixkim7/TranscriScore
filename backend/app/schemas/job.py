from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class JobStage(str, Enum):
    """Pipeline stages, in order — used for progress reporting via GET /status/{job_id}."""

    UPLOADED = "uploaded"
    SEPARATING = "separating"
    TRANSCRIBING = "transcribing"
    QUANTIZING = "quantizing"
    RECONCILING_TEMPO = "reconciling_tempo"
    RENDERING_MUSICXML = "rendering_musicxml"
    EXPORTING = "exporting"


class StemResult(BaseModel):
    stem_name: str
    stem_label: str
    tempo_bpm: float
    note_count: int
    musicxml_path: str


class JobResult(BaseModel):
    combined_musicxml_path: str
    combined_mscz_path: str
    stems: List[StemResult]


class Job(BaseModel):
    job_id: str
    status: JobStatus = JobStatus.PENDING
    stage: Optional[JobStage] = None
    original_filename: str
    input_audio_path: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error: Optional[str] = None
    result: Optional[JobResult] = None

    model_config = {"use_enum_values": False}
