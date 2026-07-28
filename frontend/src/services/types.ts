// Mirrors backend/app/schemas/job.py exactly — keep these two in sync by hand.
// If the backend schema changes, update this file in the same PR.

export type JobStatus = "pending" | "processing" | "done" | "failed";

export type JobStage =
  | "uploaded"
  | "separating"
  | "transcribing"
  | "quantizing"
  | "reconciling_tempo"
  | "rendering_musicxml"
  | "exporting";

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

export interface Job {
  job_id: string;
  status: JobStatus;
  stage: JobStage | null;
  original_filename: string;
  input_audio_path: string;
  created_at: string;
  updated_at: string;
  error: string | null;
  result: JobResult | null;
}

// Demucs stems this project actually separates into — see
// backend/app/config/settings.py's DEMUCS_STEM_NAMES.
export const STEM_NAMES = ["vocals", "drums", "bass", "guitar", "piano", "other"] as const;
export type StemName = (typeof STEM_NAMES)[number];

// Every format GET /export/{job_id}/{format} accepts.
export type ExportFormat = "musicxml" | "mscz" | "stem-musicxml";
