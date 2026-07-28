// Read-only rendering surface for the transcribed score, backed by
// OpenSheetMusicDisplay (OSMD). This is preview-only — no cursor playback,
// no click-to-edit; note correction is a separate, later UI (see CLAUDE.md
// step 9, "shared/TBD"). Renders whatever MusicXML the backend's
// musicxml_service.py last produced for the current track.
//
// npm install opensheetmusicdisplay

import { useEffect, useRef, useState } from 'react';
import { OpenSheetMusicDisplay } from 'opensheetmusicdisplay';
import './ScorePreview.css';

export interface ScorePreviewProps {
  /** URL (or path) the backend serves the current track's .musicxml from. Null = nothing to show yet. */
  musicXmlUrl: string | null;
  onRenderError?: (error: Error) => void;
}

type PreviewStatus = 'idle' | 'loading' | 'ready' | 'error';

export function ScorePreview({ musicXmlUrl, onRenderError }: ScorePreviewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const osmdRef = useRef<OpenSheetMusicDisplay | null>(null);
  const [status, setStatus] = useState<PreviewStatus>('idle');
  const [errorMessage, setErrorMessage] = useState('');

  // OSMD instance lives for the component's lifetime; re-used across track changes.
  useEffect(() => {
    if (!containerRef.current) return;

    osmdRef.current = new OpenSheetMusicDisplay(containerRef.current, {
      autoResize: true,
      backend: 'svg',
      drawingParameters: 'compacttight',
      drawTitle: true,
      drawPartNames: true,
      drawMeasureNumbers: true,
      drawCredits: false,
    });

    return () => {
      osmdRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!musicXmlUrl) {
      setStatus('idle');
      return;
    }
    if (!osmdRef.current) return;

    let cancelled = false;
    setStatus('loading');
    setErrorMessage('');

    osmdRef.current
      .load(musicXmlUrl)
      .then(() => {
        if (cancelled || !osmdRef.current) return;
        osmdRef.current.render();
        setStatus('ready');
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const error = err instanceof Error ? err : new Error(String(err));
        setStatus('error');
        setErrorMessage(error.message);
        onRenderError?.(error);
      });

    return () => {
      cancelled = true;
    };
  }, [musicXmlUrl, onRenderError]);

  return (
    <div className="score-preview">
      {status === 'idle' && (
        <div className="score-preview__placeholder">
          아직 표시할 악보가 없습니다. 변환이 끝나면 여기에 나타납니다.
        </div>
      )}
      {status === 'loading' && (
        <div className="score-preview__placeholder">악보를 불러오는 중…</div>
      )}
      {status === 'error' && (
        <div className="score-preview__placeholder score-preview__placeholder--error" role="alert">
          악보를 표시할 수 없습니다. ({errorMessage})
        </div>
      )}
      <div
        ref={containerRef}
        className="score-preview__canvas"
        aria-label="악보 미리보기"
        style={{ display: status === 'ready' ? 'block' : 'none' }}
      />
    </div>
  );
}
