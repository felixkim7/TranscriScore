# Frontend Plan

Per `CLAUDE.md`'s build order, frontend is step 9 — **after step 8 (FastAPI routes)**.
`app/api/*.py` and `app/main.py` are all currently empty, so there is no HTTP API yet
for a frontend to call. Step 8 needs to happen (or at least be scoped jointly) before
real frontend implementation can start.

Stack (from `CLAUDE.md` / the original project proposal): React + TypeScript,
OpenSheetMusicDisplay (OSMD) for score rendering, a waveform/stem player, and a
note-correction interface.

## What needs to be built (screens/features)

1. **Upload screen** — file picker for an audio clip, kicks off the pipeline.
2. **Processing/status view** — the pipeline takes a while (separation, classification,
   transcription, quantization, rendering); needs a progress indicator, ideally
   per-stage.
3. **Score preview panel** — renders the generated MusicXML using OSMD so the user
   sees the sheet music in-browser.
4. **Waveform + stem player** — visualize the original audio waveform, play back
   individual separated stems (vocals/drums/guitar/piano) so the user can check what
   got separated.
5. **Correction interface** — the human-in-the-loop piece: let the user click/select
   notes on the rendered score and edit them (pitch, duration, delete, etc.), matching
   the project proposal's stated goal.
   - **Tempo picker/override**: tempo octave ambiguity (e.g. detecting 129 BPM when
     the real tempo is 65 BPM — half/double the true value) can't be resolved from
     audio alone; see the "Tempo octave ambiguity" entry in `CLAUDE.md`'s Known
     Gotchas. Rather than guessing, let the user see the detected BPM and pick the
     correct one themselves (e.g. offer the detected value alongside its half/double
     as quick options, plus a free-entry field) — this re-quantizes note durations
     against the corrected tempo before final export.
6. **Export buttons** — download MusicXML / MIDI / PDF / MSCZ / stems, per the
   proposal's export list.

## How the work could split

Two natural options for a two-person team — to be decided with your teammate, not
unilaterally, since it depends on who's more interested in OSMD/notation-editing work
vs. general React app plumbing.

**Option A — split by feature:**
- **Track 1:** upload flow, processing/status view, waveform + stem player, export
  buttons — more standard web-app CRUD/media-player work, wires up to whichever
  endpoints step 8 exposes.
- **Track 2:** OSMD score rendering + the correction interface — the most technically
  deep part (parsing user clicks into note edits, regenerating MusicXML), likely
  deserves a dedicated owner given how much of the project's "human-in-the-loop" value
  proposition rides on it.

**Option B — split by layer:**
- One person owns the API-integration/state layer (all fetch calls, loading states,
  data shape matching FastAPI's responses).
- The other owns pure UI/rendering components.
- Can work well if you want to pair on which endpoints get built in step 8 together
  first.

## Suggested order, regardless of split

1. Nail down step 8's API shape together (what does `POST /upload`, `GET /status/:id`,
   `GET /result/:id` actually return?) — joint task, since both frontend tracks depend
   on it.
2. Build the "dumb" pipe: upload → status polling → static OSMD render of a finished
   score (no editing yet) — proves the whole chain works.
3. Add stem playback + waveform (parallel-able once step 2 works).
4. Add the correction interface last — hardest, and most dependent on the
   score-rendering piece being solid first.

## Related backlog item (your side)

Separately from the frontend, `scripts/run_pipeline.py` (Teammate A) currently chains
Demucs → classification → `transcription_service.run()` per stem, but stops at
transcription. Extending it so each stem's notes also flow through
quantization → musicxml → export (one MusicXML/MSCZ per stem, or combined into one
multi-part score — TBD) is a backlog item tracked in `CLAUDE.md`, owned by you
(Teammate B). This is the actual multi-stem end-to-end milestone; single-stem
end-to-end already works.
