// Mirrors backend/app/schemas/job.py exactly — keep these two in sync by hand.
// If the backend schema changes, update this file in the same PR.

export type JobStatus = "pending" | "processing" | "awaiting_review" | "done" | "failed";

export type JobStage =
  | "uploaded"
  | "separating"
  | "transcribing"
  | "quantizing"
  | "reconciling_tempo"
  | "rendering_musicxml"
  | "exporting";

// Which review checkpoint a job is paused at — only meaningful when
// status === "awaiting_review". Determines what POST /jobs/{job_id}/continue
// runs next (see backend/app/services/pipeline_service.py's module docstring).
export type Checkpoint = "after_separation" | "after_transcription";

export interface StemResult {
  stem_name: string;
  stem_label: string;
  tempo_bpm: number;
  note_count: number;
  musicxml_path: string;
}

export interface JobResult {
  combined_musicxml_path: string;
  combined_mscz_path: string;
  stems: StemResult[];
}

export interface SeparationCheckpointStem {
  stem_name: string;
}

export interface TranscriptionCheckpointStem {
  stem_name: string;
  stem_label: string;
  note_count: number;
}

export interface Job {
  job_id: string;
  status: JobStatus;
  stage: JobStage | null;
  checkpoint: Checkpoint | null;
  original_filename: string;
  input_audio_path: string;
  created_at: string;
  updated_at: string;
  error: string | null;
  result: JobResult | null;
  separation_checkpoint: SeparationCheckpointStem[] | null;
  transcription_checkpoint: TranscriptionCheckpointStem[] | null;
  skip_separation: boolean;
  single_instrument_label: SingleInstrumentLabel | null;
}

// Demucs stems this project actually separates into — see
// backend/app/config/settings.py's DEMUCS_STEM_NAMES.
export const STEM_NAMES = ["vocals", "drums", "bass", "guitar", "piano", "other"] as const;
export type StemName = (typeof STEM_NAMES)[number];

// The stem_label vocabulary a single-instrument upload (skip_separation)
// picks from — mirrors backend/app/services/pipeline_service.py's
// SINGLE_INSTRUMENT_LABELS exactly (the same labels every Demucs-derived
// stem already gets routed through: TRUSTED_STEM_LABELS/VERIFIED_STEM_LABELS
// plus "drums"), so keep both lists in sync by hand if either changes.
export const SINGLE_INSTRUMENT_LABELS = [
  "vocal_melody",
  "bass",
  "guitar_accompaniment",
  "piano_accompaniment",
  "drums",
  "other_accompaniment",
] as const;
export type SingleInstrumentLabel = (typeof SINGLE_INSTRUMENT_LABELS)[number];

// Every format GET /export/{job_id}/{format} accepts.
export type ExportFormat = "musicxml" | "mscz" | "stem-musicxml";
