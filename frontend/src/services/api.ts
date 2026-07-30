// Typed client for the TranscriScore backend (backend/app/api/*.py).
//
// API_BASE_URL comes from Vite's env handling (see .env.example) so both tracks
// point at the same running backend without hardcoding a port in source. Default
// matches how the backend is started in README.md's "Running the server" section
// (uvicorn on 127.0.0.1:8000).
import type { ExportFormat, Job, JobResult, SingleInstrumentLabel, StemName } from "./types";

const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  if (!response.ok) {
    // FastAPI's HTTPException body shape is always {"detail": ...} — see every
    // raise HTTPException(...) call across backend/app/api/*.py.
    let detail: unknown;
    try {
      const body = await response.json();
      detail = body.detail ?? body;
    } catch {
      detail = response.statusText;
    }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

/**
 * POST /upload — kicks off the pipeline in the background, returns immediately.
 *
 * singleInstrumentLabel: when given, sends skip_separation=true plus the
 * label alongside the file — see backend/app/api/upload.py's form fields.
 * The backend 400s if skip_separation is requested without a label (or with
 * one outside SINGLE_INSTRUMENT_LABELS), so omit this entirely for a normal
 * multi-instrument upload rather than passing a falsy/empty value.
 */
export function uploadAudio(file: File, singleInstrumentLabel?: SingleInstrumentLabel): Promise<Job> {
  const formData = new FormData();
  formData.append("file", file);
  if (singleInstrumentLabel) {
    formData.append("skip_separation", "true");
    formData.append("single_instrument_label", singleInstrumentLabel);
  }
  return request<Job>("/upload", { method: "POST", body: formData });
}

/**
 * GET /status/{job_id} — poll this until status is "awaiting_review" (a review
 * checkpoint — see job.checkpoint for which one, and call continueJob() to
 * resume), "done", or "failed".
 */
export function getStatus(jobId: string): Promise<Job> {
  return request<Job>(`/status/${jobId}`);
}

/** GET /result/{job_id} — throws ApiError(409) if not done yet, ApiError(422) if failed. */
export function getResult(jobId: string): Promise<JobResult> {
  return request<JobResult>(`/result/${jobId}`);
}

/**
 * POST /jobs/{job_id}/continue — resume a job paused at a review checkpoint
 * (status === "awaiting_review"). Runs the next phase automatically based on
 * the job's own stored checkpoint — there's no way to pass "which phase" in,
 * by design, so the caller can't accidentally skip or repeat a phase.
 * Throws ApiError(409) if the job isn't currently awaiting review.
 */
export function continueJob(jobId: string): Promise<Job> {
  return request<Job>(`/jobs/${jobId}/continue`, { method: "POST" });
}

/**
 * GET /export/{job_id}/{format} — returns a direct download URL (not a fetch
 * wrapper) since these are meant for <a href> / window.open, not JSON parsing.
 * stem is required (and only used) when format is "stem-musicxml".
 */
export function exportFileUrl(jobId: string, format: ExportFormat, stem?: StemName): string {
  const url = `${API_BASE_URL}/export/${jobId}/${format}`;
  return format === "stem-musicxml" && stem ? `${url}?stem=${encodeURIComponent(stem)}` : url;
}

/** GET /audio/{job_id} — the original uploaded mix, for a full-mix waveform view. */
export function originalAudioUrl(jobId: string): string {
  return `${API_BASE_URL}/audio/${jobId}`;
}

/**
 * GET /audio/{job_id}/{stem} — one separated stem's WAV audio, for stem playback.
 * Available as soon as separation finishes, before the whole job is DONE — don't
 * gate this on job.status === "done", only on having passed the "separating" stage.
 */
export function stemAudioUrl(jobId: string, stem: StemName): string {
  return `${API_BASE_URL}/audio/${jobId}/${stem}`;
}

/**
 * GET /midi/{job_id}/{stem} — one stem's TRANSCRIBED note events as MIDI (not
 * the separated audio — see stemAudioUrl() for that). Available as soon as
 * that stem's transcription phase finishes, before the whole job is DONE —
 * same availability rule as stemAudioUrl(), gate on job.stage having passed
 * "transcribing", not job.status === "done".
 *
 * Not directly usable in <audio src>: browsers don't natively decode .mid —
 * MidiPlayer.tsx fetches this URL as bytes and plays it through
 * @tonejs/midi + soundfont-player instead.
 */
export function stemMidiUrl(jobId: string, stem: StemName): string {
  return `${API_BASE_URL}/midi/${jobId}/${stem}`;
}
