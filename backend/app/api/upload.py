"""POST /upload — accept an audio file, kick off Demucs separation as a
background job, return immediately with a job ID to poll (see transcribe.py's
GET /status/{job_id}).

Async job model, not a blocking request: even just separation takes real time,
and the full pipeline (separation + transcribing 6 stems + quantization +
export) takes several minutes total — a single blocking HTTP request that long
risks proxy/browser timeouts and gives the frontend no way to show real progress.

Runs ONLY phase 1 (separation) before pausing at AWAITING_REVIEW — this is the
first of two review checkpoints (see app/schemas/job.py's Checkpoint enum and
app/services/pipeline_service.py's module docstring for the full design). The
user reviews the separated stems (e.g. via GET /audio/{job_id}/{stem}) and calls
POST /jobs/{job_id}/continue (transcribe.py) to run transcription next, rather
than the whole pipeline running start-to-finish automatically.
"""

import traceback
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, UploadFile

from app.config.settings import UPLOADS_DIR
from app.schemas.job import Checkpoint, Job, JobStage, JobStatus, SeparationCheckpointStem
from app.services import job_service, pipeline_service

router = APIRouter(tags=["upload"])

ALLOWED_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a"}


@router.post("/upload", response_model=Job)
async def upload_audio(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    skip_separation: bool = Form(default=False),
    single_instrument_label: Optional[str] = Form(default=None),
) -> Job:
    """
    skip_separation / single_instrument_label: set by the client when the
    upload is a single-instrument recording (solo vocal, solo guitar, etc.) —
    running Demucs separation on audio that was never actually a mix just
    wastes several minutes and risks phantom content in the other 5 mostly-
    silent stems (bleed/noise Basic Pitch could still find "notes" in). See
    pipeline_service.py's run_until_separation(skip_separation=...) /
    run_transcription_phase(single_instrument_label=...) for how this changes
    the pipeline; SINGLE_INSTRUMENT_LABELS there is the source of truth for
    valid label values, checked here so a bad value 400s immediately instead
    of failing later inside a background task where the only signal is
    job.status becoming FAILED with a traceback to dig through.
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type {suffix!r}. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
        )

    if skip_separation:
        if single_instrument_label not in pipeline_service.SINGLE_INSTRUMENT_LABELS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"single_instrument_label={single_instrument_label!r} is required and must be one of "
                    f"{sorted(pipeline_service.SINGLE_INSTRUMENT_LABELS)} when skip_separation=true"
                ),
            )

    # Job is created before the file is written (input_audio_path filled in via
    # update_job() right after) so the saved file can be named after the job ID —
    # two uploads sharing an original filename should never collide on disk.
    job = job_service.create_job(
        original_filename=file.filename or "upload",
        input_audio_path="",
        skip_separation=skip_separation,
        single_instrument_label=single_instrument_label,
    )

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    saved_path = UPLOADS_DIR / f"{job.job_id}{suffix}"
    contents = await file.read()
    saved_path.write_bytes(contents)

    job = job_service.update_job(
        job.job_id,
        status=JobStatus.PENDING,
        stage=JobStage.UPLOADED,
        input_audio_path=str(saved_path),
    )

    background_tasks.add_task(_run_separation_phase, job.job_id)

    return job


def _run_separation_phase(job_id: str) -> None:
    """Runs in FastAPI's background task pool — phase 1 only (separation)."""
    job = job_service.get_job(job_id)
    if job is None:
        return

    def on_stage(stage: JobStage, message: str) -> None:
        job_service.update_job(job_id, status=JobStatus.PROCESSING, stage=stage)

    try:
        job_service.update_job(job_id, status=JobStatus.PROCESSING, stage=JobStage.SEPARATING)
        separation_result = pipeline_service.run_until_separation(
            job.input_audio_path, on_stage=on_stage, skip_separation=job.skip_separation
        )
        job_service.update_job(
            job_id,
            status=JobStatus.AWAITING_REVIEW,
            checkpoint=Checkpoint.AFTER_SEPARATION,
            separation_checkpoint=[
                SeparationCheckpointStem(stem_name=name) for name in separation_result.stem_names
            ],
            reference_tempo_bpm=separation_result.reference_tempo_bpm,
            reference_beat_times=separation_result.reference_beat_times,
        )
    except Exception:  # noqa: BLE001 — job failures must be captured, not crash the worker
        # Full traceback, not just str(e) — a bare exception message (e.g.
        # "float division by zero") gives no way to find WHERE in the pipeline it
        # happened without reproducing the failure separately. Also printed to the
        # server log so it shows up in real time, not just when polled via the API.
        tb = traceback.format_exc()
        print(tb)
        job_service.update_job(job_id, status=JobStatus.FAILED, error=tb)
