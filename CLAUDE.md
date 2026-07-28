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
| Quantize/cleanup | **You**     | snap notes to a beat grid, filter low-confidence | librosa, music21, pretty_midi          |
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
- [x] 8. FastAPI routes wiring the services together — **You, done** (see full
      writeup in the Quality backlog section below). Built the whole surface
      (not just your owned stages) per explicit direction, rather than waiting
      to coordinate `main.py`/`upload.py`/`stems.py` jointly as originally
      planned — Teammate A's `upload.py`/`stems.py` routes are effectively
      absorbed into `POST /upload`, since the pipeline already does separation
      internally; `app/api/stems.py` is still unwritten/unused.
- [ ] 9. Frontend (upload/status/read-only OSMD preview/export — NOT an in-browser
      correction UI) — **shared**, split by feature into two tracks (pipeline+media
      vs. score preview+export) — see `docs/frontend-plan.md` for the concrete
      split, build order, and known gaps (missing audio-serving endpoint).
      Scope decision: editing happens in MuseScore (opening the downloaded
      `.mscz`), not in the browser — this is consistent with the human-in-the-loop
      workflow already described above ("the model produces a draft, the user
      corrects, then re-exports" — MuseScore was always the intended correction
      tool; the frontend's job is running the pipeline and handing off files, not
      re-implementing a notation editor). Cuts the correction interface and
      tempo/time-signature re-quantize-on-demand endpoints from the original plan.

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
- [x] **Real time-signature estimation — tried via madmom, then reverted; 4/4 hardcoded
      instead.** `quantization_service._detect_time_signature()` (madmom's
      `RNNDownBeatProcessor` + `DBNDownBeatTrackingProcessor` for downbeat tracking)
      worked and was verified correct on both test clips, but madmom's install cost
      turned out to be very high for this one feature: no pre-built Windows wheel, a
      from-source Cython + MSVC build (needed installing Visual Studio Build Tools
      system-wide), and hand-patching 3 separate Python 3.11/numpy compatibility
      breaks directly inside the installed package — none of which was tracked by
      requirements.txt, so it would all need repeating on any fresh machine/venv.
      Considered Essentia as an alternative (also referenced in the original project
      proposal): ruled out immediately — it has no Windows wheel at all, and its
      source build fails on Windows with an internal error in Essentia's own
      `setup.py`, not something patchable the way madmom's deprecated-API issues were.
      **Decision: removed madmom entirely** (`_detect_time_signature`, the numpy
      compatibility shim, `TIME_SIGNATURE_CANDIDATES`, uninstalled from the venv and
      from `requirements.txt`). `QuantizationResult.time_signature` is now always
      `DEFAULT_TIME_SIGNATURE = "4/4"` — by far the most common meter, and both test
      clips detected as 4/4 anyway, so no real accuracy was given up for these clips.
      A time-signature picker (alongside the already-planned tempo picker) is tracked
      in `docs/frontend-plan.md` so the user can override it for pieces genuinely in
      3/4, 6/8, etc. Verified after removal: full pipeline runs clean on both clips,
      octave-cap/accidental/measure-integrity invariants all still hold.
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
- [x] **Extend `run_pipeline.py` to the full per-stem chain (You)** — done. Decided:
      stems combine into one multi-part MusicXML/MSCZ (not separate files per stem) —
      the user can mute/hide/extract individual parts later in MuseScore or another
      notation program. `run_pipeline.py` now runs Demucs separation → classification
      verification → `transcription_service.run()` → `quantization_service.run()` per
      stem, writes each stem's own MusicXML to `storage/musicxml/stems/` (via the new
      `musicxml_service.write_stem_musicxml()`, for inspecting one stem's transcription
      in isolation), then combines all stems into one score via the new
      `musicxml_service.build_score()`/`run_combined()` and exports one MSCZ via
      `export_service.to_mscz()`.

      Bonus find while testing this: a real, pre-existing bug, not something the
      combining work introduced but only exposed by it. `_build_staff_part()` capped
      any segment (note, chord, OR rest) longer than `MAX_DURATION_BEATS` (4 beats) to
      one element of that length, but still advanced its cursor by the segment's FULL
      length — silently discarding the remainder rather than splitting it into multiple
      consecutive elements. This mattered for combining because stems end at different
      real times (different tempo/length) and MuseScore hard-rejects a multi-part score
      where parts don't all have the same measure count ("Incomplete measure ...
      Found: 0/1. Expected: 4/4."); padding a shorter stem's part out to match the
      longest stem's length produces one large trailing rest segment, which hit exactly
      this truncation bug. Fixed by splitting any over-length segment into a loop of
      multiple `MAX_DURATION_BEATS`-sized elements instead of one capped element.
      Confirmed via MuseScore's own crash logs (`%LOCALAPPDATA%/MuseScore/MuseScore4/
      logs/`, not visible from the CLI's stdout/stderr, which was silent) — this same
      truncation bug could in principle also have been silently dropping real note/
      chord content over 4 beats long in ordinary (non-combined) scores; not yet
      re-audited against real transcriptions for that case specifically.

      Also had to fix the padding math itself: converting a shared "combined end time
      in seconds" into each stem's own beats and rounding independently could still
      land two stems on different final measure counts (their own tempos round the gap
      differently). Fixed by computing the target as the MAX measure count across every
      stem's own conversion of that shared end time, then padding all stems to that one
      shared count.

      Second bonus find, hit when actually running the real pipeline end-to-end (with
      real Demucs separation, not simulated stems) on `sample.mp3`: a real, pre-existing
      bug in `quantization_service._time_to_beat()`'s edge extrapolation. When librosa's
      beat tracker detects its first beat far into a clip (e.g. a separated stem that's
      mostly silence/bleed until real content starts — observed: first detected beat at
      42s into a 53s "piano" stem), extrapolating backward to t=0 using the tight
      interval between the first two detected beats projects across that whole silent
      gap and produces a wildly negative beat position (observed: -101 beats). This
      corrupted `_pad_to_end_beat()`'s assumptions (built on "segments end at some
      positive beat," not "segments start around -101") and produced mismatched, wrong
      measure counts downstream — a different presentation of the same "Incomplete
      measure" MuseScore rejection as the first bug, but a completely different root
      cause. Fixed by flooring the extrapolated result at 0 (a note genuinely can't
      sound before the clip starts). This also changed some stems' quantized note
      counts substantially (e.g. drums 107→4, piano 142→26 quantized notes) — not a
      regression: those notes were never real content at negative time positions, they
      were an artifact of the extrapolation bug placing real near-t=0 audio content at
      fabricated large-negative beat positions, where many then collapsed/duplicate-
      merged once correctly floored to 0.

      Environment fixes needed along the way: `demucs` wasn't in `requirements.txt` or
      installed in this venv at all (added it); installing it transitively upgraded
      `setuptools` to a version that no longer bundles `pkg_resources`, which `resampy`
      (a basic-pitch dependency) imports directly — broke basic-pitch's import chain
      entirely. Pinned `setuptools<81` in `requirements.txt` to fix. Also fixed
      `demucs_service.py` to invoke `[sys.executable, "-m", "demucs", ...]` instead of
      a bare `"demucs"` command — the bare form only resolves if the venv's `Scripts/`
      dir happens to be on `PATH` (e.g. an activated venv shell), and failed with
      `FileNotFoundError` when scripts are run via `./venv/Scripts/python.exe` directly.

      Full pipeline verified end-to-end on `sample.mp3` after both fixes: real Demucs
      separation (htdemucs_6s) → classification → transcription → quantization → 4
      per-stem MusicXML files in `storage/musicxml/stems/` → 1 combined 4-part
      MusicXML → 1 combined MSCZ, all 4 parts matching at 32 measures, MSCZ verified
      to open/re-export cleanly in MuseScore.

      Extended again to use all 6 htdemucs_6s stems (previously bass/other were left
      unused): `DEMUCS_STEM_NAMES` in `settings.py` now includes all 6; `run_pipeline.py`
      trusts `bass`/`other` directly (no classifier exists for them — `classify_stem()`
      only distinguishes guitar vs. piano); `musicxml_service.py` already had a `"bass"`
      routing branch (single bass-clef staff) that was just unused until now, and
      `"other_accompaniment"` falls through to the default piano-grand-staff branch.
      Verified end-to-end with all 6 stems, all parts matching measure counts, MSCZ
      opening cleanly.

      **Tempo reconciliation across stems, done.** Previously each stem kept its own
      independently-detected tempo in the combined score — correct measure *count*
      (via the padding logic above) but not synchronized rhythm, since nothing aligned
      different stems' beats to real seconds. Now: `quantization_service.detect_tempo()`
      runs once on the ORIGINAL mixed audio (before separation) to get one reference
      tempo — the fullest, most reliable single signal, rather than trying to vote among
      6 separated-stem estimates of wildly varying reliability (a stem with only 3-4
      real notes still produces a full, usually-meaningless tempo estimate).
      `quantization_service.reconcile_tempo()` then compares every stem's own detected
      tempo against that reference (ratio within `TEMPO_AGREEMENT_TOLERANCE`, ±8%, counts
      as agreeing) and re-quantizes any stem that disagrees — from its raw, seconds-based
      `NoteEvent`s (not the already-quantized beat-based notes), calling
      `quantization_service.run()` again with `tempo_bpm` forced to the reference. This
      actually re-derives the stem's beat grid against the shared tempo, not just
      relabeling a number. Ratios near 2.0 or 0.5 are flagged distinctly as the classic
      beat-tracker octave error (locked onto the eighth-note or half-note pulse) vs. a
      more general mismatch, since it's such a common, well-understood case.
      `run_pipeline.py`'s `main()` now runs: per-stem quantization (each stem's own
      tempo) → reference tempo detection → reconciliation → per-stem MusicXML (written
      only AFTER reconciliation, so the debug files in `storage/musicxml/stems/` reflect
      the synced tempo) → combine → export. Verified on `sample.mp3`: reference tempo
      147.66 BPM; guitar (73.83 BPM, ratio 0.50) correctly flagged as an octave error and
      re-quantized; vocals (95.70 BPM, ratio 0.65) correctly flagged as disagreeing and
      re-quantized; drums/bass/other/piano left alone (within tolerance). All 6 parts
      still matched at 21 measures after reconciliation; MSCZ verified to open cleanly.

      Time signature is NOT part of this reconciliation — it's still hardcoded 4/4 for
      every stem (see `DEFAULT_TIME_SIGNATURE`), so there's nothing to disagree on yet.
      If real time-signature detection gets added later, the same reference-audio
      approach (detect once from the original mix, reconcile stems against it) should
      apply there too.

      Also fixed in passing: two pre-existing `print()` calls with em-dash characters
      crashed with `UnicodeEncodeError` on this Windows machine's cp949 console
      encoding (non-ASCII characters aren't safe in `print()` output here) — replaced
      with plain hyphens. Only surfaced now because the new reconciliation code's
      logging path was the first to actually execute one of these lines in a real run.

      **Drum recognition, fixed — Basic Pitch was the wrong tool entirely.** User
      reported drums were "almost not being transferred at all." Root cause confirmed
      directly: Basic Pitch is a pitched-note (fundamental-frequency) model, not built
      for unpitched percussion — on a real 50-second drum stem it found only 17
      "notes," all short (~0.15-0.3s), low-confidence (amplitude 0.3-0.45), clustered
      in one narrow pitch range. Not a threshold-tuning problem; the model has no
      concept of a kick/snare/hi-hat.

      Fixed by adding a dedicated `app/services/drum_transcription_service.py`,
      routed to instead of `transcription_service.run()` for the drums stem only
      (`run_pipeline.py`). Uses librosa's onset detector (built for finding transient
      attacks, no pitch assumption) instead of Basic Pitch, then classifies each onset
      into kick/snare/hihat and emits it as a `NoteEvent` using a General MIDI
      percussion pitch number (36/38/42) as a stand-in "pitch" — this lets drum hits
      flow through the existing NoteEvent → quantization → tempo-reconciliation
      pipeline completely unchanged; only `musicxml_service.py`'s new
      `_build_percussion_part()` (percussion clef, `note.Unpitched` at fixed staff
      positions per GM pitch, no key signature) interprets those numbers differently
      from a real melodic pitch.

      Voice classification took two attempts. First tried spectral centroid alone
      (same approach as `classification_service.classify_stem()`), with thresholds
      guessed by ear — checked against 191 real onsets from a real separated drum
      stem and found completely wrong for kick detection: every single real onset's
      centroid landed in the 1000-7000Hz range, because a short post-onset window's
      spectrum is dominated by broadband transient "click" energy regardless of drum
      type, drowning out a kick's actual low-frequency body. Would have classified 0
      of 191 onsets as kick. Fixed with a two-stage approach instead: stage 1 (kick
      vs. not) uses the ratio of STFT energy below 150Hz to the window's total energy
      — this showed a clean bimodal split on the same real data (most onsets near
      ~0.0-0.1, kick-dominated ones above ~0.7); stage 2 (snare vs. hihat, only for
      non-kick onsets) falls back to spectral centroid, at a threshold recalibrated
      from real data's observed range — though this specific split (snare vs. hihat)
      wasn't as cleanly bimodal in the real data checked, so it's flagged as the least
      reliable of the three voice classifications (see settings.py's
      `DRUM_SPECTRAL_CENTROID_SNARE_HZ` comment).

      Verified end-to-end: drums note count went from Basic Pitch's ~3-17 raw notes
      (on `sample.mp3`/`sample5.mp3`) to 110-191 raw onsets with a plausible kick/
      snare/hihat distribution on both files (not degenerate/single-voice), full
      pipeline run producing a combined score with the drums part correctly showing
      a percussion clef and unpitched noteheads, matching measure count with every
      other part, MSCZ verified to open/export cleanly.

      Known simplification, not yet addressed: when multiple drum voices land in the
      same sweep-line segment (simultaneous kick+hihat, common on a real backbeat),
      only one is notated (kick/snare prioritized over hi-hat — see
      `DRUM_VOICE_PRIORITY` in musicxml_service.py) rather than rendering independent
      simultaneous noteheads on one staff — real multi-voice percussion notation was
      out of scope for this pass.

      **Per-sample output folders, fixed — a real cross-sample file collision.** User
      reported `storage/intermediate/`, `storage/midi/`, and `storage/musicxml/`
      wrote every stem's files flat (e.g. `drums.mid`, `piano.notes.json`), keyed only
      by DEMUCS STEM NAME, never the original sample's name. Confirmed as a real bug:
      running `run_pipeline.py` on two different samples silently overwrote each
      other's same-named stem files (running on `sample.mp3` then `sample5.mp3` left
      only `sample5`'s `drums.mid` on disk — `sample.mp3`'s was gone, no error, no
      warning). `storage/stems/` (Demucs's own output) already avoided this by
      nesting under `<model>/<input_sample_stem>/<demucs_stem_name>.wav` — the fix
      extends the same pattern to the other three directories.

      Added `settings.stem_output_dir(base_dir, input_stem)`: returns
      `base_dir/input_stem/` when `input_stem` is given, or `base_dir` unchanged when
      omitted. Threaded an optional `input_stem` parameter through every write/read
      site that needed it: `transcription_service.run()/load_note_events()`,
      `drum_transcription_service.run()`, `quantization_service.run()/
      load_quantization_result()/to_midi()/reconcile_tempo()`, `musicxml_service.
      write_stem_musicxml()`. `run_pipeline.py` now passes the original sample's
      filename stem (e.g. `"sample5"`) through every one of these calls.

      Scope decision: the single-file test scripts (`test_musicxml.py`,
      `test_export.py`, etc. — which transcribe one file directly with no
      separation, so `output_name` already IS the sample name) were deliberately
      NOT changed to nest — there's no collision risk for them, and nesting would
      have changed where their output lands for no benefit. `musicxml_service.run()`/
      `run_combined()` (the single-stem and combined-score writers, keyed by
      `output_name` which is always the sample name already) also didn't need
      changes — only `write_stem_musicxml()` (keyed by Demucs stem name) had the
      actual bug.

      Verified end-to-end on `sample5.mp3`: `storage/intermediate/sample5/`,
      `storage/midi/sample5/`, and `storage/musicxml/stems/sample5/` all created
      correctly with all 6 stems' files nested inside; combined MSCZ still opens
      cleanly. Cleaned up the stale flat files left over from prior runs (before this
      fix) that were silently overwriting each other across samples.

      **Drum MIDI export, added.** User noticed `storage/midi/<sample>/` was missing
      `drums.mid` while every other stem had one. Root cause: `transcription_service.
      run()` gets a MIDI file for free from Basic Pitch's `predict()` (which returns a
      ready-made MIDI object alongside note events) — `drum_transcription_service.
      run()` never had an equivalent, since librosa's onset detector has no built-in
      MIDI export. Fixed by adding `_to_midi()` (builds a `pretty_midi.PrettyMIDI`
      from the raw NoteEvents, same pattern as `quantization_service.to_midi()`) and
      writing it to `storage/midi/` alongside the existing notes JSON. Uses
      `pretty_midi.Instrument(program=0, is_drum=True)` — the `is_drum=True` flag
      routes the instrument to General MIDI channel 10 (the standard percussion
      channel), so pitch 36/38/42 actually plays back as kick/snare/hi-hat in any
      MIDI player/DAW instead of sounding like a piano playing those pitches.
      Verified: `drums.mid` now written correctly (confirmed `is_drum=True`, correct
      pitches/timing on read-back), full pipeline re-run end-to-end with no
      regressions, combined MSCZ still opens cleanly.

      **Drum note dropout in MusicXML, fixed — a real quantization bug, not a
      notation bug.** User reported `drums.musicxml` was "not showing most of the
      notes" even though `drums.mid` (added above) sounded fine. Traced directly:
      188 raw onset-detected hits going into `quantization_service.run()`, only 35
      quantized notes coming out (an 81% drop) — the bug was in quantization, not
      `musicxml_service.py`'s rendering. Root cause: `drum_transcription_service.py`
      gave every hit a fixed `DRUM_ONSET_DEFAULT_DURATION_SECONDS = 0.1` regardless
      of tempo. At the sample's ~160 BPM, a 16th note (the quantization grid's
      snapping resolution) is ~0.094s — almost exactly the same as the fixed
      duration, so a hit's onset and its onset+0.1s offset frequently snapped to the
      SAME beat-grid position, and `quantization_service.run()`'s `if offset_beat <=
      onset_beat: continue` guard (there to drop genuinely-collapsed notes) silently
      dropped it. Confirmed directly: 156 of 188 real onsets (83%) collapsed to
      zero duration after snapping.

      Fixed by scaling each hit's duration to the gap until the NEXT onset instead
      of a fixed value (`_hit_duration()` in drum_transcription_service.py) —
      `DRUM_ONSET_DURATION_FRACTION_OF_GAP` (0.8) of that gap, clamped to
      [`DRUM_ONSET_MIN_DURATION_SECONDS`, `DRUM_ONSET_MAX_DURATION_SECONDS`] = [0.15,
      0.3]s. This scales with actual note density (short between fast hi-hat hits,
      longer between sparse kicks) — long enough to reliably survive snapping at any
      reasonable tempo, short enough not to visually overlap the next hit. The last
      onset in a stem (no "next onset" to measure against) falls back to the gap
      until the clip's end. Verified: quantized drum notes went from 35 to 151 (out
      of 188 raw onsets, 80% survival vs. 19% before) on the same real stem; combined
      MusicXML's drums part now shows 140 unpitched notes (vs. a much sparser count
      before); full pipeline re-run end-to-end, all 6 parts still matching measure
      count, MSCZ verified to open cleanly.

      **Drums playing back as piano in MuseScore, fixed.** User opened the combined
      MSCZ and heard piano-sounding playback on the drum staff, even though notation
      looked correct (percussion clef, unpitched noteheads) and the standalone
      `drums.mid` (fixed earlier) sounded right. Root cause: `_build_percussion_part()`
      never assigned an `Instrument` to the part at all — with no MIDI channel/program
      info in the MusicXML, MuseScore falls back to a default piano sound for
      playback, even though the notation itself renders correctly as percussion.
      This is a separate code path from `drums.mid` (`drum_transcription_service.py`'s
      `_to_midi()`, which does set `is_drum=True` on its `pretty_midi.Instrument`) —
      fixing MIDI export didn't touch MusicXML generation at all.

      Fixed by adding `part.append(instrument.UnpitchedPercussion())` in
      `_build_percussion_part()`, right after creating the `Part`. Confirmed this
      writes `<midi-channel>10</midi-channel>` into the MusicXML's `<score-part>`
      (General MIDI's standard percussion channel — same underlying concept as
      `is_drum=True` in the pretty_midi fix, just the MusicXML equivalent), which is
      what actually tells MuseScore to play the part back as drums instead of piano.
      Verified: real drums stem's MusicXML now includes the midi-channel-10 block,
      full pipeline re-run end-to-end with the combined score's drums part correctly
      channel-assigned, MSCZ still opens/converts cleanly.

      **Follow-up, tried then reverted per user instruction: playback through
      General MIDI channel 10 sounds like "Percussion" (a single generic
      instrument), not a real drum kit** — user reported the hi-hat's staff
      position "sounds like a weird drum," not a hi-hat. Root cause: a single
      shared `instrument.UnpitchedPercussion()` for the whole part has
      `percMapPitch = None`, and music21's MusicXML writer only emits a
      `<midi-unpitched>` element (the thing that tells a GM percussion channel
      WHICH drum sound a note maps to) when `percMapPitch is not None` — with it
      unset, every note falls back to one single default sound regardless of staff
      position.

      First attempt: give each note its OWN `Instrument` (`BassDrum`/`SnareDrum`/
      `HiHatCymbal`, each with the correct `percMapPitch` built in), inserted into
      the stream right before that note. This did make `<midi-unpitched>` appear
      correctly per voice — but user asked to revert it, wanting one single drum-kit
      part with notes routed to the correct drum instrument WITHIN that one part,
      not effectively-separate per-note instrument objects. Reverted to the single
      shared `instrument.UnpitchedPercussion()` for the whole part.

      **Real root cause, found by the user directly, not by `percMapPitch` at
      all: NOTEHEAD SHAPE.** User edited a hi-hat note by hand in MuseScore,
      changed its notehead from the default round shape to an "x", and the correct
      hi-hat sound played immediately — no other change. This means MuseScore picks
      a playback sound for a note on a shared percussion channel/instrument based on
      notehead shape at that staff position, not `percMapPitch` (which the reverted
      per-note-Instrument attempt above was chasing down the wrong path). Standard
      drum notation already uses this convention: round noteheads for
      kick/snare/toms, "x" noteheads for hi-hat/cymbals — `_build_percussion_part()`
      just wasn't setting it (every voice defaulted to `note.Unpitched`'s standard
      "normal" round notehead).

      Fixed by adding a notehead shape to `DRUM_STAFF_POSITIONS` (now
      `pitch -> (staff_position, notehead, display_name)`) — `"normal"` for
      kick/snare, `"x"` for hi-hat — and setting `element.notehead = notehead` on
      each `Unpitched` note in `_build_percussion_part()`. Confirmed music21's
      `note.notehead` attribute writes a real `<notehead>x</notehead>` MusicXML
      element correctly (checked in isolation first). Verified end-to-end: real
      drums stem's MusicXML now has 37 hi-hat notes correctly marked
      `<notehead parentheses="no">x</notehead>`; full pipeline re-run on
      `sample5.mp3`, combined score shows 40 correctly-marked hi-hat notes, MSCZ
      verified to open/convert cleanly. Single shared `instrument.UnpitchedPercussion()`
      kept (per user's revert instruction) — the notehead fix is independent of
      and doesn't need the per-note-Instrument approach at all.

- [x] **Vocals: dedicated single treble-clef staff + harmonic-duplicate removal —
      done.** User reported "the vocal stem is not being turned into midi or note
      events correctly" and asked to confirm whether vocals used a single treble
      staff. Confirmed directly from the code they did NOT: `"vocal_melody"` had
      no dedicated branch in `musicxml_service.build_score()`, so it fell through
      to the piano grand-staff `else` branch — split across treble/bass "hands" by
      pitch register via `_assign_staff_per_note()` (built for simultaneous piano
      chords, not a single melodic line), with real melody notes at risk of being
      misrouted mid-phrase or dropped by `_drop_octave_overflow()`.

      Fixed in two parts:
      1. Added a dedicated `"vocal_melody"` branch in `build_score()` — single
         treble-clef staff, `instrument.Vocalist()`, same as the existing guitar/
         bass single-staff branches (no more grand-staff split for vocals).
      2. Investigated the actual audio→MIDI/note-event conversion and found a
         real Basic Pitch data-quality problem: on real vocal audio, Basic Pitch
         (a polyphonic model, no assumption a stem is monophonic) sometimes
         detects a strong harmonic/overtone of the real sung note as if it were
         its own simultaneous note. Confirmed directly: one segment had notes at
         MIDI 59/71/95 all overlapping in time — exactly 0/1/3 octaves apart
         (frequency ratios 1x/2x/8x), physically impossible for one voice to sing
         at once. Checked across the whole stem: 64% of all time-overlapping note
         pairs were octave-related — too systematic to be coincidental melodic
         overlap, not a one-off glitch.

      Fixed with `transcription_service._remove_harmonic_duplicates()`, gated to
      `stem_label == "vocal_melody"` only (`MONOPHONIC_STEM_LABELS`) — chord-
      capable stems (piano/guitar/bass) must NOT run this, since real simultaneous
      different-octave notes are normal, correct output for them (an actual
      chord), not a bug. Keeps the LOWEST pitch in each group of time-overlapping,
      octave-related notes — acoustically correct (harmonics are always above the
      fundamental, never below), and empirically right more often than a
      confidence-based rule too (12 of 16 real overlapping pairs also had the
      lower pitch as the higher-confidence one, but confidence isn't what the
      rule keys on). Also rebuilds the stem's MIDI file from the cleaned note
      events (new `transcription_service._to_midi()`) instead of writing Basic
      Pitch's own `midi_data` object directly — that object doesn't reflect the
      cleanup, so using it as-is would have silently kept the harmonic duplicates
      in the MIDI while the JSON/notation were already fixed, an inconsistency
      that would have been confusing to debug later.

      Verified: real vocals stem went from 103 raw notes (many with impossible
      octave-stacked overlaps) to 89 cleaned notes with zero remaining
      octave-overlap pairs; rebuilt MIDI file has the same 89 notes; full pipeline
      re-run end-to-end on `sample5.mp3`, combined score's vocals part confirmed
      single-staff (no more `<staves>2</staves>`), all 6 parts still matching
      measure count, MSCZ verified to open/convert cleanly. Non-vocal stems
      (piano/guitar/bass/other) confirmed unaffected — same code path as before.

- [x] **Guitar sometimes rendered as a two-staff piano grand staff instead of
      single-staff guitar — fixed.** User checked `sample6.mp3`'s output and
      found `guitar.musicxml` on two staves. Root cause: `classify_stem()`'s
      re-check of Demucs's `guitar.wav` predicted `piano_accompaniment` (the
      audio sounded more piano-like to the rule-based classifier), and
      `run_pipeline.py` was using that PREDICTED label as the stem's final
      `stem_label` — which also drives `musicxml_service.py`'s staff-layout
      choice (single-staff guitar vs. two-staff piano grand staff), not just
      the displayed instrument name. So a guitar.wav re-classified as
      piano-sounding rendered as an actual piano grand staff.

      Fixed by no longer acting on the classifier's relabel for `stem_label` at
      all — `run_pipeline.py`'s `run_pipeline()` now always keeps
      `stem_label = expected_label` (the label matching which Demucs stem the
      audio actually came from: `guitar_accompaniment` for `guitar.wav`,
      `piano_accompaniment` for `piano.wav`), and only PRINTS the classifier's
      disagreement as a log line — it no longer changes what gets stored or how
      the stem gets notated. Rationale: which Demucs stem produced this audio is
      a more reliable signal for staff LAYOUT than a rule-based heuristic whose
      thresholds were validated on synthetic test signals, not real audio (see
      `classification_service.py`'s own docstring caveat).

      Verified on `sample6.mp3` (same file, same real classifier disagreement on
      both guitar.wav and piano.wav this run): `guitar.musicxml` now has no
      `<staves>2</staves>` (single-staff, confirmed), `piano.musicxml` still
      correctly has it (real piano stem, unaffected); full pipeline re-run
      end-to-end, all 6 parts still matching measure count, MSCZ verified to
      open/convert cleanly.

- [x] **Tempo reconciliation could force a stem onto a WRONG reference tempo,
      making its notation claim to finish playing 33-54% early — fixed with a
      duration sanity check.** User noticed most parts' tempos looked doubled on
      `sample6.mp3` and asked whether tempo octave ambiguity and "parts played at
      double speed" were separate issues. They were right to push back — I'd
      initially conflated them. Investigated properly: `quantization_service.
      run()`'s beat grid is built ENTIRELY from real detected beat positions in
      that stem's own audio (`_beat_grid()`/`_time_to_beat()`) — `tempo_bpm` only
      controls the printed label, in the normal case (2+ real beats detected).
      So forcing a stem onto the reference tempo doesn't distort its notated
      RHYTHM... except when the reference tempo itself came from a doubled/halved
      beat-tracker detection, which genuinely means the reference's OWN beat grid
      packs twice (or half) as many real beats into the same real time as a
      correctly-detected stem. Forcing that mismatched tempo NUMBER onto a
      DIFFERENT stem's correctly-spaced beat grid produces an internally
      inconsistent result.

      User's proposed fix: compare the sheet music's calculated playback duration
      (at its printed tempo) against the real audio length — if they don't match,
      something is wrong. Implemented exactly this as `_passes_duration_check()`
      in `quantization_service.py`: computes `last_note.offset_beat * 60 /
      tempo_bpm` (the notation's implied total playback time) and compares it to
      the real audio's actual duration (`_audio_duration_seconds()`, via
      `soundfile.info()` — cheap, header-only read). `DURATION_RATIO_TOLERANCE`
      (±15%) gates whether a forced-reference re-quantization is accepted.
      Confirmed on real `sample6.mp3` data: forcing 4 stems (drums, vocals,
      guitar, piano) onto the reference tempo dropped their notated-duration-vs-
      real-audio ratio to 0.46-0.67 — i.e. the notation would claim to finish
      33-54% early despite being the same real audio. `reconcile_tempo()` now
      computes the candidate re-quantization FIRST, checks its duration ratio,
      and only keeps it if the ratio is sane — otherwise falls back to the
      stem's own (better) tempo, logged distinctly ("reference REJECTED... keeping
      X's own tempo instead").

      One stem (`other`) failed the duration check on BOTH its own tempo AND the
      reference in earlier testing — a separate, deeper problem (that stem's own
      beat detection is itself unreliable, likely sparse/noisy separated content),
      not something tempo reconciliation can fix by choosing between two
      candidates. Not addressed in this pass; flagged here for later.

      Verified end-to-end on `sample6.mp3`: all 4 previously-wrongly-forced stems
      now keep their own musically-consistent tempo (74/91/99/74 BPM, matching
      their own beat detection) instead of being forced to a mismatched 148;
      combined score's 6 parts still all match at 30 measures despite the now
      much wider tempo spread (confirms `build_score()`'s measure-padding logic,
      which already worked in real seconds not raw beat counts, handles this
      correctly); MSCZ verified to open/convert cleanly.

- [x] **Step 8 — FastAPI routes, done.** Async job/polling model (decided
      explicitly, not a blocking request): the full pipeline takes several
      minutes per file, and a multi-minute blocking HTTP request risks proxy/
      browser timeouts and gives the frontend no way to show real progress.

      New pieces:
      - `app/services/pipeline_service.py` — the actual pipeline logic, moved
        out of `scripts/run_pipeline.py` (now a thin CLI wrapper calling
        `pipeline_service.run_full_pipeline()`) so both the CLI and the API call
        the same code, not two copies. Takes an optional `on_stage(stage,
        message)` callback for progress reporting instead of only printing.
      - `app/schemas/job.py` — `JobStatus` (pending/processing/done/failed),
        `JobStage` (uploaded/separating/transcribing/quantizing/
        reconciling_tempo/rendering_musicxml/exporting), `Job`, `JobResult`,
        `StemResult`.
      - `app/services/job_service.py` — file-backed job store, one JSON file per
        job at `storage/jobs/<job_id>.json`. Chosen over a database since
        `app/models/`'s purpose (DB models vs. ML model cache) was never decided
        and this project doesn't otherwise need real DB infrastructure; survives
        process restarts unlike a pure in-memory dict. Not safe against truly
        concurrent writers to the same job (read-modify-write race) — fine for a
        single-worker dev server, would need a real lock or a database
        otherwise.
      - `app/api/upload.py` — `POST /upload`: validates extension (mp3/wav/flac/
        m4a), saves the file under `storage/uploads/<job_id>.<ext>` (named after
        the job ID, not the original filename, so same-named uploads never
        collide), creates the job, schedules `pipeline_service.run_full_pipeline()`
        via FastAPI's `BackgroundTasks`, returns immediately with the job.
      - `app/api/transcribe.py` — `GET /status/{job_id}` (poll current stage),
        `GET /result/{job_id}` (404 unknown job, 422 if the job failed — with the
        captured error, 409 if not done yet, else the `JobResult`).
      - `app/api/export.py` — `GET /export/{job_id}/{format}` file download,
        `format` = `musicxml` | `mscz` | `stem-musicxml` (needs `?stem=<name>`
        for the per-stem case). PDF/PNG/SVG isn't wired up since
        `export_service.py` only has `to_mscz()` (still Q3, unstarted).
      - `app/main.py` — mounts all three routers, wide-open CORS for local
        frontend dev (tighten before any real deployment), `/health`.

      Scope decision: built the WHOLE API surface (including what would have
      been Teammate A's `upload.py`/`stems.py` in the original ownership split),
      not just the owned transcription/export routes, per explicit direction —
      rather than leaving `main.py` wiring for a joint session as `CLAUDE.md`'s
      build order originally planned. A separate `app/api/stems.py` router
      wasn't written since the pipeline already does separation internally as
      part of `POST /upload`'s background job — there was no remaining
      standalone "give me just the stems" use case to expose.

      Real bug found via actual API testing (not caught by the many direct
      `pipeline_service`/`scripts/run_pipeline.py` runs earlier in the project):
      a job failed with `float division by zero` during tempo reconciliation.
      Reproducing the exact same file directly through `pipeline_service.
      run_full_pipeline()` succeeded cleanly — non-reproducible on demand, most
      likely Basic Pitch (TensorFlow inference, no fixed seed) or librosa's beat
      tracker occasionally returning a genuinely degenerate result on a
      borderline signal. Root cause: `quantization_service.detect_tempo()` can
      return `0.0` BPM in this edge case, and `reconcile_tempo()`'s
      `ratio = result.tempo_bpm / reference_tempo_bpm` divides by it
      unconditionally. Fixed with a guard: `reconcile_tempo()` now checks
      `reference_tempo_bpm <= 0` up front and, if so, skips reconciliation
      entirely (every stem keeps its own tempo — the same safe state as if
      reconciliation had never run) instead of crashing the whole job over a
      labeling step.

      Also fixed while debugging that: `_process_job()`'s exception handler was
      only capturing `str(e)` into the job's `error` field — for a bare message
      like `"float division by zero"` there was no way to tell WHERE in the
      pipeline it happened without reproducing the failure separately (which
      cost real time above). Now captures and stores the full
      `traceback.format_exc()`, also printed to the server log immediately
      rather than only surfacing on the next status poll.

      Verified end-to-end via the real running server (not just direct
      `pipeline_service` calls): `POST /upload` on `sample7.mp3` and
      `sample.mp3` both completed successfully after the fixes (job status
      "done", full `JobResult` with all 6 stems); `GET /result` returns the
      correct JSON; all three `GET /export` format variants (`musicxml`,
      `mscz`, `stem-musicxml`) download real files of sensible size; the
      downloaded MSCZ re-opens/converts cleanly in MuseScore (not corrupted in
      transit). Error paths checked directly: unsupported file extension → 400,
      unknown job ID → 404, result/export requested before the job finishes →
      409 with a correctly-formatted stage name (fixed a `str(enum)` formatting
      bug caught during this same testing pass — was printing
      `JobStage.SEPARATING` instead of `separating`).

## Known gotchas

- **Dependencies are heavy and conflict-prone** (torch, demucs, basic-pitch, and TensorFlow if
  using YAMNet). basic-pitch has historically pinned specific TF/coremltools versions — resolve
  this early in step 0, in a virtualenv.
- **[RESOLVED] Installing `demucs` breaks `basic-pitch` unless `setuptools<81` is
  pinned.** demucs pulls in a newer setuptools transitively that no longer bundles
  `pkg_resources` by default; `resampy` (a basic-pitch dependency) still imports
  `pkg_resources` directly and fails hard without it. `requirements.txt` now pins
  `setuptools<81`. Also: call demucs via `[sys.executable, "-m", "demucs", ...]`
  (as `demucs_service.py` does), not a bare `"demucs"` command — the bare form only
  resolves on PATH in an activated venv shell and fails with `FileNotFoundError`
  otherwise (e.g. running scripts via `./venv/Scripts/python.exe` directly).
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
- **[RESOLVED — madmom removed] Real downbeat/time-signature detection was tried via
  madmom, but its install cost (from-source Cython+MSVC build, Visual Studio Build
  Tools, hand-patching 3 Python 3.11/numpy compatibility breaks in the installed
  package — none tracked by requirements.txt) wasn't worth it for one feature.
  Essentia was considered as an alternative and ruled out immediately: no Windows
  wheel, source build fails on Windows in Essentia's own `setup.py`. Time signature
  is now always 4/4 (see the "Real time-signature estimation" entry in the Quality
  backlog above for the full writeup); a picker for the user to override it is
  planned in the frontend (`docs/frontend-plan.md`).
- **Tempo octave ambiguity is a fundamental, unfixable-from-audio-alone MIR limitation
  — not a bug, even though it looks like one.** Evaluated transcription quality against
  a ground-truth original score (`sample2_original.musicxml` vs. our output for
  `sample2.mp3`): `quantization_service`'s `librosa.beat.beat_track()` detected 129.2
  BPM; the original's actual marked tempo is 65 BPM — a ratio of 1.988, i.e. almost
  exactly double. This is the classic beat-tracker octave error (locking onto the
  eighth-note pulse instead of the quarter-note pulse). **There is no way for the app
  to know which reading is "correct" from audio alone** — 65 and 129 BPM are both
  self-consistent periodicities in the same signal; disambiguating requires either the
  score's own tempo marking (not present in audio) or genre/style priors we don't have.
  Decided not to chase an automatic fix (e.g. biasing toward a "typical" 60-140 BPM
  range) — evaluated as not worth the effort relative to Basic Pitch's over-detection
  (see below). Instead, tracked as a frontend correction-interface item: see "Tempo
  picker/override" under item 5 in `docs/frontend-plan.md` — let the user see the
  detected BPM and correct it themselves (e.g. offer the half/double as quick options)
  once the correction UI exists.
- **Basic Pitch over-detects notes relative to ground truth.** Same evaluation as
  above: for the ~20-measure passage `sample2.mp3` actually covers, the original score
  has ~269 note events; raw Basic Pitch output has 428 (~60% overshoot), only partly
  cleaned up by quantization (350, still ~30% over). Confidence of the excess notes is
  spread across the normal range (median 0.57), not clustered low, so a stricter
  confidence-percentile cutoff won't cleanly remove them without also cutting real
  notes. Likely cause: piano sustain-pedal resonance/harmonics being picked up as
  separate note events. `frame_threshold` (governs whether a note is detected as
  sounding at all, frame by frame — distinct from `onset_threshold`, which only
  governs whether a new onset re-triggers mid-sustain) was tried at 0.4/0.5/0.6:
  0.4 cut the excess with minimal verified real-note loss (1 note on one clip, 0 on
  the other), but was reverted after the user found it removed too much real content
  by ear on a full listen — verification against ground-truth counts and time-overlap
  matching didn't fully capture perceived quality loss. **Not currently applied**
  (`frame_threshold` left at Basic Pitch's default 0.3). Revisit with a smaller step
  (e.g. 0.32-0.35) if attempted again, and verify by listening, not just by counting.

## Housekeeping TODO

- `classification_service.py` now exists (Teammate A, `classification-stage` merge) —
  heuristic guitar/piano split on Demucs's `other.wav` stem, not ML-based.
- Decide the purpose of `app/models/` (ML model loaders/cache vs DB models) or remove it.
- Add at least one solo/piano clip **and** one mixed clip to `samples/`.
