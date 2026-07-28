# Frontend Plan

Step 9, now unblocked — step 8 (FastAPI routes) is done and verified end-to-end
against a real running server (see `CLAUDE.md`'s Quality backlog and `README.md`'s
"Running the server" section for the actual API shape, request/response examples,
and a `curl` walkthrough). `frontend/` is currently an empty scaffold (0-byte
`package.json`, empty `src/{assets,components,hooks,pages,services,utils}/`) — this
is a from-scratch build, not a partially-started one.

Stack (from `CLAUDE.md` / the original project proposal): React + TypeScript,
OpenSheetMusicDisplay (OSMD) for score rendering, a waveform/stem player, and a
note-correction interface.

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

**Known gaps the frontend will run into, not backend bugs to "fix" — just things
without a fully-wired path yet:**
- No raw-audio-file or per-stem-audio download/stream endpoint exists yet (only
  MusicXML/MSCZ). The waveform + stem player screen needs actual audio bytes to
  visualize/play — this needs a new backend endpoint (e.g.
  `GET /audio/{job_id}/{stem}`, serving from `storage/stems/<model>/<job_id>/`)
  before that screen can be real. Flag this to whoever picks up Track 1 below —
  it's a quick addition to `export.py` or a new small router, not a redesign.
- Tempo/time-signature correction (re-quantizing against a user-picked value) has
  no backend endpoint either — `quantization_service.run(..., tempo_bpm=...)`
  already supports forcing a tempo, but nothing in the API calls it on demand yet.
  Needed before the tempo/time-signature pickers (item 5 below) can do anything
  beyond just displaying a number.

## Screens/features

1. **Upload screen** — file picker, `POST /upload`, hands off the returned `job_id`.
2. **Processing/status view** — poll `/status/{job_id}`; show per-stage progress
   using the real `stage` enum values above (6 stages = a real progress bar, not
   just a spinner).
3. **Score preview panel** — fetch the combined MusicXML (`/export/{job_id}/musicxml`)
   and render with OSMD.
4. **Waveform + stem player** — visualize the original upload's waveform, play back
   individual stems. Blocked on the missing audio-serving endpoint noted above.
5. **Correction interface** — human-in-the-loop editing: click/select notes on the
   rendered score, edit pitch/duration/delete. The project's core value proposition.
   - **Tempo picker/override**: tempo octave ambiguity (e.g. 129 BPM detected vs. 65
     BPM real) can't be resolved from audio alone (`CLAUDE.md`'s Known Gotchas). Show
     the detected BPM per stem, offer half/double as quick picks plus free entry.
     Needs the re-quantize-on-demand endpoint noted above.
   - **Time signature picker/override**: always 4/4 today (real detection removed —
     madmom too costly to install, Essentia has no Windows wheel; see `CLAUDE.md`'s
     Quality backlog). Offer common options (4/4, 3/4, 6/8, 2/4) + free entry.
6. **Export buttons** — `/export/{job_id}/{musicxml,mscz,stem-musicxml}` already
   work; wire up download buttons/links for each. PDF/PNG export doesn't exist on
   the backend yet (Q3 in `CLAUDE.md`, still open) — MIDI-per-stem download also
   isn't exposed via the API yet even though the files exist on disk
   (`storage/midi/<job_id>/`), only MusicXML/MSCZ are wired to `/export`.

## How the work splits — two tracks, by feature

Split by feature, not by layer (state/API-integration vs. UI) — a feature split
means each person mostly owns their own files and avoids the two of you constantly
touching the same components. Assign based on who wants the deep OSMD/notation work
vs. who wants more standard web-app/media-player work — that preference matters more
than any other factor here.

**Track 1 — Pipeline UX (upload → status → stems → export)**
- Upload screen (1)
- Processing/status view (2)
- Waveform + stem player (4) — coordinate on the missing audio-serving endpoint
  first, see above
- Export buttons (6)
- Owns: the API client/fetch layer for `/upload`, `/status`, `/export` — Track 2
  only needs `/result` (for the MusicXML content) and whatever new re-quantize
  endpoint correction needs, so there's minimal overlap in what each track calls.

**Track 2 — Score + correction (the deep, notation-specific half)**
- Score preview panel (3) — OSMD integration
- Correction interface (5), including the tempo/time-signature pickers
- Owns: parsing MusicXML into an editable representation, mapping clicks to
  notes, regenerating/re-exporting after edits. This is the part most tied to the
  project's actual "human-in-the-loop" pitch — whoever takes this should be
  comfortable diving into OSMD's API and possibly needing backend endpoint changes
  (the re-quantize-on-demand one above) as edits require them.

Both tracks depend on `/upload` + `/status` + `/result` existing (they do, and are
tested) and don't otherwise block each other much — Track 2 can build against a
`GET /export/{job_id}/musicxml` response using a job ID from a manual `curl` upload
while Track 1 is still building the upload screen, no need to wait in sequence.

## Suggested build order

1. **Both, together, briefly:** scaffold the actual React+TS project (currently
   empty) — routing, a shared API client module (`src/services/`) wrapping the 4
   endpoints above with typed responses matching `app/schemas/job.py`'s shapes, and
   agree on the shared `Job`/`JobResult` TypeScript types so both tracks build
   against the same contract from the start.
2. **Track 1:** upload → poll → "done" state, even with a bare-bones/no-op score
   view — proves the whole async chain works end-to-end from the browser.
3. **Track 2, parallel to step 2 once the API client exists:** OSMD rendering
   against a MusicXML file (can start from a `curl`-uploaded job's result while
   Track 1's upload screen isn't done yet — no need to block on it).
4. **Track 1:** waveform + stem player, once the audio-serving endpoint is added
   (flag to Track 2 / whoever touches the backend that day — small addition).
5. **Track 2:** correction interface — hardest, most dependent on step 3 being
   solid, likely needs backend coordination (re-quantize-on-demand endpoint) partway
   through.
6. **Both:** export buttons + final polish, once 2-5 are stable.

## Related backlog item — done

`scripts/run_pipeline.py` (now `app/services/pipeline_service.py`, called by both
the CLI script and the FastAPI async job API) runs the full chain: Demucs
separation → classification verification → transcription → quantization → tempo
reconciliation → per-stem MusicXML (written to `storage/musicxml/stems/` for
inspection) → one combined multi-part MusicXML/MSCZ for all stems together. See
`CLAUDE.md`'s Quality backlog for the full history of bugs found and fixed along
the way. The multi-stem end-to-end milestone is done, and it's now reachable over
HTTP via `POST /upload` — not just the CLI script.
