"""GET /export/{job_id}/{format} — download a finished job's output file.

Formats: "musicxml" (combined score), "mscz" (combined MuseScore project),
"stem-musicxml" (a single stem's MusicXML, via ?stem=<name>). PDF/PNG/SVG export
doesn't exist yet — export_service.py only has to_mscz() (tracked as Q3 in
CLAUDE.md's quality backlog).

GET /audio/{job_id} and GET /audio/{job_id}/{stem} — stream the original upload
or a separated stem's audio (WAV), for the frontend's waveform + stem player
(docs/frontend-plan.md's Track 1). Added because no endpoint served raw audio
bytes at all before this — only notation formats (MusicXML/MSCZ) were reachable
via /export. Available as soon as separation finishes (job.stage past
"separating"), not gated on the whole job being DONE, unlike /export — a stem
player wants to start working while transcription/quantization/export are still
running for the rest of the pipeline.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.config.settings import DEMUCS_MODEL, DEMUCS_STEM_NAMES, MIDI_DIR, STEMS_DIR
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


ORIGINAL_AUDIO_MEDIA_TYPES = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
}


@router.get("/audio/{job_id}")
def download_original_audio(job_id: str) -> FileResponse:
    """The original uploaded audio (whatever extension was uploaded), for the
    waveform view of the full mix before separation."""
    job = job_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job found with id {job_id!r}")

    file_path = Path(job.input_audio_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Uploaded audio file is missing: {file_path}")

    media_type = ORIGINAL_AUDIO_MEDIA_TYPES.get(file_path.suffix.lower(), "application/octet-stream")
    return FileResponse(path=file_path, media_type=media_type, filename=job.original_filename)


@router.get("/audio/{job_id}/{stem}")
def download_stem_audio(job_id: str, stem: str) -> FileResponse:
    """One separated stem's audio (WAV), for stem playback.

    Doesn't require the job to be DONE — only that separation has actually run
    and written this stem's file to disk. A stem player can start working while
    later pipeline stages (transcription/quantization/export) are still running.
    """
    if stem not in DEMUCS_STEM_NAMES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown stem {stem!r}. Valid stems: {list(DEMUCS_STEM_NAMES)}",
        )

    job = job_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job found with id {job_id!r}")

    input_stem = Path(job.input_audio_path).stem
    stem_path = STEMS_DIR / DEMUCS_MODEL / input_stem / f"{stem}.wav"
    if not stem_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Stem {stem!r} not available yet (separation may still be running, or the job failed "
            f"before it completed). Check GET /status/{job_id} first.",
        )

    return FileResponse(
        path=stem_path,
        media_type="audio/wav",
        filename=f"{job.original_filename}.{stem}.wav",
    )


@router.get("/midi/{job_id}/{stem}")
def download_stem_midi(job_id: str, stem: str) -> FileResponse:
    """One stem's TRANSCRIBED note events, as MIDI — not the separated audio
    (see GET /audio/{job_id}/{stem} for that). Lets the frontend offer "listen
    to what got transcribed" per stem, same as it already offers "listen to
    the separated audio" per stem — a different thing to check: this is
    Basic Pitch's (or drum_transcription_service's) output, so it reveals
    transcription quality/errors that the separated audio itself wouldn't.

    Written by transcription_service.run()/drum_transcription_service.run()
    at storage/midi/<job_id>/<stem>.mid as soon as that stem's transcription
    phase finishes — doesn't require the whole job to be DONE, same
    availability timing as the stem audio endpoint (checks the file exists
    directly rather than gating on job.status).

    Real per-instrument GM programs are baked into the file itself (see
    transcription_service.STEM_LABEL_MIDI_PROGRAMS /
    _apply_stem_instrument()) — vocals/bass/guitar/piano each carry their own
    General MIDI program (not all identically "Electric Piano," which is
    what Basic Pitch's own predict() hardcodes for every stem otherwise), and
    drums are on GM channel 10 (is_drum=True) — so a standards-compliant
    player/soundfont renders each stem sounding like its actual instrument,
    not just "generic MIDI."
    """
    if stem not in DEMUCS_STEM_NAMES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown stem {stem!r}. Valid stems: {list(DEMUCS_STEM_NAMES)}",
        )

    job = job_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job found with id {job_id!r}")

    midi_path = MIDI_DIR / job_id / f"{stem}.mid"
    if not midi_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"MIDI for stem {stem!r} not available yet (transcription may still be running, or the "
            f"job failed before it completed). Check GET /status/{job_id} first.",
        )

    return FileResponse(
        path=midi_path,
        media_type="audio/midi",
        filename=f"{job.original_filename}.{stem}.mid",
    )
