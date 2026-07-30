from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    # The pipeline has genuinely stopped and is waiting for a client to call
    # POST /jobs/{job_id}/continue — NOT the same as PROCESSING with a slow
    # stage. See job_service.py / pipeline_service.py's phase functions.
    AWAITING_REVIEW = "awaiting_review"
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


class Checkpoint(str, Enum):
    """Which review checkpoint a job is currently paused at (only meaningful
    when status is AWAITING_REVIEW) — determines what
    POST /jobs/{job_id}/continue runs next. See pipeline_service.py's
    run_until_separation() / run_transcription_phase() / run_final_phase()."""

    AFTER_SEPARATION = "after_separation"
    AFTER_TRANSCRIPTION = "after_transcription"


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


class SeparationCheckpointStem(BaseModel):
    """One stem's info at the after-separation checkpoint — enough for the
    frontend to list/play each stem before committing to transcription."""

    stem_name: str


class TranscriptionCheckpointStem(BaseModel):
    """One stem's info at the after-transcription checkpoint — enough for the
    frontend to show what got transcribed (raw note count, own tempo) before
    committing to quantization/tempo reconciliation/export."""

    stem_name: str
    stem_label: str
    note_count: int


class Job(BaseModel):
    job_id: str
    status: JobStatus = JobStatus.PENDING
    stage: Optional[JobStage] = None
    checkpoint: Optional[Checkpoint] = None
    original_filename: str
    input_audio_path: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error: Optional[str] = None
    result: Optional[JobResult] = None

    # Populated once each checkpoint is reached — None before that point.
    separation_checkpoint: Optional[List[SeparationCheckpointStem]] = None
    transcription_checkpoint: Optional[List[TranscriptionCheckpointStem]] = None

    # Internal bookkeeping needed to resume the pipeline (which stem got which
    # label after separation) — not really "job status" but has to live
    # somewhere durable across the pause, and job_service.py is already the
    # only thing that persists this job. Not returned to API callers as part
    # of the public Job shape's meaningful fields, but IS part of the JSON —
    # simplest to just let it round-trip rather than build a second storage
    # mechanism for one dict.
    stem_labels: Optional[Dict[str, str]] = None

    # Tempo/beat tracking, detected once from the ORIGINAL pre-separation audio
    # during phase 1 (see pipeline_service.run_until_separation()'s
    # SeparationPhaseResult) — the fullest, most reliable single signal, same
    # reasoning as run_final_phase()'s reference-tempo reconciliation, just run
    # earlier. Populated as soon as separation finishes; NOT currently consumed
    # by transcription/quantization anywhere — detected and persisted for later
    # use, per explicit instruction not to wire it in yet.
    reference_tempo_bpm: Optional[float] = None
    reference_beat_times: Optional[List[float]] = None

    # Set from POST /upload's form fields (see app/api/upload.py) when the
    # user indicates this recording has only one instrument/voice, so Demucs
    # separation should be skipped entirely — see pipeline_service.py's
    # run_until_separation(skip_separation=...) / run_transcription_phase(
    # single_instrument_label=...). single_instrument_label is required
    # (and validated against pipeline_service.SINGLE_INSTRUMENT_LABELS at the
    # API layer, not here, to avoid a schemas->services import) whenever
    # skip_separation is True; both stay at their defaults for the normal
    # multi-stem path.
    skip_separation: bool = False
    single_instrument_label: Optional[str] = None

    model_config = {"use_enum_values": False}
