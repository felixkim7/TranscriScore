// Composes ScorePreview + ExportPanel, and owns the piece that makes them
// actually usable: polling job status via useJobStatus (which wraps
// services/api.ts's getStatus) and only handing a preview URL to ScorePreview
// once the job is DONE (the export routes 409 otherwise).
//
// Only ever mounted by ResultsPage once job.status === "done", so unlike the
// original Track 2 standalone version, there's no pending/processing/no-job
// state to render here — ProcessingStatus (Track 1) already covers that.

import { useJobStatus } from '../../hooks/useJobStatus';
import { exportFileUrl } from '../../services/api';
import { ScorePreview } from '../ScorePreview/ScorePreview';
import { ExportPanel } from '../ExportPanel/ExportPanel';
import './ScoreWorkspace.css';

export interface ScoreWorkspaceProps {
  /** job_id of a job whose status is already "done". */
  jobId: string;
}

export function ScoreWorkspace({ jobId }: ScoreWorkspaceProps) {
  const { job, error } = useJobStatus(jobId);

  if (error) {
    return (
      <div className="score-workspace score-workspace--error" role="alert">
        {error}
      </div>
    );
  }

  if (!job) {
    return (
      <div className="score-workspace score-workspace--pending" aria-live="polite">
        불러오는 중…
      </div>
    );
  }

  return (
    <div className="score-workspace">
      <div className="score-workspace__preview">
        <ScorePreview musicXmlUrl={exportFileUrl(jobId, 'musicxml')} />
      </div>
      <div className="score-workspace__export">
        <ExportPanel jobId={jobId} trackName={job.original_filename} />
      </div>
    </div>
  );
}
