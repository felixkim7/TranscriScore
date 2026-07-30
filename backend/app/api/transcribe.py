"""GET /status/{job_id} — poll a job's current stage/status.
GET /result/{job_id} — once a job is done, its combined MusicXML/MSCZ paths and
per-stem breakdown (see app/schemas/job.py's JobResult).
POST /jobs/{job_id}/continue — resume a paused job to its next phase.

The pipeline is split into three phases with two review checkpoints in between
(see app/services/pipeline_service.py's module docstring for the full design):
POST /upload runs phase 1 (separation) and pauses; this router's /continue
endpoint runs phase 2 (transcription) the first time it's called for a job, and
phase 3 (quantize/reconcile/render/export) the second time — which phase runs is
decided from the job's stored Checkpoint, not passed in by the caller, so the
client can't accidentally run the wrong phase out of order.
"""

import traceback

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.schemas.job import (
    Checkpoint,
    Job,
    JobResult,
    JobStage,
    JobStatus,
    TranscriptionCheckpointStem,
)
from app.services import job_service, pipeline_service, transcription_service

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


@router.post("/jobs/{job_id}/continue", response_model=Job)
def continue_job(job_id: str, background_tasks: BackgroundTasks) -> Job:
    job = job_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job found with id {job_id!r}")

    if job.status != JobStatus.AWAITING_REVIEW:
        raise HTTPException(
            status_code=409,
            detail=f"Job is not awaiting review (status={job.status.value}) - nothing to continue",
        )

    if job.checkpoint == Checkpoint.AFTER_SEPARATION:
        job = job_service.update_job(job_id, status=JobStatus.PROCESSING, stage=JobStage.TRANSCRIBING)
        background_tasks.add_task(_run_transcription_phase, job_id)
    elif job.checkpoint == Checkpoint.AFTER_TRANSCRIPTION:
        job = job_service.update_job(job_id, status=JobStatus.PROCESSING, stage=JobStage.QUANTIZING)
        background_tasks.add_task(_run_final_phase, job_id)
    else:
        # Shouldn't happen — AWAITING_REVIEW is only ever set alongside a
        # checkpoint (see upload.py / this file's _run_transcription_phase) —
        # but guard rather than silently doing nothing.
        raise HTTPException(status_code=500, detail=f"Job is awaiting review but has no checkpoint set: {job}")

    return job


def _run_transcription_phase(job_id: str) -> None:
    """Runs in FastAPI's background task pool — phase 2 only (transcription)."""
    job = job_service.get_job(job_id)
    if job is None:
        return

    def on_stage(stage: JobStage, message: str) -> None:
        job_service.update_job(job_id, status=JobStatus.PROCESSING, stage=stage)

    try:
        stem_labels = pipeline_service.run_transcription_phase(job.input_audio_path, on_stage=on_stage)
        checkpoint_stems = [
            TranscriptionCheckpointStem(
                stem_name=stem_name,
                stem_label=stem_label,
                note_count=len(
                    transcription_service.load_note_events(stem_name, input_stem=job_id)
                ),
            )
            for stem_name, stem_label in stem_labels.items()
        ]
        job_service.update_job(
            job_id,
            status=JobStatus.AWAITING_REVIEW,
            checkpoint=Checkpoint.AFTER_TRANSCRIPTION,
            transcription_checkpoint=checkpoint_stems,
            stem_labels=stem_labels,
        )
    except Exception:  # noqa: BLE001 — job failures must be captured, not crash the worker
        tb = traceback.format_exc()
        print(tb)
        job_service.update_job(job_id, status=JobStatus.FAILED, error=tb)


def _run_final_phase(job_id: str) -> None:
    """Runs in FastAPI's background task pool — phase 3 (quantize -> reconcile
    -> render -> export), the rest of the pipeline through to a final result."""
    job = job_service.get_job(job_id)
    if job is None or job.stem_labels is None:
        return

    def on_stage(stage: JobStage, message: str) -> None:
        job_service.update_job(job_id, status=JobStatus.PROCESSING, stage=stage)

    try:
        output_name = pipeline_service.readable_output_name(job.original_filename, job_id)
        title = pipeline_service.readable_title(job.original_filename)
        result = pipeline_service.run_final_phase(
            job.input_audio_path,
            job.stem_labels,
            on_stage=on_stage,
            output_name=output_name,
            title=title,
            reference_tempo_bpm=job.reference_tempo_bpm,
            reference_beat_times=job.reference_beat_times,
        )
        job_service.update_job(job_id, status=JobStatus.DONE, result=result)
    except Exception:  # noqa: BLE001 — job failures must be captured, not crash the worker
        tb = traceback.format_exc()
        print(tb)
        job_service.update_job(job_id, status=JobStatus.FAILED, error=tb)
