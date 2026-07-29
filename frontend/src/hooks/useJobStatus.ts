import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, getStatus } from "../services/api";
import type { Job } from "../services/types";

const POLL_INTERVAL_MS = 3000;

// Statuses where nothing will change until either the backend finishes on its
// own (done/failed) or the user takes an action (awaiting_review — nothing
// happens until continueJob() is called) — polling further is wasted work.
const TERMINAL_OR_PAUSED = new Set(["awaiting_review", "done", "failed"]);

interface UseJobStatusResult {
  job: Job | null;
  error: string | null;
  /** Call after continueJob() succeeds to resume polling for the next phase. */
  resumePolling: () => void;
}

/**
 * Polls GET /status/{job_id} every POLL_INTERVAL_MS until the job reaches a
 * paused (awaiting_review) or terminal (done/failed) status, then stops.
 * Call resumePolling() after continueJob() to start polling again for the
 * next phase — a phase runs as a new background task, so nothing changes on
 * the backend between "awaiting_review" and calling /continue.
 */
export function useJobStatus(jobId: string): UseJobStatusResult {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const startPolling = useCallback(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);

    let cancelled = false;

    async function poll() {
      try {
        const latest = await getStatus(jobId);
        if (cancelled) return;
        setJob(latest);
        setError(null);
        if (TERMINAL_OR_PAUSED.has(latest.status)) {
          if (intervalRef.current) clearInterval(intervalRef.current);
        }
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof ApiError ? String(e.detail) : "Failed to reach the backend.");
        if (intervalRef.current) clearInterval(intervalRef.current);
      }
    }

    poll(); // fetch immediately, don't wait POLL_INTERVAL_MS for the first update
    intervalRef.current = setInterval(poll, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
    };
  }, [jobId]);

  useEffect(() => {
    const cleanup = startPolling();
    return () => {
      cleanup?.();
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [startPolling]);

  return { job, error, resumePolling: startPolling };
}
