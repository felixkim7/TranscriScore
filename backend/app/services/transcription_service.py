import json
from pathlib import Path
from typing import List, Optional

import pretty_midi
from basic_pitch.inference import predict

from app.config.settings import INTERMEDIATE_DIR, MIDI_DIR, stem_output_dir
from app.schemas.transcription import NoteEvent

# Raised from Basic Pitch's default (0.5): at 0.5, real piano sustain is frequently
# split into 2+ back-to-back same-pitch note fragments (the model over-eagerly detects
# a new onset mid-sustain) -- verified up to 44% of raw notes on one real test clip.
# 0.6 was checked against both test clips using generous time-overlap matching (not
# exact-onset matching, which falsely flags timing-shifted notes as "lost"): it cuts
# split-fragment notes substantially with zero verified loss of real, high-confidence
# notes. 0.7 cuts further but wasn't chosen -- smaller deviation from Basic Pitch's own
# tested default while still fixing the fragmentation problem.
ONSET_THRESHOLD = 0.6

# Stem labels treated as monophonic (one real pitch sounding at a time) for
# _remove_harmonic_duplicates() below — currently just the vocal melody. Chord-
# capable stems (piano/guitar/bass) genuinely produce simultaneous different
# pitches as normal, correct output (a real chord), so this cleanup must NOT run
# for them — it would incorrectly strip real chord tones that happen to be an
# octave apart.
MONOPHONIC_STEM_LABELS = {"vocal_melody"}


def run(
    input_path: str,
    stem_label: str = "unknown",
    input_stem: Optional[str] = None,
) -> List[NoteEvent]:
    """Transcribe an audio file into note events using Spotify Basic Pitch.

    Writes the resulting MIDI to storage/midi/ and the note events as JSON to
    storage/intermediate/ (so later stages can be re-run without re-transcribing).

    Args:
        input_path: path to the audio stem to transcribe. Should be the
            LOUDNESS-NORMALIZED path from preprocessing_service.preprocess_stem()
            (its .normalized_audio_path), not the raw separated stem — Basic
            Pitch only accepts a file path and does its own internal loading,
            so normalizing loudness before this call is the one way to actually
            change what audio bytes it transcribes. Still works with a raw
            stem path (e.g. from the CLI script's simpler flow), just without
            that benefit.
        stem_label: role of this stem (e.g. "piano_accompaniment"), typically
            from classification_service.classify_stem() or a trusted Demucs
            label (e.g. "vocals", "drums"). Defaults to "unknown" so existing
            callers that don't pass it keep working. For "vocal_melody"
            specifically, also runs _remove_harmonic_duplicates() (see that
            function's docstring) — Basic Pitch is a polyphonic model and, on a
            monophonic vocal line, sometimes emits a strong harmonic/overtone of
            the real sung note as if it were its own simultaneous note (confirmed
            on real audio: notes at exact octave multiples of each other,
            overlapping in time — physically impossible for a single voice to
            sing three octaves at once).

            NOTE: per-stem-type minimum_frequency/maximum_frequency restriction
            and an onset-cross-check filter (dropping notes with no nearby
            independently-detected onset) were both tried here and REMOVED —
            the onset filter in particular cut 190->109 notes (43%) on a real
            vocals stem (sample7), and on listening it turned out to be
            overfiltering, cutting real content rather than just phantom notes
            (same failure mode as the frame_threshold=0.4 experiment
            elsewhere in this project's history: looked like a clean
            improvement by the numbers, wrong once actually heard). See
            preprocessing_service.py — preprocess_stem() still computes
            onset times/tempo/beats/mel-spectrogram, they're just no longer
            used to filter transcription output.
        input_stem: the ORIGINAL sample's filename stem (e.g. "sample5"), not
            input_path's own stem (e.g. "drums") — when given, nests output
            under storage/midi/<input_stem>/ and storage/intermediate/<input_stem>/
            instead of writing flat, so a multi-stem run (run_pipeline.py) on two
            different samples can't silently overwrite each other's same-named
            stem files (e.g. two different samples both producing "drums.mid").
            Omit for single-file runs where output naming already can't collide.
    """
    audio_path = Path(input_path)

    _, midi_data, raw_note_events = predict(audio_path, onset_threshold=ONSET_THRESHOLD)

    note_events = [
        NoteEvent(
            pitch=pitch,
            onset=start,
            offset=end,
            duration=end - start,
            velocity=round(amplitude * 127),
            confidence=amplitude,
            stem_label=stem_label,
        )
        for start, end, pitch, amplitude, _pitch_bends in raw_note_events
    ]

    if stem_label in MONOPHONIC_STEM_LABELS:
        note_events = _remove_harmonic_duplicates(note_events)
        # Rebuild MIDI from the cleaned note events instead of writing Basic
        # Pitch's own midi_data — that object still has the raw, undeduplicated
        # harmonics baked in, so using it here would silently undo the cleanup
        # for anyone listening to the MIDI instead of reading the JSON/notation.
        midi_to_write = _to_midi(note_events)
    else:
        midi_to_write = midi_data

    midi_dir = stem_output_dir(MIDI_DIR, input_stem)
    midi_dir.mkdir(parents=True, exist_ok=True)
    midi_path = midi_dir / f"{audio_path.stem}.mid"
    midi_to_write.write(str(midi_path))

    intermediate_dir = stem_output_dir(INTERMEDIATE_DIR, input_stem)
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    notes_path = intermediate_dir / f"{audio_path.stem}.notes.json"
    notes_path.write_text(
        json.dumps([note.model_dump() for note in note_events], indent=2)
    )

    return note_events


def _remove_harmonic_duplicates(note_events: List[NoteEvent]) -> List[NoteEvent]:
    """Drop notes that are almost certainly a harmonic/overtone of another note
    sounding at the same time, not a real second simultaneous pitch.

    Basic Pitch is a polyphonic model with no built-in assumption that a stem is
    monophonic. On real vocal audio it sometimes detects a strong overtone of the
    actual sung note as if it were its own note: confirmed directly on a real
    stem — e.g. one segment had notes at MIDI 59, 71, and 95 all overlapping in
    time, which are exactly 0/1/3 octaves apart (frequency ratios 1x/2x/8x). A
    single human voice cannot produce three simultaneous pitches three octaves
    apart; these are the fundamental plus its 2nd and 4th harmonics. Checked
    across a full real vocal stem: 64% of all time-overlapping note pairs were
    related by an exact whole number of octaves — too systematic to be
    coincidental melodic overlap.

    Keeps the LOWEST pitch in each group of time-overlapping, octave-related
    notes and drops the rest. This is the acoustically correct choice (harmonics
    are always above the fundamental, never below it), and was also empirically
    right more often than "keep highest confidence" on real data (in 12 of 16
    real overlapping octave-related pairs, the lower pitch also had the higher
    Basic Pitch confidence score — but confidence alone isn't used as the rule
    here, since acoustic correctness doesn't depend on it).

    Only meant for genuinely monophonic sources (see MONOPHONIC_STEM_LABELS) —
    running this on a chord-capable stem (piano/guitar) would incorrectly delete
    real chord tones that happen to land an octave apart.
    """
    sorted_notes = sorted(note_events, key=lambda n: n.onset)
    dropped = set()

    for i, note in enumerate(sorted_notes):
        if i in dropped:
            continue
        for j in range(i + 1, len(sorted_notes)):
            other = sorted_notes[j]
            if other.onset >= note.offset:
                break
            if j in dropped:
                continue
            if note.pitch == other.pitch:
                continue
            if (other.pitch - note.pitch) % 12 == 0:
                # Harmonic pair — drop whichever is higher (regardless of which
                # loop variable it is; `note` isn't guaranteed to be the lower
                # one once earlier drops have happened).
                if other.pitch > note.pitch:
                    dropped.add(j)
                else:
                    dropped.add(i)
                    break  # `note` itself was dropped; stop comparing it further

    return [n for i, n in enumerate(sorted_notes) if i not in dropped]


def _to_midi(note_events: List[NoteEvent]) -> pretty_midi.PrettyMIDI:
    """Build a PrettyMIDI object directly from NoteEvents.

    Used for stems where the note events get cleaned up AFTER Basic Pitch's own
    predict() call (currently just vocal harmonic-duplicate removal) — Basic
    Pitch's own returned midi_data object doesn't reflect that cleanup, so
    writing it directly would silently keep the removed notes in the MIDI file.
    """
    midi = pretty_midi.PrettyMIDI()
    voice = pretty_midi.Instrument(program=0)  # generic instrument; caller's MIDI is for inspection, not final export

    for n in note_events:
        voice.notes.append(
            pretty_midi.Note(velocity=n.velocity, pitch=n.pitch, start=n.onset, end=n.offset)
        )

    midi.instruments.append(voice)
    return midi


def load_note_events(stem_name: str, input_stem: Optional[str] = None) -> List[NoteEvent]:
    """Load previously transcribed note events from storage/intermediate/.

    input_stem: see run()'s docstring — pass the same value used when this stem
    was transcribed, to find it under the matching per-sample subfolder.
    """
    notes_path = stem_output_dir(INTERMEDIATE_DIR, input_stem) / f"{stem_name}.notes.json"
    if not notes_path.exists():
        raise FileNotFoundError(
            f"No saved note events for '{stem_name}' at {notes_path}. Run transcription first."
        )
    raw = json.loads(notes_path.read_text())
    return [NoteEvent(**item) for item in raw]
