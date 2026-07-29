import { originalAudioUrl, stemAudioUrl } from "../services/api";
import { STEM_NAMES } from "../services/types";

interface StemPlayerProps {
  jobId: string;
}

/**
 * Plain HTML5 <audio> controls for the original mix and each separated stem —
 * functional first pass. GET /audio/{job_id}/{stem} works as soon as separation
 * finishes (doesn't require the whole job to be done), so this renders as soon
 * as the results page mounts rather than waiting for job.status === "done".
 * Real waveform visualization (e.g. wavesurfer.js) is a planned follow-up, not
 * implemented here — see docs/frontend-plan.md.
 */
export default function StemPlayer({ jobId }: StemPlayerProps) {
  return (
    <div className="stem-player">
      <h2>Listen</h2>

      <div className="stem-track">
        <span className="stem-label">Original mix</span>
        <audio controls src={originalAudioUrl(jobId)} />
      </div>

      {STEM_NAMES.map((stem) => (
        <div className="stem-track" key={stem}>
          <span className="stem-label">{stem}</span>
          <audio controls src={stemAudioUrl(jobId, stem)} />
        </div>
      ))}
    </div>
  );
}
