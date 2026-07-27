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
   |________ Teammate A ________|    |___________ Teammate B (you) ___________|
```

**Team division:** Teammate A owns upload through stem classification. You (Teammate B)
own Basic Pitch transcription through score rendering/export. The handoff point is a
**stem audio file** (or the raw upload, if separation is skipped) — see "Handoff contract"
below.

| Stage            | Owner       | Does                                             | Tools                                  |
|------------------|-------------|---------------------------------------------------|-----------------------------------------|
| Preprocess       | Teammate A  | load, resample, mel-spectrogram, tempo/onset     | librosa, torchaudio, ffmpeg            |
| Separate         | Teammate A  | split mix into vocals/drums/bass/other stems     | Demucs (Hybrid Transformer)            |
| Classify (opt.)  | Teammate A  | label each stem's instrument/role                | AST / YAMNet / CNN — see gotchas       |
| Transcribe       | **You**     | stem → note events (pitch, onset, offset, vel.)  | Spotify Basic Pitch (piano: ByteDance) |
| Quantize/cleanup | **You**     | snap notes to a beat grid, filter low-confidence | librosa, madmom, music21, pretty_midi  |
| MusicXML         | **You**     | note events → score                              | music21, partitura                     |
| Render/export    | **You**     | score → PDF/PNG/SVG/MIDI; browser preview        | MuseScore CLI, OpenSheetMusicDisplay   |

### Handoff contract (Teammate A ↔ you)

Your transcription stage must be runnable against **any stem-shaped audio file** in
`samples/` (mono/stereo WAV or MP3) without depending on Teammate A's code having run:

- Don't import from Teammate A's services (`preprocessing_service.py`, `demucs_service.py`)
  or their in-progress schemas. Your services take a file path in, per "services are pure
  functions" below — same as any other audio input.
- Keep testing against raw clips in `samples/` (already doing this — `sample.mp3`,
  `sample2.mp3`) so your half is provably correct independent of whether separation/
  classification is finished.
- When Teammate A's stem output is ready, the only new input to your side is a stem file
  path (e.g. `storage/stems/<track>/other.wav`) — same shape as any other audio file, so
  no interface change should be needed on your end.

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
│   │   │   ├── upload.py             #   POST audio → save to storage/uploads      [Teammate A]
│   │   │   ├── stems.py              #   separation + stem endpoints              [Teammate A]
│   │   │   ├── transcribe.py         #   run transcription pipeline               [You]
│   │   │   └── export.py             #   return MusicXML / PDF / MIDI / stems     [You]
│   │   ├── config/
│   │   │   └── settings.py           # all paths + model config live here (no hardcoded paths) — shared
│   │   ├── core/                     # app-wide: logging, exceptions, deps (empty) — shared
│   │   ├── models/                   # PURPOSE TBD — ML model loaders/cache OR DB models (empty)
│   │   ├── schemas/                  # pydantic request/response + note-event models
│   │   │   ├── transcription.py      # [You] — note-event schema, shared currency into your stages
│   │   │   └── export.py             # [You]
│   │   ├── services/                 # ONE stage per file; pure functions (see conventions)
│   │   │   ├── preprocessing_service.py      # [Teammate A]
│   │   │   ├── demucs_service.py             # [Teammate A]
│   │   │   ├── transcription_service.py      # [You] — Basic Pitch
│   │   │   ├── quantization_service.py       # [You]
│   │   │   ├── musicxml_service.py           # [You]
│   │   │   └── export_service.py             # [You]
│   │   ├── utils/
│   │   │   ├── audio_utils.py        # load/convert/resample helpers — shared, don't fork
│   │   │   └── file_utils.py         # storage paths, safe filenames, cleanup — shared, don't fork
│   │   └── main.py                   # FastAPI app entrypoint — shared, touch last (step 8)
│   ├── scripts/                      # standalone smoke tests, run on samples/ files
│   │   ├── test_demucs.py            # [Teammate A]
│   │   ├── test_basic_pitch.py       # [You]
│   │   └── test_musicxml.py          # [You]
│   ├── storage/                      # all IO goes through here (see storage layout)
│   │   ├── uploads/  intermediate/  stems/  midi/  musicxml/  pdf/  mscz/
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

Every stage reads/writes through `storage/` via `file_utils`, never ad-hoc paths. This is
the shared contract between both halves of the pipeline — don't change directory names or
file-naming conventions without telling your teammate, since their output paths are your
input paths.

- `uploads/` raw user audio — written by Teammate A
- `stems/` Demucs output (per-track WAVs) — written by Teammate A, **read by you**
- `intermediate/` spectrograms, note-event JSON, anything between stages — shared scratch space
- `midi/` transcribed MIDI — written by you
- `musicxml/` generated `.musicxml` — written by you
- `pdf/` rendered scores (and PNG/SVG) — written by you
- `mscz/` editable MuseScore project files — written by you (primary export for the
  human-in-the-loop correction workflow; PDF/PNG/SVG are print/share formats, added later)

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
4. **Show the diff and the exact test command.** Don't modify unrelated stages/files —
   this now also means: don't touch your teammate's owned files (see ownership tags in the
   repository map above). If a shared file (`config/settings.py`, `utils/`, `main.py`) needs
   a change, call it out explicitly since it affects both of you.
5. **Ask before adding heavy dependencies**, and keep `requirements.txt` resolvable (pin versions
   when needed). Flag conflicts instead of silently upgrading. Since `requirements.txt` is shared,
   prefer additive changes (new lines) over reordering/removing your teammate's entries.
6. Prefer pretrained models. Don't train from scratch unless we explicitly decide to.
7. **Test against raw `samples/` clips, not your teammate's output**, until their stage is
   actually done — don't block your progress on their pipeline being finished (see Handoff
   contract above).

## Build order & status

Build the **spine first** (solo/piano end-to-end), then add the harder stages. Owner
tagged per step — you can drive your steps independent of Teammate A's progress, since
steps 2-4 and 6 only need a raw/stem clip from `samples/`, not Teammate A's actual code.

- [x] 0. Env + `requirements.txt` resolves; one `samples/` clip loads — shared, done
- [ ] 1. Preprocess → mel-spectrogram + tempo/onset  (`test_preprocessing.py`) — **Teammate A**
- [x] 2. Transcribe a clean solo stem → note events JSON  (`test_basic_pitch.py`) — **You, done**
- [x] 3. Note events → MusicXML  (`test_musicxml.py`) — **You, done** (two-staff grand
      staff, sweep-line overlap merge; chord quality is a follow-up, see Known gotchas)
- [x] 4. Render MusicXML → editable score  ← **first end-to-end demo (solo audio)** —
      **You, done** (`test_export.py`; exports to `.mscz` via MuseScore CLI, not PDF —
      matches the human-in-the-loop correction workflow. PDF/PNG/SVG export can be added
      later as a quality/export-variety item, same `export_service.py` call pattern.)
- [ ] 5. Demucs separation → feed a stem into step 2  (`test_demucs.py`) — **Teammate A**
- [x] 6. Quantization/cleanup (the fiddliest stage — test against a known-tempo clip) — **You, done** (backbone: global tempo + 16th-note grid; real beat-tracking is a quality follow-up)
- [ ] 7. Stem classification (only if needed — see gotchas) — **Teammate A**
- [ ] 8. FastAPI routes wiring the services together — **shared**, do last, together
- [ ] 9. Frontend (OSMD preview + correction UI) — **shared/TBD**, after 8

## Quality backlog (your side)

The backbone (steps 2, 3, 4, 6) works end-to-end but is intentionally rough. Once the
backbone was working, the plan was to circle back and improve each stage:

- [x] Q1. **Quantization quality (partial)** — `quantization_service.py` now maps each
      note's onset/offset to a fractional beat position by interpolating between real
      detected beat times (`librosa.beat.beat_track`, extrapolating at clip edges)
      instead of assuming one constant BPM, so the grid follows the actual tempo curve.
      Confidence filtering is now percentile-based (drops the bottom 10% of notes per
      clip) instead of a flat 0.2 cutoff that was filtering ~0 notes in practice.
      Also added `_merge_sustained_fragments()`: Basic Pitch sometimes emits one
      continuously-held note as 2+ back-to-back same-pitch fragments (~24% of notes on
      `sample2` were affected) — merged when the gap is tiny AND velocity doesn't
      increase (a real re-attack strikes as loud or louder; a split sustain decays),
      so a genuine repeated note isn't wrongly merged. Verified against real data before
      shipping (67 decaying-pattern vs 45 increasing-pattern candidates found first).
      **Still open:** no explicit rest insertion or tie generation across barlines in
      this stage (handled implicitly by musicxml_service's sweep-line instead), no
      merging for non-identical-pitch legato phrases.
- [x] Q2. **MusicXML/chord quality (partial)** — `musicxml_service.py`'s staff-splitting
      is rebuilt around `_split_two_hands()`: a direct search over every pair of
      octave-wide (MAX_CHORD_SPAN=12 semitones) pitch windows, picking whichever pair
      covers the most notes — correct by construction, so neither staff can ever exceed
      an octave from this step alone. `_assign_staff_per_note()` uses one combined
      sweep-line timeline (all notes, both hands) so a note's staff is decided once,
      at its own onset, and can't flip mid-hold. `_drop_octave_overflow()` handles the
      residual case where cross-onset overlap (two notes each correctly assigned at
      their own onset time can still end up sounding together later) still produces a
      too-wide combined chord on one staff — drops the pitches outside that segment's
      densest octave window (~5% of notes on real test clips) rather than reassigning,
      since two iterative "move overflow to the other staff" designs were tried and
      both hit stable oscillation (fixing one staff's violation recreated it on the
      other, indefinitely — verified by tracing violation counts pass-by-pass).
      Verified on two real clips: 0 chord-width violations, 0 pitch/duration coverage
      loss (for surviving notes), 0 notes double-assigned to both staves, still exactly
      1 voice per staff.
      **Still open:** no key signature detection, time signature still hardcoded 4/4,
      the ~5% dropped-note rate in dense passages is a real (if rare) trade-off, not
      eliminated.
- [x] Q4. **Transcription revisit** — `transcription_service.py` now calls Basic Pitch
      with `onset_threshold=0.6` (was the 0.5 default). At 0.5, real piano sustain was
      frequently split into 2+ back-to-back same-pitch fragments — verified up to 44%
      of raw notes on one real test clip (`sample.mp3`). Tested 0.6 and 0.7 against
      both clips using time-overlap matching (not exact-onset matching, which falsely
      flags small timing shifts as "lost notes"): both eliminate most split-fragments
      with **zero verified loss of real, high-confidence notes** — every apparently
      "missing" note had a same-pitch, time-overlapping replacement. Chose 0.6 over
      0.7 (which cut further) as the smaller deviation from Basic Pitch's own tested
      default. Did not touch `frame_threshold`/`minimum_note_length` — tested raising
      `minimum_note_length` first and it barely reduced the split-fragment rate (only
      discards short notes outright), confirming `onset_threshold` was the correct
      lever. Verified: 428/350 raw/quantized notes on `sample2.mp3`,
      647/352 on `sample.mp3`; full pipeline (transcribe → quantize → musicxml →
      export) runs clean on both.
- [x] **Key signature detection** — prioritized ahead of Q3 (export formats): MSCZ
      export already works well, and getting the notation itself more correct matters
      more right now than adding export file formats. `_detect_key()` in
      `musicxml_service.py` uses music21's built-in Krumhansl-Schmuckler-style key
      analysis over a flat Stream of the stem's notes (weighted by duration). Detected
      once per stem and applied consistently to every staff (so treble/bass never
      disagree). Verified on both real clips with strong confidence: `sample2.mp3` →
      A major (correlation 0.847), `sample.mp3` → C minor (correlation 0.833). Known
      limitation: relative major/minor ambiguity (e.g. C major vs. A minor share the
      same notes) is inherent to pitch-class-only key detection, not fixable without
      deeper harmonic analysis — not something this pass addresses.
- [x] **Real time-signature estimation** — `quantization_service._detect_time_signature()`
      uses madmom's `RNNDownBeatProcessor` + `DBNDownBeatTrackingProcessor` for real
      downbeat tracking (librosa has no downbeat/meter detection built in, confirmed
      by checking its API directly). The DBN decodes the most likely beat-position
      sequence for each candidate meter in `TIME_SIGNATURE_CANDIDATES = [3, 4]` and
      picks whichever fits best; the numerator is read off as the max beat number in
      the decoded sequence. Denominator is always reported as 4 (a known
      simplification — madmom reasons in beats-per-bar, not note-value subdivisions,
      so 6/8 vs. 3/4 can't be distinguished this way). Falls back to "4/4" on any
      failure (verified: correctly triggers on a silent/degenerate test input rather
      than crashing). Threaded through `QuantizationResult.time_signature` and applied
      in `musicxml_service._build_staff_part` (replacing the previous hardcoded 4/4).
      Verified on both real clips: `sample2.mp3` and `sample.mp3` both detected as
      4/4, confirmed present in the written MusicXML's `<time>` element, with the
      octave-cap invariant (0 violations) still holding on both.

      **madmom install was substantially harder than expected — worth knowing about
      if this needs reinstalling:** madmom 0.16.1 has no pre-built Windows wheel, so
      pip must compile its Cython extensions from source, which requires (1) `Cython`
      installed first (its `pyproject.toml` doesn't declare this correctly for pip's
      isolated build), and (2) a C compiler — Visual Studio Build Tools (C++ workload)
      had to be installed system-wide, since Windows has no C compiler by default.
      Beyond that, madmom 0.16.1's own code predates several Python/numpy
      deprecations and needed direct patching in the installed package
      (`venv/Lib/site-packages/madmom/`) to actually run:
      - `collections.MutableSequence` → `collections.abc.MutableSequence` in
        `processors.py` (moved in Python 3.3+, removed 3.10+).
      - `np.float`/`np.int`/etc. (removed in numpy>=1.24) — 99 occurrences across 19
        files, bulk-patched to the builtin equivalents.
      - One usage inside compiled Cython (`madmom/ml/hmm.pyx`, not patchable as text)
        still referenced `np.int` at runtime — worked around with a compatibility
        shim (`np.int = int` etc.) set at the top of `quantization_service.py` before
        madmom is imported, since editing compiled `.pyx` output wasn't practical.
      - A separate numpy behavior change (implicit ragged/inhomogeneous array
        construction, used by `DBNDownBeatTrackingProcessor.process()` to pick the
        best-scoring HMM) had to be patched directly in the installed
        `downbeats.py` — modern numpy raises `ValueError` where old numpy silently
        built an object array.
      None of these patches are tracked by pip/requirements.txt — they live only in
      this machine's `venv`. **If the venv is ever recreated, these steps must be
      redone** (or a maintained madmom fork/newer release found, if one exists by
      then) for time-signature detection to keep working.
- [x] **Fix redundant natural-sign accidentals** — after shipping key signature
      detection, sheet music was showing natural signs on notes that were already
      diatonic to the detected key (e.g. plain A and B in A major, which has no
      reason to ever show either as altered). Root cause: `note.Note(midi_int)` always
      gives the pitch an explicit `natural` Accidental object (not `None`), since
      music21 has no spelling context from a bare MIDI number. `Part.makeAccidentals()`
      (music21's own cautionary-accidental logic) was tried first and found to have a
      real bug for our case: `makeAccidentalsInMeasureStream` only filters
      `pitchPastMeasure` by "foreign to the key" when the current measure has its own
      explicit `Key` element; when it doesn't (our normal case — music21 puts `Key`
      only in the measure where it's set, not every measure), it falls back to
      treating ALL of the previous measure's pitches as needing cautionary
      re-display — confirmed on a minimal repro (20× B4 across 5 measures in A major):
      the first note of every measure after the first kept showing as needing display,
      even though B is fully diatonic and never once altered. Fixed by bypassing
      `makeAccidentals()` entirely: `_suppress_redundant_accidentals()` in
      `musicxml_service.py` compares each pitch directly against `Key.alteredPitches`
      (the letter names the key signature actually sharpens/flattens) and sets
      `displayStatus` accordingly — simpler and unaffected by the measure-boundary bug.
      Verified: 258 → 30 accidentals on `sample2.mp3` (A major), 30 remaining are all
      genuine C/G naturals (deviations from the key, correctly still shown); a
      positive-case test (F# in C major) confirmed the fix doesn't over-suppress real
      accidentals. Octave-cap invariant re-checked, still 0 violations on both clips.
- [x] **Fix notes/chords overflowing past measure boundaries** — after the accidental
      fix, rendered sheet music showed notes crossing barlines and irregular beam/tie
      groupings. Root cause: nothing in segment construction snaps a note/chord's
      cumulative beat position to measure boundaries, so `part.append(element)` can
      place an element that starts inside one measure and extends past the barline
      into the next. `makeMeasures()` alone doesn't split/tie such elements — it just
      lets them overflow, producing measures with more (or, for the next measure,
      fewer) beats than the time signature allows. Confirmed directly: measures 3 and
      4 of `sample2.mp3`'s treble part had 4.25 and 4.75 quarter-note beats instead of
      4.0. Fixed by calling `part.makeTies(inPlace=True)` right after `makeMeasures()`
      in `_build_staff_part` — this is music21's dedicated method for splitting
      elements that cross barlines into properly tied fragments per measure. Verified:
      0 measures (other than the legitimately-partial final one) deviate from 4.0
      beats on either staff, on both real clips; re-checked the accidental-suppression
      and octave-cap fixes still hold (30 accidentals unchanged, 0 octave violations).
- [ ] Q3. **Export quality** — add PDF/PNG/SVG export alongside MSCZ (same
      `export_service.py` subprocess pattern), better error surfacing if MuseScore
      CLI fails or isn't found at `MUSESCORE_PATH`, cleanup of intermediate files.
      Deprioritized behind key/time signature work (see above).
- [ ] **Extend `run_pipeline.py` to the full per-stem chain (You)** — Teammate A's new
      `scripts/run_pipeline.py` chains Demucs separation → classification verification →
      `transcription_service.run()` per stem (vocals/drums/guitar/piano), returning
      `Dict[str, List[NoteEvent]]`. It stops at transcription. You own extending this
      so each stem's note events also flow through `quantization_service.run()` →
      `musicxml_service.run()` → `export_service.to_mscz()`, producing one MusicXML/MSCZ
      per stem (or however multi-stem output should be organized — TBD whether stems
      combine into one multi-part score or stay separate files, decide before
      implementing). This is the actual multi-stem end-to-end milestone; single-stem
      end-to-end already works (step 4, done).

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
- **[RESOLVED, was TODO — chord quality] `musicxml_service.py` now assigns staff per-note**
  (`_assign_staff_per_note`), fixing the earlier over-chording where treble/bass assignment
  by whole-chord average pitch rarely split hands. Still no chord simplification (e.g.
  collapsing near-duplicate pitches or dropping low-confidence notes from dense chords) —
  a genuinely dense chord (up to 8 simultaneous notes seen on `sample2`) will still render
  as a literal 8-note chord rather than a simplified reduction. Revisit if real playtesting
  shows chords are too dense to read, independent of the treble/bass split now being correct.
- **madmom (time signature detection) needed manual patches applied directly to the
  installed package inside this machine's venv — these are NOT captured by
  requirements.txt and will need to be redone if the venv is ever recreated.** See the
  full list under the "Real time-signature estimation" entry in the Quality backlog
  above. In short: install `Cython` before `madmom`, install Visual Studio Build Tools
  (C++ workload) for the Windows C compiler, then hand-patch several files in
  `venv/Lib/site-packages/madmom/` for Python 3.11 / modern numpy compatibility (the
  package predates both). If this becomes a recurring pain point, worth checking for
  a maintained fork or newer release before repeating these steps.

## Housekeeping TODO

- `classification_service.py` now exists (Teammate A, `classification-stage` merge) —
  heuristic guitar/piano split on Demucs's `other.wav` stem, not ML-based.
- Decide the purpose of `app/models/` (ML model loaders/cache vs DB models) or remove it.
- Add at least one solo/piano clip **and** one mixed clip to `samples/`.
