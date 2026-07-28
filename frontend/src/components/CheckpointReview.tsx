import { useState } from "react";
import { ApiError, continueJob } from "../services/api";
import type { Job } from "../services/types";

interface CheckpointReviewProps {
  job: Job;
  onContinued: () => void;
}

const CHECKPOINT_LABELS: Record<NonNullable<Job["checkpoint"]>, string> = {
  after_separation: "Stems separated",
  after_transcription: "Notes transcribed",
};

/**
 * Shown when a job is paused at a review checkpoint (status === "awaiting_review").
 * Displays what that checkpoint produced (which stems, or per-stem note counts)
 * and a "Continue" button that calls POST /jobs/{job_id}/continue, then tells
 * the parent to resume status polling for the next phase.
 */
export default function CheckpointReview({ job, onContinued }: CheckpointReviewProps) {
  const [isContinuing, setIsContinuing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleContinue() {
    setIsContinuing(true);
    setError(null);
    try {
      await continueJob(job.job_id);
      onContinued();
    } catch (e) {
      setError(e instanceof ApiError ? String(e.detail) : "Failed to continue the job.");
      setIsContinuing(false);
    }
  }

  const title = job.checkpoint ? CHECKPOINT_LABELS[job.checkpoint] : "Checkpoint reached";

  return (
    <div className="checkpoint-review">
      <h2>{title} — review before continuing</h2>

      {job.checkpoint === "after_separation" && job.separation_checkpoint && (
        <p>
          Separated into {job.separation_checkpoint.length} stems: listen to each one below, then continue to
          transcribe them.
        </p>
      )}

      {job.checkpoint === "after_transcription" && job.transcription_checkpoint && (
        <table className="checkpoint-table">
          <thead>
            <tr>
              <th>Stem</th>
              <th>Label</th>
              <th>Notes found</th>
            </tr>
          </thead>
          <tbody>
            {job.transcription_checkpoint.map((stem) => (
              <tr key={stem.stem_name}>
                <td>{stem.stem_name}</td>
                <td>{stem.stem_label}</td>
                <td>{stem.note_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      <button type="button" onClick={handleContinue} disabled={isContinuing}>
        {isContinuing ? "Continuing..." : "Continue"}
      </button>
    </div>
  );
}
