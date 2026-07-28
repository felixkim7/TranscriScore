// Export buttons/download links. Uses services/api.ts's exportFileUrl(), which
// returns a plain URL rather than a fetch wrapper — so these are real <a href
// download> links, not JS-driven blob downloads. Matches the comment on
// exportFileUrl(): "meant for <a href> / window.open, not JSON parsing."
//
// Only "musicxml" and "mscz" are offered — "stem-musicxml" also exists on the
// backend but needs a stem picker UI this component doesn't have yet (see
// TRACK2_INTEGRATION.md's "Not part of this track" section).

import { exportFileUrl } from '../../services/api';
import type { ExportFormat } from '../../services/types';
import './ExportPanel.css';

export interface ExportPanelProps {
  /** job_id from services/types.ts's Job. Null disables all links. */
  jobId: string | null;
  /** Used as the download filename's base, e.g. "sample2" → "sample2.mscz" */
  trackName?: string;
}

const FORMATS: { id: ExportFormat; label: string; extension: string }[] = [
  { id: 'mscz', label: 'MuseScore (.mscz)', extension: 'mscz' },
  { id: 'musicxml', label: 'MusicXML (.musicxml)', extension: 'musicxml' },
];

export function ExportPanel({ jobId, trackName = 'score' }: ExportPanelProps) {
  return (
    <div className="export-panel">
      <h3 className="export-panel__title">내보내기</h3>
      <ul className="export-panel__list">
        {FORMATS.map((format, index) => {
          const disabled = !jobId;
          return (
            <li
              key={format.id}
              className="export-panel__item"
              style={index === 0 ? { borderTop: 'none', paddingTop: 0 } : undefined}
            >
              <span className="export-panel__item-label">{format.label}</span>
              {disabled ? (
                <span className="export-panel__button export-panel__button--disabled">다운로드</span>
              ) : (
                <a
                  className="export-panel__button"
                  href={exportFileUrl(jobId, format.id)}
                  download={`${trackName}.${format.extension}`}
                >
                  다운로드
                </a>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
