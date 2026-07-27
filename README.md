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
which chains the whole thing for one input file. `app/main.py` and `app/api/*.py`
(the FastAPI HTTP layer) are not implemented yet — these scripts are the only way to
run the pipeline today.

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