# TranscriScore — Project Context

An AI study-group project: a web-based service that turns short audio clips into an
**editable first-draft of sheet music**. The output that matters is **MusicXML** (openable
and editable in MuseScore), not just MIDI. Workflow is **human-in-the-loop**: the model
produces a draft, the user corrects uncertain notes, then re-exports.

First-draft quality is acceptable. Prefer pretrained/off-the-shelf models over training
anything from scratch.

## Pipeline

```
upload → preprocess → separate → (classify stems) → transcribe (audio→MIDI)
      → quantize/cleanup → MusicXML → render → export + user correction
```

| Stage            | Does                                             | Tools                                  |
|------------------|--------------------------------------------------|----------------------------------------|
| Preprocess       | load, resample, mel-spectrogram, tempo/onset     | librosa, torchaudio, ffmpeg            |
| Separate         | split mix into vocals/drums/bass/other stems     | Demucs (Hybrid Transformer)            |
| Classify (opt.)  | label each stem's instrument/role                | AST / YAMNet / CNN — see gotchas       |
| Transcribe       | stem → note events (pitch, onset, offset, vel.)  | Spotify Basic Pitch (piano: ByteDance) |
| Quantize/cleanup | snap notes to a beat grid, filter low-confidence | librosa, madmom, music21, pretty_midi  |
| MusicXML         | note events → score                              | music21, partitura                     |
| Render/export    | score → PDF/PNG/SVG/MIDI; browser preview        | MuseScore CLI, OpenSheetMusicDisplay   |

## Tech stack

- **Backend:** Python, FastAPI, PyTorch/TensorFlow, Demucs + Basic Pitch, music21/partitura/mido,
  MuseScore CLI.
- **Frontend (build last):** React + TypeScript, OpenSheetMusicDisplay, waveform + stem player,
  note-correction interface.

## Repository map

```
TranscriScore/
├── backend/
│   ├── app/
│   │   ├── api/                      # thin FastAPI routers (no business logic)
│   │   │   ├── upload.py             #   POST audio → save to storage/uploads
│   │   │   ├── stems.py              #   separation + stem endpoints
│   │   │   ├── transcribe.py         #   run transcription pipeline
│   │   │   └── export.py             #   return MusicXML / PDF / MIDI / stems
│   │   ├── config/
│   │   │   └── settings.py           # all paths + model config live here (no hardcoded paths)
│   │   ├── core/                     # app-wide: logging, exceptions, deps (empty)
│   │   ├── models/                   # PURPOSE TBD — ML model loaders/cache OR DB models (empty)
│   │   ├── schemas/                  # pydantic request/response + note-event models
│   │   │   ├── transcription.py
│   │   │   └── export.py
│   │   ├── services/                 # ONE stage per file; pure functions (see conventions)
│   │   │   ├── preprocessing_service.py
│   │   │   ├── demucs_service.py
│   │   │   ├── transcription_service.py     # Basic Pitch
│   │   │   ├── quantization_servie.py        # ⚠ typo: rename to quantization_service.py
│   │   │   ├── musicxml_service.py
│   │   │   └── export_service.py
│   │   ├── utils/
│   │   │   ├── audio_utils.py        # load/convert/resample helpers
│   │   │   └── file_utils.py         # storage paths, safe filenames, cleanup
│   │   └── main.py                   # FastAPI app entrypoint
│   ├── scripts/                      # standalone smoke tests, run on samples/ files
│   │   ├── test_demucs.py
│   │   ├── test_basic_pitch.py
│   │   └── test_musicxml.py
│   ├── storage/                      # all IO goes through here (see storage layout)
│   │   ├── uploads/  intermediate/  stems/  midi/  musicxml/  pdf/
│   ├── tests/                        # (empty) unit tests
│   └── requirements.txt
├── docs/
├── frontend/                         # build LAST, after the script pipeline works
├── project plans/
├── samples/                          # test audio — needs 1 solo + 1 mixed clip
├── .gitignore
└── README.md
```

## Storage layout

Every stage reads/writes through `storage/` via `file_utils`, never ad-hoc paths:

- `uploads/` raw user audio
- `stems/` Demucs output (per-track WAVs)
- `intermediate/` spectrograms, note-event JSON, anything between stages
- `midi/` transcribed MIDI
- `musicxml/` generated `.musicxml`
- `pdf/` rendered scores (and PNG/SVG)

## Code conventions

- **Services are pure functions.** Signature style: `def run(input_path: str, ...) -> Result`
  returning an output **path** or a typed object. No FastAPI imports inside `services/`.
- **API routers are thin** — parse request, call a service, return a schema. No pipeline logic in routers.
- **Config, not constants.** Read paths and model settings from `config/settings.py`.
- **Schemas are pydantic.** Define note events (pitch, onset, offset, duration, velocity, confidence)
  once in `schemas/transcription.py` and reuse across stages.
- Type hints + short docstrings on every service function.
- Keep note events as the common currency between transcribe → quantize → musicxml.

## How we work (rules for Claude Code)

1. **One stage at a time.** Implement a single service, nothing else.
2. **Every stage must run standalone** via its `scripts/test_*.py` on a file in `samples/`
   and print/inspectable output **before** we move on.
3. **Services first, API later.** Get the pipeline working as a script chain, then wrap in FastAPI.
4. **Show the diff and the exact test command.** Don't modify unrelated stages/files.
5. **Ask before adding heavy dependencies**, and keep `requirements.txt` resolvable (pin versions
   when needed). Flag conflicts instead of silently upgrading.
6. Prefer pretrained models. Don't train from scratch unless we explicitly decide to.

## Build order & status

Build the **spine first** (solo/piano end-to-end), then add the harder stages:

- [ ] 0. Env + `requirements.txt` resolves; one `samples/` clip loads
- [ ] 1. Preprocess → mel-spectrogram + tempo/onset  (`test_preprocessing.py`)
- [ ] 2. Transcribe a clean solo stem → note events JSON  (`test_basic_pitch.py`)
- [ ] 3. Note events → MusicXML  (`test_musicxml.py`)
- [ ] 4. Render MusicXML → PDF  ← **first end-to-end demo (solo audio)**
- [ ] 5. Demucs separation → feed a stem into step 2  (`test_demucs.py`)
- [ ] 6. Quantization/cleanup (the fiddliest stage — test against a known-tempo clip)
- [ ] 7. Stem classification (only if needed — see gotchas)
- [ ] 8. FastAPI routes wiring the services together
- [ ] 9. Frontend (OSMD preview + correction UI)

## Known gotchas

- **Dependencies are heavy and conflict-prone** (torch, demucs, basic-pitch, and TensorFlow if
  using YAMNet). basic-pitch has historically pinned specific TF/coremltools versions — resolve
  this early in step 0, in a virtualenv.
- **MuseScore is a system binary**, not a pip package — it must be installed separately and called
  via CLI.
- **Basic Pitch onsets won't line up to a grid** — the quantization stage is what makes output
  readable, and it's the hardest part. Budget real time there.
- **Demucs already names its stems** (vocals/drums/bass/other), so classification is partly
  redundant. Off-the-shelf YAMNet/AST gives generic audio tags, not clean instrument labels.
  Consider using Demucs's stem names first and adding classification only if finer roles are needed.

## Housekeeping TODO

- Rename `services/quantization_servie.py` → `quantization_service.py` (typo will break imports).
- No `classification_service.py` exists yet — decide whether to add one or fold classification
  into `stems.py` / skip it (see gotchas).
- Decide the purpose of `app/models/` (ML model loaders/cache vs DB models) or remove it.
- Add at least one solo/piano clip **and** one mixed clip to `samples/`.
