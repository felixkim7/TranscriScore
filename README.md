# TranscriScore

An AI study-group project: a web-based service that turns short audio clips into an
editable first-draft of sheet music. See `CLAUDE.md` for full architecture, pipeline,
and team-ownership details.

## Backend setup

```
cd backend
python -m venv venv
./venv/Scripts/pip.exe install -r requirements.txt
```

You'll also need [ffmpeg](https://ffmpeg.org/) and [MuseScore 4](https://musescore.org/)
installed separately (system binaries, not pip packages). If ffmpeg isn't on PATH, prepend
its `bin/` directory to `PATH` before running scripts.

## The full pipeline, step by step

The backend is split into two halves, owned by the two of us (see `CLAUDE.md` for the
full team-ownership breakdown):

- **Upload → preprocessing → separation → classification** (Teammate A)
- **Transcription → quantization → MusicXML → export** (Teammate B, this repo owner)

All commands below run from `backend/`. Every stage has a standalone smoke-test script
in `scripts/` so you can run and inspect each step in isolation, plus `run_pipeline.py`
which chains the whole thing for one input file. There's also a FastAPI HTTP layer
(`app/main.py`, `app/api/*.py`) that wraps the same pipeline behind an async job API —
see "Running the server" below.

### 0. Environment check (confirms audio loads at all)

```
./venv/Scripts/python.exe scripts/test_env.py
```

No arguments — picks the first file in `samples/` and confirms librosa/ffmpeg can load it.

### 1. Source separation (Teammate A) — mixed audio → stems

```
./venv/Scripts/python.exe scripts/test_demucs.py ../samples/YOUR_FILE.mp3
```

Runs Demucs (`htdemucs_6s` model) and splits the input into `vocals.wav`, `drums.wav`,
`guitar.wav`, and `piano.wav`. Saves to `storage/stems/htdemucs_6s/YOUR_FILE/`.
(`bass.wav`/`other.wav` are also written by Demucs itself but not read back — see
`DEMUCS_STEM_NAMES` in `app/config/settings.py`.)

### 2. Stem-label classification (Teammate A) — sanity-check Demucs's labels

```
./venv/Scripts/python.exe scripts/test_classification.py
```

Picks the first file in `samples/` and runs the rule-based classifier
(`classify_stem`) that distinguishes guitar vs. piano accompaniment by spectral
features. In the real pipeline this re-checks Demucs's own `guitar.wav`/`piano.wav`
labels rather than classifying from scratch, since Demucs's docs flag piano
separation as bleed-prone; `vocals.wav`/`drums.wav` are trusted directly with no
check. See `app/services/classification_service.py` for the full rationale.

### 3. Transcription (Teammate B) — audio → MIDI + note events

```
./venv/Scripts/python.exe scripts/test_basic_pitch.py --file ../samples/YOUR_FILE.mp3
```

Runs Spotify's Basic Pitch on a single audio file (a stem, or a full mixed clip —
this stage doesn't care which). Saves: `storage/midi/YOUR_FILE.mid`,
`storage/intermediate/YOUR_FILE.notes.json`

### 4. Quantization (Teammate B)

Reusing a previous transcription (skips re-running Basic Pitch):

```
./venv/Scripts/python.exe scripts/test_quantization.py --from-cache YOUR_FILE
```

(stem name, no extension — e.g. `sample2`; requires step 1 already run for that file, and
the original audio still present in `samples/` for beat detection)

Or fresh (re-transcribes first):

```
./venv/Scripts/python.exe scripts/test_quantization.py --file ../samples/YOUR_FILE.mp3
```

Saves: `storage/midi/quantized/YOUR_FILE.mid`, `storage/intermediate/YOUR_FILE.quantized.json`

### 5. MusicXML (Teammate B)

Reusing a previous quantization:

```
./venv/Scripts/python.exe scripts/test_musicxml.py --from-cache YOUR_FILE
```

Or fresh (re-transcribes + re-quantizes):

```
./venv/Scripts/python.exe scripts/test_musicxml.py --file ../samples/YOUR_FILE.mp3
```

Saves: `storage/musicxml/YOUR_FILE.musicxml`

### 6. Export (Teammate B) — MusicXML → MSCZ

```
./venv/Scripts/python.exe scripts/test_export.py --from-musicxml YOUR_FILE
```

Or from a saved quantization (`--from-cache YOUR_FILE`), or fully fresh
(`--file ../samples/YOUR_FILE.mp3`).

Saves: `storage/mscz/YOUR_FILE.mscz`

### Single-file end-to-end (audio → MSCZ, transcription-only side)

```
./venv/Scripts/python.exe scripts/test_export.py --file ../samples/YOUR_FILE.mp3
```

Runs transcription → quantization → MusicXML → export in one command, on one audio
file directly (no separation/classification). Good for testing the transcription→export
half in isolation against a solo instrument sample.

### Full pipeline (separation → classification → transcription → combined MSCZ)

```
./venv/Scripts/python.exe scripts/run_pipeline.py ../samples/YOUR_FILE.mp3
```

This is the real multi-stem chain, end to end: Demucs separation → label verification
(classification) → Basic Pitch transcription → quantization, run per stem (vocals,
drums, guitar, piano) on a mixed input clip, then all stems are combined into **one**
multi-part MusicXML/MSCZ (each stem is its own part — mute/hide/extract individual
parts later in MuseScore or another notation program; stems aren't kept as separate
final files).

Saves:
- `storage/musicxml/stems/<stem_name>.musicxml` — each stem's own transcription,
  written individually before combining, for inspecting/debugging one stem in
  isolation (e.g. checking the piano part's notation without the whole band).
- `storage/musicxml/YOUR_FILE.musicxml` — the final combined multi-part score.
- `storage/mscz/YOUR_FILE.mscz` — the combined score exported to MuseScore format.

Stems that end up shorter than the longest stem (different tempo/audio length) are
padded with trailing rests so every part has the same number of measures — required
for MuseScore to accept a multi-part file at all (it hard-rejects mismatched measure
counts across parts).

## Running the server

The FastAPI app wraps the same pipeline behind an HTTP API, so a frontend (or `curl`)
can kick off a transcription without going through `run_pipeline.py` directly. Runs
from `backend/`:

```
./venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Add `--reload` while developing so the server restarts automatically on code changes.
Once it's up:

- `http://127.0.0.1:8000/health` — liveness check
- `http://127.0.0.1:8000/docs` — interactive Swagger UI (try requests from the browser)

### API shape

Processing is async AND split into 3 phases with 2 review checkpoints in between —
`POST /upload` only runs separation, then pauses; the pipeline doesn't run straight
through to a final result automatically. Poll `GET /status/{job_id}`; when `status`
is `awaiting_review`, call `POST /jobs/{job_id}/continue` to run the next phase.
Repeat until `status` is `done` (or `failed`).

```
upload -> [separating] -> awaiting_review (after_separation)
       -> continue -> [transcribing] -> awaiting_review (after_transcription)
       -> continue -> [quantizing -> reconciling_tempo -> rendering_musicxml -> exporting] -> done
```

| Endpoint | Method | Does |
|---|---|---|
| `/upload` | POST | Accepts an audio file (`.mp3`/`.wav`/`.flac`/`.m4a`, multipart form field `file`), saves it, runs separation in the background, returns a `Job` with a `job_id` |
| `/status/{job_id}` | GET | Current `status` (pending/processing/awaiting_review/done/failed), `stage`, and — while `awaiting_review` — `checkpoint` (`after_separation`/`after_transcription`) plus that checkpoint's data (`separation_checkpoint` or `transcription_checkpoint`) |
| `/jobs/{job_id}/continue` | POST | Resumes a job paused at `awaiting_review`, running whichever phase comes next (decided from the job's own `checkpoint`, not passed in). 409 if the job isn't currently awaiting review |
| `/result/{job_id}` | GET | Once done: combined MusicXML/MSCZ paths + per-stem breakdown (tempo, note count, stem MusicXML path). 409 if not finished yet, 422 if the job failed |
| `/export/{job_id}/{format}` | GET | Downloads the actual file. `format` is `musicxml`, `mscz`, or `stem-musicxml` (needs `?stem=<name>`, e.g. `?stem=guitar`) |
| `/audio/{job_id}` | GET | The original uploaded audio, for a full-mix waveform view |
| `/audio/{job_id}/{stem}` | GET | One separated stem's WAV audio. Available as soon as separation finishes — doesn't require the whole job to be `done` |

Example with `curl`:

```
curl -X POST http://127.0.0.1:8000/upload -F "file=@../samples/YOUR_FILE.mp3;type=audio/mpeg"
# -> {"job_id": "...", "status": "pending", ...}

curl http://127.0.0.1:8000/status/YOUR_JOB_ID
# -> poll until "status": "awaiting_review" (checkpoint: "after_separation")
# -> at this point, GET /audio/YOUR_JOB_ID/<stem> already works if you want to listen first

curl -X POST http://127.0.0.1:8000/jobs/YOUR_JOB_ID/continue
curl http://127.0.0.1:8000/status/YOUR_JOB_ID
# -> poll until "status": "awaiting_review" (checkpoint: "after_transcription")

curl -X POST http://127.0.0.1:8000/jobs/YOUR_JOB_ID/continue
curl http://127.0.0.1:8000/status/YOUR_JOB_ID
# -> poll until "status": "done"

curl http://127.0.0.1:8000/result/YOUR_JOB_ID

curl -o output.mscz http://127.0.0.1:8000/export/YOUR_JOB_ID/mscz
```

Job records persist to `storage/jobs/<job_id>.json`; uploaded files land in
`storage/uploads/<job_id>.<ext>` (named after the job ID, not the original filename, so
two uploads sharing a name never collide). Between checkpoints, nothing is held in
memory — resumable state lives on disk (separated stems, transcribed note events) or
in the job record itself, so a server restart mid-pause loses nothing.

### Quick reference

| Script                    | Owner | `--file <path>` | `--from-cache <name>`                | `--from-musicxml <name>`          |
|----------------------------|-------|:---:|:---:|:---:|
| `test_env.py`              | —     | — (auto-picks first file) | — | — |
| `test_demucs.py`           | A     | ✓ (positional arg, no flag) | — | — |
| `test_classification.py`   | A     | — (auto-picks first file) | — | — |
| `test_basic_pitch.py`      | B     | ✓ | — | — |
| `test_quantization.py`     | B     | ✓ | ✓ (skips transcription) | — |
| `test_musicxml.py`         | B     | ✓ | ✓ (skips transcription+quantization) | — |
| `test_export.py`           | B     | ✓ | ✓ (skips transcription+quantization) | ✓ (skips everything but export) |
| `run_pipeline.py`          | A→B   | ✓ (positional arg, no flag) | — | — |