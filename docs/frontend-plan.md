# Frontend Plan

Step 9, now unblocked — step 8 (FastAPI routes) is done and verified end-to-end
against a real running server (see `CLAUDE.md`'s Quality backlog and `README.md`'s
"Running the server" section for the actual API shape, request/response examples,
and a `curl` walkthrough). `frontend/` is scaffolded (Vite + React 19 + TypeScript,
`react-router-dom` installed) with a shared typed API client already in place at
`src/services/` — see "Suggested build order" step 1 below for exactly what's
there. `src/{components,hooks,pages,utils}/` are still empty, ready for each
track's actual screens.

**Scope decision: editing happens in MuseScore, not the browser.** The frontend's
job is to run the pipeline and hand the user finished score files — it does not
implement note-by-note correction. This removes the biggest, riskiest piece of the
original plan (click-to-edit OSMD interaction, mapping clicks to note edits,
regenerating MusicXML from an edited in-browser state) and the tempo/time-signature
re-quantization endpoints that correction would have needed. The user opens the
downloaded `.mscz` in MuseScore 4 to fix anything wrong — same tool already used
throughout this project to verify output, so this also means the frontend needs no
new backend work to support editing.

Stack (from `CLAUDE.md` / the original project proposal, trimmed to match the
reduced scope): React + TypeScript, OpenSheetMusicDisplay (OSMD) for a **read-only**
score preview, a waveform/stem player.

## The real API (confirmed working, not hypothetical)

| Endpoint | Method | Returns |
|---|---|---|
| `/upload` | POST | `Job` (includes `job_id`) — multipart `file` field, `.mp3`/`.wav`/`.flac`/`.m4a` |
| `/status/{job_id}` | GET | `Job` — `status` (pending/processing/done/failed), `stage` (separating/transcribing/quantizing/reconciling_tempo/rendering_musicxml/exporting) |
| `/result/{job_id}` | GET | `JobResult` — combined MusicXML/MSCZ paths + per-stem list (name, label, tempo, note count, stem MusicXML path). 409 if not done, 422 if failed |
| `/export/{job_id}/{format}` | GET | File download. `format` = `musicxml` \| `mscz` \| `stem-musicxml` (+ `?stem=<name>`) |
| `/audio/{job_id}` | GET | The original uploaded audio (whatever format was uploaded) |
| `/audio/{job_id}/{stem}` | GET | One separated stem's WAV audio. Doesn't require the whole job to be DONE — only that separation finished |

Processing is async and takes several minutes per file (Demucs separation + 6-stem
transcription) — every screen that waits on a job needs to poll `/status`, not just
fire-and-forget the upload.

(The audio-serving gap and the tempo/time-signature re-quantize-on-demand gap from
earlier versions of this plan are both resolved/no-longer-applicable — see the
"Suggested build order" section's step 1 for what was added.)

## Screens/features

1. **Upload screen** — file picker, `POST /upload`, hands off the returned `job_id`.
2. **Processing/status view** — poll `/status/{job_id}`; show per-stage progress
   using the real `stage` enum values above (6 stages = a real progress bar, not
   just a spinner).
3. **Score preview panel (read-only)** — fetch the combined MusicXML
   (`/export/{job_id}/musicxml`) and render with OSMD, purely for a quick look.
   No click handling, no note selection/editing — OSMD's default rendering is
   already read-only, so this is much smaller than typical OSMD integration work.
4. **Waveform + stem player** — visualize the original upload's waveform, play back
   individual stems. `originalAudioUrl()`/`stemAudioUrl()` in `src/services/api.ts`
   are ready to use — no longer blocked.
5. **Export buttons** — `/export/{job_id}/{musicxml,mscz,stem-musicxml}` already
   work; wire up download buttons/links for each. Point the user at "open this in
   MuseScore to edit" somewhere near the MSCZ download, since that's now the
   actual editing path. PDF/PNG export doesn't exist on the backend yet (Q3 in
   `CLAUDE.md`, still open) — MIDI-per-stem download also isn't exposed via the
   API yet even though the files exist on disk (`storage/midi/<job_id>/`), only
   MusicXML/MSCZ are wired to `/export`.

No correction interface, no tempo/time-signature pickers — cut along with the
in-browser editing scope.

## How the work splits — two tracks, by feature

With correction cut, the OSMD piece (item 3) is now small (read-only render, no
interaction logic) rather than the deep, dedicated-owner piece it was in the
original plan — so the two tracks are more evenly sized than before, but a feature
split (vs. splitting by layer/state-vs-UI) still keeps each person mostly in their
own files and avoids constant overlap.

**Track 1 — Pipeline + media**
- Upload screen (1)
- Processing/status view (2)
- Waveform + stem player (4) — coordinate on the missing audio-serving endpoint
  first, see above
- Owns: the API client for `/upload`, `/status`.

**Track 2 — Score preview + export**
- Score preview panel (3) — OSMD, read-only
- Export buttons (5)
- Owns: the API client for `/result`, `/export`.

Each track's API surface barely overlaps (Track 1: upload/status; Track 2:
result/export), so the split works even without much coordination once the shared
types exist (step 1 below). Given the shrunk scope, it's also reasonable for this
to end up more like "whoever finishes first helps the other" than a strict
division — flag that as an option when you actually divide it up, rather than
treating the track boundary as fixed.

## Suggested build order

1. **Done.** React+TS project scaffolded (Vite, React 19, `react-router-dom`
   installed — not wired into any routes yet, that's each track's job), plus a
   shared typed API client at `frontend/src/services/`:
   - `types.ts` — `Job`, `JobStatus`, `JobStage`, `JobResult`, `StemResult`,
     mirroring `backend/app/schemas/job.py` by hand (keep both in sync manually;
     no codegen set up).
   - `api.ts` — typed wrappers for all 6 backend endpoints: `uploadAudio()`,
     `getStatus()`, `getResult()`, `exportFileUrl()`, `originalAudioUrl()`,
     `stemAudioUrl()`. The last three return plain URL strings (for `<a href>`/
     audio elements), not fetch wrappers — downloads/streams shouldn't go through
     JSON parsing. Errors from the JSON-returning calls throw `ApiError` (has
     `.status` and `.detail`, matching FastAPI's `{"detail": ...}` error shape).
   - Base URL comes from `VITE_API_BASE_URL` (see `.env.example`; copy to
     `.env.local` to override — defaults to `http://127.0.0.1:8000`, matching
     `README.md`'s "Running the server" instructions).

   Verified against a real running backend (not just typechecked): status
   polling, result fetching, all URL builders, and an actual stem-audio download
   (15MB WAV, real content-length) all confirmed working; `ApiError` confirmed
   correctly parses a real 404's `detail` message. `npx tsc -b` and `npm run
   build` both clean.

   Also added while scaffolding (backend, needed for the stem player): `GET
   /audio/{job_id}` (original mix) and `GET /audio/{job_id}/{stem}` (one
   separated stem's WAV) in `backend/app/api/export.py` — this was the "known
   gap" flagged earlier in this doc. The stem endpoint doesn't require the whole
   job to be DONE, only that separation has finished, so Track 1's stem player
   can start working before transcription/export finish for the rest of the
   pipeline.
2. **Done — Track 1: upload → poll → "done" state, plus waveform + stem player.**
   Built in one pass rather than two separate steps, since the audio-serving
   endpoint was already ready:
   - `src/pages/UploadPage.tsx` — file picker (validates extension client-side
     to match the backend's `ALLOWED_EXTENSIONS`), calls `uploadAudio()`,
     navigates to `/job/:jobId` on success.
   - `src/hooks/useJobStatus.ts` — polls `GET /status/{job_id}` every 3s,
     stops once the job reaches `done`/`failed`. Reusable — `ResultsPage` is
     its only consumer so far, but nothing about it is page-specific.
   - `src/components/ProcessingStatus.tsx` — renders the 7-stage progress list
     using the real `JobStage` order, marking each done/active/pending; shows
     the error message directly if the job failed.
   - `src/components/StemPlayer.tsx` — plain HTML5 `<audio>` elements for the
     original mix + all 6 stems (native controls, no waveform visuals yet —
     decided explicitly to prove the real flow first, see this doc's history).
   - `src/pages/ResultsPage.tsx` — wires the above together; only renders the
     stem player once the job's stage indicates separation has actually
     finished (`transcribing` or later — checked directly against the real
     stage sequence, not assumed), not gated on the whole job being done. Has a
     clearly-marked placeholder (`.score-section`) for Track 2's OSMD preview +
     export buttons.
   - `src/App.tsx` / `main.tsx` — `react-router-dom` wired up (`/` upload,
     `/job/:jobId` results), replacing the default Vite demo content
     (`App.css`/unused demo assets removed).

   Verified against the REAL running backend end-to-end, not just typechecked:
   started both `uvicorn` and `vite dev`, uploaded `sample.mp3` through a fresh
   real job, polled it through every real stage to `done`, confirmed the stem
   player's audio sources (`GET /audio/{job_id}` and `/audio/{job_id}/{stem}`)
   return real, correctly-sized files once available. Every new `.tsx`/`.ts`
   file confirmed to compile cleanly through Vite's actual transform pipeline
   (not just `tsc`, which only checks types) via direct requests to the dev
   server. `npx tsc -b` and `npm run build` both clean.
3. **Track 2, can start now (the API client and page routing both exist):**
   OSMD read-only render against a MusicXML file (can start from a
   `curl`-uploaded job's result — several real completed jobs already exist in
   `storage/jobs/` from testing — no need to wait on anything else), rendered
   into `ResultsPage.tsx`'s `.score-section` placeholder, then export buttons.
4. **Both:** final polish once Track 2's piece lands — layout, loading states,
   error handling consistency between the two tracks' components.

## Related backlog item — done

`scripts/run_pipeline.py` (now `app/services/pipeline_service.py`, called by both
the CLI script and the FastAPI async job API) runs the full chain: Demucs
separation → classification verification → transcription → quantization → tempo
reconciliation → per-stem MusicXML (written to `storage/musicxml/stems/` for
inspection) → one combined multi-part MusicXML/MSCZ for all stems together. See
`CLAUDE.md`'s Quality backlog for the full history of bugs found and fixed along
the way. The multi-stem end-to-end milestone is done, and it's now reachable over
HTTP via `POST /upload` — not just the CLI script.
