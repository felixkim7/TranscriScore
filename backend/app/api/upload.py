"""POST /upload — accept an audio file, kick off the full pipeline as a
background job, return immediately with a job ID to poll (see transcribe.py's
GET /status/{job_id} and GET /result/{job_id}).

Async job model, not a blocking request: the full pipeline (Demucs separation +
transcribing 6 stems) takes several minutes per file — a single blocking HTTP
request that long risks proxy/browser timeouts and gives the frontend no way to
show real progress.
"""

import traceback
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile

from app.config.settings import UPLOADS_DIR
from app.schemas.job import Job, JobStage, JobStatus
from app.services import job_service, pipeline_service

router = APIRouter(tags=["upload"])

ALLOWED_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a"}


@router.post("/upload", response_model=Job)
async def upload_audio(file: UploadFile, background_tasks: BackgroundTasks) -> Job:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type {suffix!r}. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
        )

    # Job is created before the file is written (input_audio_path filled in via
    # update_job() right after) so the saved file can be named after the job ID —
    # two uploads sharing an original filename should never collide on disk.
    job = job_service.create_job(original_filename=file.filename or "upload", input_audio_path="")

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

    background_tasks.add_task(_process_job, job.job_id)

    return job


def _process_job(job_id: str) -> None:
    """Runs in FastAPI's background task pool — the actual pipeline execution."""
    job = job_service.get_job(job_id)
    if job is None:
        return

    def on_stage(stage: JobStage, message: str) -> None:
        job_service.update_job(job_id, status=JobStatus.PROCESSING, stage=stage)

    try:
        job_service.update_job(job_id, status=JobStatus.PROCESSING, stage=JobStage.SEPARATING)
        result = pipeline_service.run_full_pipeline(job.input_audio_path, on_stage=on_stage)
        job_service.update_job(job_id, status=JobStatus.DONE, result=result)
    except Exception:  # noqa: BLE001 — job failures must be captured, not crash the worker
        # Full traceback, not just str(e) — a bare exception message (e.g.
        # "float division by zero") gives no way to find WHERE in the pipeline it
        # happened without reproducing the failure separately. Also printed to the
        # server log so it shows up in real time, not just when polled via the API.
        tb = traceback.format_exc()
        print(tb)
        job_service.update_job(job_id, status=JobStatus.FAILED, error=tb)
