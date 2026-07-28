"""GET /status/{job_id} — poll a job's current stage/status.
GET /result/{job_id} — once a job is done, its combined MusicXML/MSCZ paths and
per-stem breakdown (see app/schemas/job.py's JobResult).

The actual pipeline runs in the background, kicked off by POST /upload
(app/api/upload.py) — this router is read-only, no processing happens here.
"""

from fastapi import APIRouter, HTTPException

from app.schemas.job import Job, JobResult, JobStatus
from app.services import job_service

router = APIRouter(tags=["transcribe"])


@router.get("/status/{job_id}", response_model=Job)
def get_status(job_id: str) -> Job:
    job = job_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job found with id {job_id!r}")
    return job


@router.get("/result/{job_id}", response_model=JobResult)
def get_result(job_id: str) -> JobResult:
    job = job_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job found with id {job_id!r}")

    if job.status == JobStatus.FAILED:
        raise HTTPException(status_code=422, detail=f"Job failed: {job.error}")
    if job.status != JobStatus.DONE:
        stage_value = job.stage.value if job.stage is not None else None
        raise HTTPException(
            status_code=409,
            detail=f"Job is not finished yet (status={job.status.value}, stage={stage_value})",
        )
    if job.result is None:
        # Shouldn't happen if status is DONE, but guard against inconsistent state
        # rather than returning a misleading 200 with a null body.
        raise HTTPException(status_code=500, detail="Job marked done but has no result")

    return job.result
