"""GET /export/{job_id}/{format} — download a finished job's output file.

Formats: "musicxml" (combined score), "mscz" (combined MuseScore project),
"stem-musicxml" (a single stem's MusicXML, via ?stem=<name>). PDF/PNG/SVG export
doesn't exist yet — export_service.py only has to_mscz() (tracked as Q3 in
CLAUDE.md's quality backlog).
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.schemas.job import JobStatus
from app.services import job_service

router = APIRouter(tags=["export"])

MEDIA_TYPES = {
    "musicxml": "application/vnd.recordare.musicxml+xml",
    "mscz": "application/octet-stream",
}


@router.get("/export/{job_id}/{format}")
def download_export(job_id: str, format: str, stem: str | None = Query(default=None)) -> FileResponse:
    job = job_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job found with id {job_id!r}")
    if job.status != JobStatus.DONE or job.result is None:
        raise HTTPException(
            status_code=409,
            detail=f"Job is not finished yet (status={job.status.value})",
        )

    if format == "stem-musicxml":
        if stem is None:
            raise HTTPException(status_code=400, detail="?stem=<name> is required for format=stem-musicxml")
        matching = [s for s in job.result.stems if s.stem_name == stem]
        if not matching:
            available = [s.stem_name for s in job.result.stems]
            raise HTTPException(
                status_code=404, detail=f"No stem named {stem!r} in this job's result. Available: {available}"
            )
        file_path = Path(matching[0].musicxml_path)
        download_name = f"{job.original_filename}.{stem}.musicxml"
    elif format == "musicxml":
        file_path = Path(job.result.combined_musicxml_path)
        download_name = f"{job.original_filename}.musicxml"
    elif format == "mscz":
        file_path = Path(job.result.combined_mscz_path)
        download_name = f"{job.original_filename}.mscz"
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format {format!r}. Supported: musicxml, mscz, stem-musicxml",
        )

    if not file_path.exists():
        raise HTTPException(status_code=500, detail=f"Job marked done but output file is missing: {file_path}")

    return FileResponse(
        path=file_path,
        media_type=MEDIA_TYPES.get(format, "application/octet-stream"),
        filename=download_name,
    )
