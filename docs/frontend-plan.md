# Frontend Plan

Step 9, now unblocked — step 8 (FastAPI routes) is done and verified end-to-end
against a real running server (see `CLAUDE.md`'s Quality backlog and `README.md`'s
"Running the server" section for the actual API shape, request/response examples,
and a `curl` walkthrough). `frontend/` is currently an empty scaffold (0-byte
`package.json`, empty `src/{assets,components,hooks,pages,services,utils}/`) — this
is a from-scratch build, not a partially-started one.

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

Processing is async and takes several minutes per file (Demucs separation + 6-stem
transcription) — every screen that waits on a job needs to poll `/status`, not just
fire-and-forget the upload.

**Known gap:** no raw-audio-file or per-stem-audio download/stream endpoint exists
yet (only MusicXML/MSCZ). The waveform + stem player screen needs actual audio
bytes to visualize/play — needs a new backend endpoint (e.g.
`GET /audio/{job_id}/{stem}`, serving from `storage/stems/<model>/<job_id>/`)
before that screen can be real. Small addition to `export.py` or a new small
router, not a redesign — flag it to whoever picks it up.

(The tempo/time-signature re-quantize-on-demand gap from the earlier version of
this plan no longer applies — that only mattered for in-browser correction, which
is out of scope now.)

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
   individual stems. Blocked on the missing audio-serving endpoint noted above.
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

1. **Both, together, briefly:** scaffold the actual React+TS project (currently
   empty) — routing, a shared API client module (`src/services/`) wrapping the 4
   endpoints above with typed responses matching `app/schemas/job.py`'s shapes, and
   agree on the shared `Job`/`JobResult` TypeScript types so both tracks build
   against the same contract from the start.
2. **Track 1:** upload → poll → "done" state (bare-bones, no score view yet) —
   proves the whole async chain works end-to-end from the browser.
3. **Track 2, parallel to step 2 once the API client exists:** OSMD read-only
   render against a MusicXML file (can start from a `curl`-uploaded job's result
   while Track 1's upload screen isn't done yet — no need to block on it), then
   export buttons.
4. **Track 1:** waveform + stem player, once the audio-serving endpoint is added
   (flag to Track 2 / whoever touches the backend that day — small addition).
5. **Both:** wire the two tracks into one flow (upload → status → preview + export
   + stem player all on one results page), final polish.

## Related backlog item — done

`scripts/run_pipeline.py` (now `app/services/pipeline_service.py`, called by both
the CLI script and the FastAPI async job API) runs the full chain: Demucs
separation → classification verification → transcription → quantization → tempo
reconciliation → per-stem MusicXML (written to `storage/musicxml/stems/` for
inspection) → one combined multi-part MusicXML/MSCZ for all stems together. See
`CLAUDE.md`'s Quality backlog for the full history of bugs found and fixed along
the way. The multi-stem end-to-end milestone is done, and it's now reachable over
HTTP via `POST /upload` — not just the CLI script.
