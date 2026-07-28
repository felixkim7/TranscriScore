// Composes ScorePreview + ExportPanel, and owns the piece that makes them
// actually usable: polling job status via useJobStatus (which wraps
// services/api.ts's getStatus) and only handing a preview URL to ScorePreview
// once the job is DONE (the export routes 409 otherwise).

import { useJobStatus } from '../../hooks/useJobStatus';
import { exportFileUrl } from '../../services/api';
import type { JobStage } from '../../services/types';
import { ScorePreview } from '../ScorePreview/ScorePreview';
import { ExportPanel } from '../ExportPanel/ExportPanel';
import './ScoreWorkspace.css';

export interface ScoreWorkspaceProps {
  /** job_id returned by uploadAudio() in services/api.ts. Null before any upload. */
  jobId: string | null;
}

const STAGE_LABELS: Record<JobStage, string> = {
  uploaded: '업로드 완료, 대기 중',
  separating: '음원을 분리하는 중',
  transcribing: '음표를 추출하는 중',
  quantizing: '리듬을 정리하는 중',
  reconciling_tempo: '템포를 맞추는 중',
  rendering_musicxml: '악보를 만드는 중',
  exporting: '내보내기 파일을 만드는 중',
};

export function ScoreWorkspace({ jobId }: ScoreWorkspaceProps) {
  const { job, error } = useJobStatus(jobId);

  if (!jobId) {
    return (
      <div className="score-workspace score-workspace--empty">
        오디오를 업로드하면 여기에 결과가 표시됩니다.
      </div>
    );
  }

  if (error) {
    return (
      <div className="score-workspace score-workspace--error" role="alert">
        {error}
      </div>
    );
  }

  if (!job || job.status === 'pending' || job.status === 'processing') {
    const label = job?.stage ? STAGE_LABELS[job.stage] : '준비하는 중';
    return (
      <div className="score-workspace score-workspace--pending" aria-live="polite">
        {label}…
      </div>
    );
  }

  if (job.status === 'failed') {
    return (
      <div className="score-workspace score-workspace--error" role="alert">
        변환에 실패했습니다{job.error ? `: ${job.error}` : ''}
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
