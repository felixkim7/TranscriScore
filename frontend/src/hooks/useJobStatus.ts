// Polls services/api.ts's getStatus() while a job is pending/processing, stops
// once it reaches done/failed. Backend is async by design (README: "processing
// takes several minutes... POST /upload returns immediately with a job ID"), so
// anything that wants to show a live score/export UI has to poll first.

import { useEffect, useRef, useState } from 'react';
import { ApiError, getStatus } from '../services/api';
import type { Job } from '../services/types';

export function useJobStatus(jobId: string | null, pollIntervalMs = 2000) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!jobId) {
      setJob(null);
      setError(null);
      return;
    }

    let cancelled = false;

    const poll = async () => {
      try {
        const result = await getStatus(jobId);
        if (cancelled) return;
        setJob(result);
        setError(null);
        if (result.status === 'pending' || result.status === 'processing') {
          timerRef.current = setTimeout(poll, pollIntervalMs);
        }
      } catch (err) {
        if (cancelled) return;
        const message = err instanceof ApiError ? String(err.detail) : String(err);
        setError(message);
      }
    };

    poll();

    return () => {
      cancelled = true;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [jobId, pollIntervalMs]);

  return { job, error };
}
