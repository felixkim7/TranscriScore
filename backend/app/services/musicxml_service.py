from pathlib import Path
from typing import List, NamedTuple

from music21 import chord, clef, duration, instrument, key, layout, metadata, meter, note, stream, tempo

from app.config.settings import MUSICXML_DIR
from app.schemas.transcription import QuantizationResult

MAX_DURATION_BEATS = 4.0  # cap a single note/chord at one whole note (4/4 backbone)
MIDDLE_C = 60  # decides which single octave-window is bass vs treble when only one is needed
MAX_CHORD_SPAN = 12  # semitones (one octave); a single hand can't be asked to span more than this


class Segment(NamedTuple):
    start_beat: float
    end_beat: float
    pitches: List[int]  # empty list = rest


def run(result: QuantizationResult, output_name: str) -> Path:
    """Convert a QuantizationResult into a MusicXML score.

    Routing by result.stem_label:
    - "guitar_accompaniment": single treble-clef staff, Guitar instrument.
    - "bass": single bass-clef staff, Electric Bass instrument. (Not
      currently produced by demucs_service.run() — DEMUCS_STEM_NAMES in
      settings.py only returns vocals/drums/guitar/piano — kept here in
      case bass gets added back to the pipeline later.)
    - anything else (piano_accompaniment / unknown_accompaniment / no label
      — this currently includes "vocals" and "drums" too, since neither has
      its own branch yet): two-staff (treble/bass) piano grand staff. Each
      note is assigned to treble or bass exactly once (_assign_staff_per_note),
      based on the notes sounding at its onset, so a single sustained note
      can never flip staves mid-hold; _drop_octave_overflow then guarantees
      neither staff's simultaneous chord width exceeds MAX_CHORD_SPAN.
      Notating a vocal melody or drum hits as a piano grand staff is a known
      simplification, not something fixed in this pass.

    Backbone version: a single sweep-line pass over ALL notes combined produces one
    definitive timeline of which pitches are sounding at every moment. Key signature
    is detected once from all of this stem's notes (_detect_key, music21's built-in
    Krumhansl-Schmuckler-style analysis) and applied to every staff, so treble/bass
    never disagree on key.
    """
    segments = _sweep_line_segments(result.notes)
    detected_key = _detect_key(result.notes)

    score = stream.Score()
    score.metadata = metadata.Metadata(title=output_name)

    if result.stem_label == "guitar_accompaniment":
        part = _build_staff_part(
            segments, result.tempo_bpm, clef.TrebleClef(), detected_key, result.time_signature,
            part_instrument=instrument.Guitar(), as_part_staff=False,
        )
        score.insert(0, part)
    elif result.stem_label == "bass":
        part = _build_staff_part(
            segments, result.tempo_bpm, clef.BassClef(), detected_key, result.time_signature,
            part_instrument=instrument.ElectricBass(), as_part_staff=False,
        )
        score.insert(0, part)
    else:
        treble_notes, bass_notes = _assign_staff_per_note(result.notes)
        treble_notes = _drop_octave_overflow(treble_notes)
        bass_notes = _drop_octave_overflow(bass_notes)
        treble_segments = _sweep_line_segments(treble_notes)
        bass_segments = _sweep_line_segments(bass_notes)
        treble = _build_staff_part(
            treble_segments, result.tempo_bpm, clef.TrebleClef(), detected_key,
            result.time_signature, as_part_staff=True,
        )
        bass = _build_staff_part(
            bass_segments, result.tempo_bpm, clef.BassClef(), detected_key,
            result.time_signature, as_part_staff=True,
        )
        score.insert(0, treble)
        score.insert(0, bass)
        score.insert(0, layout.StaffGroup(
            [treble, bass], name="Piano", abbreviation="Pno.", symbol="brace"
        ))

    MUSICXML_DIR.mkdir(parents=True, exist_ok=True)
    output_path = MUSICXML_DIR / f"{output_name}.musicxml"
    score.write("musicxml", fp=str(output_path))

    return output_path


def _detect_key(notes) -> key.Key:
    """Detect the key signature from a stem's note events.

    Uses music21's built-in key-finding (Krumhansl-Schmuckler-style pitch-class
    profile matching) over a flat Stream of the stem's notes, weighted by duration.
    Verified on both real test clips with strong confidence (correlation coefficient
    ~0.83-0.85); relative major/minor ambiguity is an inherent limitation of
    pitch-class-only key detection (e.g. C major vs. A minor share the same notes),
    not something fixable without deeper harmonic analysis.
    """
    s = stream.Stream()
    for n in notes:
        s.append(note.Note(n.pitch, quarterLength=max(0.1, n.duration_beats)))
    return s.analyze("key")


def _sweep_line_segments(notes) -> List[Segment]:
    """Collapse overlapping notes into a single timeline of non-overlapping chords.

    Every onset/offset becomes a boundary point; between consecutive boundaries the
    set of sounding pitches is constant. Adjacent boundaries with an identical pitch
    set are merged so a single sustained note/chord isn't split into many tied pieces.
    """
    if not notes:
        return []

    boundaries = sorted({n.onset_beat for n in notes} | {n.offset_beat for n in notes})

    raw_segments: List[Segment] = []
    for start, end in zip(boundaries, boundaries[1:]):
        sounding = sorted({n.pitch for n in notes if n.onset_beat <= start and n.offset_beat >= end})
        raw_segments.append(Segment(start, end, sounding))

    merged: List[Segment] = []
    for seg in raw_segments:
        if merged and merged[-1].pitches == seg.pitches:
            prev = merged.pop()
            merged.append(Segment(prev.start_beat, seg.end_beat, seg.pitches))
        else:
            merged.append(seg)

    return merged


def _assign_staff_per_note(notes):
    """Assign each note to treble or bass exactly once, in a single deterministic pass.

    Builds one combined sweep-line timeline across ALL notes (both hands at once), then
    splits each segment's pitches into treble/bass via _split_two_hands (a direct
    two-octave-window partition — provably respects the cap by construction, no
    iteration). A note is assigned to whichever staff its pitch falls in during the
    segment it starts in, and keeps that staff for its full duration — deciding
    per-segment instead let a single held note flip staves mid-sustain whenever a
    different note started/stopped nearby and shifted the split.
    """
    combined_segments = _sweep_line_segments(notes)

    treble_notes, bass_notes = [], []
    for n in notes:
        onset_segment = next(
            seg for seg in combined_segments if seg.start_beat <= n.onset_beat < seg.end_beat
        )
        treble_pitches, bass_pitches, _dropped = _split_two_hands(onset_segment.pitches)
        if n.pitch in treble_pitches:
            treble_notes.append(n)
        elif n.pitch in bass_pitches:
            bass_notes.append(n)
        # else: this pitch was dropped for this segment — more than two octave-wide
        # hands' worth of pitches were sounding at once, which two staves genuinely
        # can't represent without breaking the octave cap somewhere. Drop the note
        # rather than force it into a staff and silently blow the cap back open.

    return treble_notes, bass_notes


def _drop_octave_overflow(staff_notes):
    """Guarantee MAX_CHORD_SPAN on one staff by dropping (not reassigning) overflow.

    _assign_staff_per_note decides a note's staff once, based on what's sounding at
    its OWN onset — locally correct, but a later, unrelated note (different onset) can
    still start overlapping and push the combined chord (after this staff's own
    sweep-line) over MAX_CHORD_SPAN, even though neither note's individual assignment
    was wrong. Moving such notes to the other staff was tried and hit a stable
    oscillation (fixing one staff's overflow recreates it on the other, indefinitely),
    so this drops whichever pitches fall outside the segment's densest octave window
    instead — guaranteed to terminate in one pass, and only affects the rare segments
    where cross-onset overlap creates a genuine conflict (~3% of segments observed on
    real piano audio).
    """
    segments = _sweep_line_segments(staff_notes)
    violating = [
        s for s in segments if len(s.pitches) >= 2 and max(s.pitches) - min(s.pitches) > MAX_CHORD_SPAN
    ]
    if not violating:
        return staff_notes

    keep_pitches_by_window = {
        (s.start_beat, s.end_beat): set(max(_split_two_hands(s.pitches)[:2], key=len))
        for s in violating
    }

    kept = []
    for n in staff_notes:
        overflow = any(
            n.onset_beat < end and n.offset_beat > start and n.pitch not in keep_pitches
            for (start, end), keep_pitches in keep_pitches_by_window.items()
        )
        if not overflow:
            kept.append(n)

    return kept


def _split_two_hands(pitches: List[int]):
    """Partition a chord's pitches into (treble_pitches, bass_pitches, dropped_pitches).

    Directly searches every pair of MAX_CHORD_SPAN-wide (one octave) windows and picks
    whichever pair covers the most pitches between them — the lower window is bass,
    the higher is treble. This is correct by construction: neither side can ever exceed
    an octave, since both are built as octave-wide windows from the start (no iterative
    patch-up needed). Any pitch covered by neither chosen window is dropped — this only
    happens when more than two hands' worth of pitches sound in registers too far apart
    to fit two octave windows over them, which real two-handed piano playing shouldn't
    produce; tracked so callers can report it rather than have it fail silently.
    """
    ordered = sorted(set(pitches))
    if not ordered:
        return [], [], []
    if ordered[-1] - ordered[0] <= MAX_CHORD_SPAN:
        return ([], ordered, []) if ordered[0] < MIDDLE_C else (ordered, [], [])

    best = ([], [], ordered)  # (low_window, high_window, dropped) — start "all dropped"
    for low_start in ordered:
        low_window = [p for p in ordered if low_start <= p <= low_start + MAX_CHORD_SPAN]
        remaining = [p for p in ordered if p not in low_window]
        if not remaining:
            candidate = (low_window, [], [])
        else:
            for high_start in remaining:
                high_window = [p for p in remaining if high_start <= p <= high_start + MAX_CHORD_SPAN]
                dropped = [p for p in remaining if p not in high_window]
                candidate = (low_window, high_window, dropped)
                if len(candidate[2]) < len(best[2]):
                    best = candidate
            continue
        if len(candidate[2]) < len(best[2]):
            best = candidate

    bass_pitches, treble_pitches, dropped = best
    return treble_pitches, bass_pitches, dropped


def _build_staff_part(
    segments: List[Segment],
    tempo_bpm: float,
    staff_clef,
    staff_key: key.Key,
    time_signature: str = "4/4",
    part_instrument=None,
    as_part_staff: bool = True,
) -> stream.Part:
    part = stream.PartStaff() if as_part_staff else stream.Part()
    if part_instrument is not None:
        part.append(part_instrument)
    part.append(staff_clef)
    # Build a fresh Key instance per part rather than inserting the same object into
    # multiple streams (music21 elements are generally not meant to be shared).
    part.append(key.Key(staff_key.tonic.name, staff_key.mode))
    part.append(meter.TimeSignature(time_signature))
    part.append(tempo.MetronomeMark(number=round(tempo_bpm)))

    cursor = 0.0
    for seg in segments:
        if seg.start_beat > cursor:
            part.append(note.Rest(duration=duration.Duration(quarterLength=seg.start_beat - cursor)))

        span = min(seg.end_beat - seg.start_beat, MAX_DURATION_BEATS)
        note_duration = duration.Duration(quarterLength=span)

        if not seg.pitches:
            element = note.Rest(duration=note_duration)
        elif len(seg.pitches) == 1:
            element = note.Note(seg.pitches[0], duration=note_duration)
        else:
            element = chord.Chord(seg.pitches, duration=note_duration)
        part.append(element)

        cursor = seg.end_beat

    part = part.makeMeasures()
    # A note/chord's cumulative beat position can land anywhere relative to measure
    # boundaries (nothing about segment construction above snaps to them), so
    # makeMeasures() alone can leave an element straddling a barline — printed
    # overflowing the measure rather than split into tied fragments across it. That's
    # what was producing measures with more/fewer beats than the time signature allows
    # and the resulting visual mess (notes crossing barlines, odd beam groupings).
    # makeTies() finds those cases and splits them into proper tied notes per measure.
    part.makeTies(inPlace=True)
    _suppress_redundant_accidentals(part, staff_key)

    return part


def _suppress_redundant_accidentals(part: stream.Part, staff_key: key.Key) -> None:
    """Hide accidental display on every pitch that already matches the key signature.

    Notes/chords are built from bare MIDI pitch numbers, which music21 always gives
    an explicit "natural" Accidental object (not None) since it has no spelling
    context at note-creation time. Left as-is, every diatonic note (e.g. A and B in
    A major) prints a redundant natural sign.

    music21's own `Part.makeAccidentals()` (Krumhansl-style cautionary-accidental
    logic) was tried first but has a real bug for our case: when a later measure has
    no explicit Key element (normal — music21 only puts the Key in the measure where
    it's set, not every measure), `makeAccidentalsInMeasureStream` builds
    `pitchPastMeasure` from ALL of the previous measure's pitches instead of only
    the ones foreign to the key (the filtering it does apply in the sibling
    "elif ksLast" branch) — so it treats the first note of every later measure as a
    cautionary case needing re-display, regardless of whether the key signature
    already covers it. Confirmed on a minimal repro (20x B4 across 5 measures in A
    major): first-of-measure kept showing True/needs-display in every measure after
    the first, even though B is fully diatonic and never altered anywhere.

    Simpler and correct: compare each pitch directly against Key.alteredPitches
    (the letter names the key signature actually sharpens/flattens). If they match,
    hide the accidental; only a genuine deviation from the key gets to display.
    """
    sharp_letters = {p.name[0] for p in staff_key.alteredPitches if p.name.endswith("#")}
    flat_letters = {p.name[0] for p in staff_key.alteredPitches if p.name.endswith("-")}

    for n in part.recurse().notes:
        pitches = n.pitches if n.isChord else [n.pitch]
        for p in pitches:
            if p.accidental is None:
                continue
            implied_alter = 1 if p.step in sharp_letters else (-1 if p.step in flat_letters else 0)
            p.accidental.displayStatus = p.alter != implied_alter
