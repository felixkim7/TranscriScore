"""File-backed job store for the async upload -> process -> result API (step 8).

One JSON file per job at storage/jobs/<job_id>.json — chosen over a database since
app/models/'s purpose (DB models vs. ML model cache) was never decided, and this
project doesn't otherwise need real DB infrastructure. Survives process restarts,
unlike a pure in-memory dict, and matches the project's existing convention of
routing all IO through storage/ (see CLAUDE.md's "Storage layout").

Not process-safe against true concurrent writers (read-modify-write on the same
job's JSON file could race) — acceptable for a single-worker dev server; would need
a real lock or a database if this ever runs with multiple worker processes.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.config.settings import JOBS_DIR
from app.schemas.job import Job, JobStage, JobStatus


def create_job(original_filename: str, input_audio_path: str) -> Job:
    job = Job(
        job_id=str(uuid.uuid4()),
        original_filename=original_filename,
        input_audio_path=input_audio_path,
    )
    _save(job)
    return job


def get_job(job_id: str) -> Optional[Job]:
    job_path = JOBS_DIR / f"{job_id}.json"
    if not job_path.exists():
        return None
    return Job.model_validate_json(job_path.read_text())


def update_job(
    job_id: str,
    status: Optional[JobStatus] = None,
    stage: Optional[JobStage] = None,
    error: Optional[str] = None,
    result=None,
    input_audio_path: Optional[str] = None,
) -> Job:
    job = get_job(job_id)
    if job is None:
        raise FileNotFoundError(f"No job found with id {job_id}")

    if status is not None:
        job.status = status
    if stage is not None:
        job.stage = stage
    if error is not None:
        job.error = error
    if result is not None:
        job.result = result
    if input_audio_path is not None:
        job.input_audio_path = input_audio_path
    job.updated_at = datetime.now(timezone.utc)

    _save(job)
    return job


def _save(job: Job) -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    job_path = JOBS_DIR / f"{job.job_id}.json"
    job_path.write_text(job.model_dump_json(indent=2))
