import { useParams } from "react-router-dom";
import CheckpointReview from "../components/CheckpointReview";
import ProcessingStatus from "../components/ProcessingStatus";
import StemPlayer from "../components/StemPlayer";
import { useJobStatus } from "../hooks/useJobStatus";

// A stem's audio is servable as soon as separation has finished — see
// backend/app/api/export.py's GET /audio/{job_id}/{stem} docstring. This is
// true both once the job reaches the "after_separation" checkpoint (paused,
// waiting for the user to continue) AND once it's past that point running
// later stages — checking status/checkpoint together covers both, since
// job.stage alone stays "separating" for the whole pause (it only advances
// again once /continue kicks off the next phase).
const STEM_PLAYER_READY_STAGES = new Set([
  "transcribing",
  "quantizing",
  "reconciling_tempo",
  "rendering_musicxml",
  "exporting",
]);

export default function ResultsPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const { job, error, resumePolling } = useJobStatus(jobId!);

  if (error) {
    return (
      <div className="results-page">
        <p role="alert">{error}</p>
      </div>
    );
  }

  if (!job) {
    return (
      <div className="results-page">
        <p>Loading job status...</p>
      </div>
    );
  }

  const separationDone =
    job.status === "done" ||
    (job.status === "awaiting_review" && job.checkpoint === "after_separation") ||
    (job.stage !== null && STEM_PLAYER_READY_STAGES.has(job.stage));

  return (
    <div className="results-page">
      <ProcessingStatus job={job} />

      {job.status === "awaiting_review" && <CheckpointReview job={job} onContinued={resumePolling} />}

      {separationDone && <StemPlayer jobId={job.job_id} />}

      {job.status === "done" && (
        <div className="score-section">
          {/* Track 2: score preview (OSMD) + export buttons go here. */}
          <p className="placeholder">Score preview and export coming soon.</p>
        </div>
      )}
    </div>
  );
}
