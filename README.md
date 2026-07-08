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

## Testing the transcription → export pipeline

All commands run from `backend/`. Each stage has a standalone smoke-test script in
`scripts/`, and each one accepts `--file <path>` to run against any audio file, or a
`--from-cache`/`--from-musicxml` flag to reuse a previous stage's output instead of
recomputing it from scratch.

### 0. Environment check (confirms audio loads at all)

```
./venv/Scripts/python.exe scripts/test_env.py
```

No arguments — picks the first file in `samples/` and confirms librosa/ffmpeg can load it.

### 1. Transcription only (audio → MIDI + note events)

```
./venv/Scripts/python.exe scripts/test_basic_pitch.py --file ../samples/YOUR_FILE.mp3
```

Saves: `storage/midi/YOUR_FILE.mid`, `storage/intermediate/YOUR_FILE.notes.json`

### 2. Quantization only

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

### 3. MusicXML only

Reusing a previous quantization:

```
./venv/Scripts/python.exe scripts/test_musicxml.py --from-cache YOUR_FILE
```

Or fresh (re-transcribes + re-quantizes):

```
./venv/Scripts/python.exe scripts/test_musicxml.py --file ../samples/YOUR_FILE.mp3
```

Saves: `storage/musicxml/YOUR_FILE.musicxml`

### 4. Export only (MusicXML → MSCZ)

```
./venv/Scripts/python.exe scripts/test_export.py --from-musicxml YOUR_FILE
```

Or from a saved quantization (`--from-cache YOUR_FILE`), or fully fresh
(`--file ../samples/YOUR_FILE.mp3`).

Saves: `storage/mscz/YOUR_FILE.mscz`

### Full pipeline in one shot (audio → MSCZ)

```
./venv/Scripts/python.exe scripts/test_export.py --file ../samples/YOUR_FILE.mp3
```

This is the true end-to-end test — runs transcription → quantization → MusicXML → export
in one command.

### Quick reference

| Script                 | `--file <path>` | `--from-cache <name>`               | `--from-musicxml <name>`  |
|-------------------------|:---:|:---:|:---:|
| `test_env.py`           | — (auto-picks first file) | — | — |
| `test_basic_pitch.py`   | ✓ | — | — |
| `test_quantization.py`  | ✓ | ✓ (skips transcription) | — |
| `test_musicxml.py`      | ✓ | ✓ (skips transcription+quantization) | — |
| `test_export.py`        | ✓ | ✓ (skips transcription+quantization) | ✓ (skips everything but export) |

`test_demucs.py` is Teammate A's script (source separation) and is not yet implemented.