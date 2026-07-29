import type { Job, JobStage } from "../services/types";

// Order matches backend/app/schemas/job.py's JobStage enum and the actual
// sequence pipeline_service.run_full_pipeline() reports via its on_stage callback.
const STAGE_ORDER: JobStage[] = [
  "uploaded",
  "separating",
  "transcribing",
  "quantizing",
  "reconciling_tempo",
  "rendering_musicxml",
  "exporting",
];

const STAGE_LABELS: Record<JobStage, string> = {
  uploaded: "Uploaded",
  separating: "Separating into stems",
  transcribing: "Transcribing notes",
  quantizing: "Quantizing rhythm",
  reconciling_tempo: "Reconciling tempo across stems",
  rendering_musicxml: "Rendering sheet music",
  exporting: "Exporting",
};

interface ProcessingStatusProps {
  job: Job;
}

export default function ProcessingStatus({ job }: ProcessingStatusProps) {
  if (job.status === "failed") {
    return (
      <div className="processing-status failed">
        <p role="alert">Processing failed: {job.error ?? "Unknown error"}</p>
      </div>
    );
  }

  const currentIndex = job.stage ? STAGE_ORDER.indexOf(job.stage) : -1;
  // While awaiting_review, the stage that triggered the pause has actually
  // FINISHED (that's why it paused) — mark it done, not "active"/still-running,
  // otherwise the list looks stuck rather than paused-on-purpose.
  const lastCompletedIndex = job.status === "awaiting_review" ? currentIndex : currentIndex - 1;

  const headerText =
    job.status === "awaiting_review" ? `Paused: "${job.original_filename}"` : `Processing "${job.original_filename}"...`;

  return (
    <div className="processing-status">
      <p>{headerText}</p>
      <ol className="stage-list">
        {STAGE_ORDER.map((stage, index) => {
          const state =
            job.status === "done" || index <= lastCompletedIndex
              ? "done"
              : index === currentIndex
                ? "active"
                : "pending";
          return (
            <li key={stage} className={`stage stage-${state}`}>
              {STAGE_LABELS[stage]}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
