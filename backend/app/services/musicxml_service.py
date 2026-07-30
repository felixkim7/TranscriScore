import math
from pathlib import Path
from typing import List, NamedTuple, Optional

from music21 import chord, clef, duration, instrument, key, layout, metadata, meter, note, percussion, stream, tempo

from app.config.settings import MUSICXML_DIR, MUSICXML_STEMS_DIR, stem_output_dir
from app.schemas.transcription import QuantizationResult

MAX_DURATION_BEATS = 4.0  # cap a single note/chord at one whole note (4/4 backbone)
MIDDLE_C = 60  # decides which single octave-window is bass vs treble when only one is needed
MAX_CHORD_SPAN = 12  # semitones (one octave); a single hand can't be asked to span more than this

# General MIDI percussion pitch -> (percussion-clef staff line position, notehead
# shape, display name), used to notate drum_transcription_service.py's kick/snare/
# hihat hits on a standard 5-line percussion staff, matching common drum-notation
# convention (kick below the staff, snare in the middle space, hi-hat above the
# staff with an "x" notehead).
#
# The notehead shape isn't just cosmetic — it's what MuseScore actually uses to
# pick a playback SOUND for a note on a shared percussion instrument/channel, not
# percMapPitch (confirmed by the user directly: editing a hi-hat note in MuseScore
# to use an "x" notehead fixed its sound immediately, with no other change).
# Previously every voice used the default "normal" (round) notehead, so hi-hat
# notes played back as whatever round-notehead sound MuseScore maps at that staff
# position on the shared instrument.UnpitchedPercussion() channel — not a hi-hat.
DRUM_STAFF_POSITIONS = {
    36: ("F4", "normal", "Kick"),
    38: ("C5", "normal", "Snare"),
    42: ("G5", "x", "Hi-Hat"),
}
# Simultaneous drum hits (e.g. kick+hihat on a real backbeat) are notated as a
# single music21.percussion.PercussionChord — multiple Unpitched noteheads
# sharing ONE stem/note-position, each keeping its own staff position and
# notehead shape (round for kick/snare, "x" for hi-hat). See
# _build_percussion_part()'s docstring for why this replaced two earlier
# attempts (drop-to-one-winner, then two independent music21 Voices).
#
# TRIED two-voice notation first (kick+snare in one Voice, hi-hat in a second,
# sharing one staff) and REVERTED — technically correct MusicXML, but each
# voice is an independent rest-filled stream, so every segment where only ONE
# voice has real content still emits an explicit rest in the OTHER voice.
# At real note density this produced constant small interleaved rests
# cluttering both voices, confirmed unreadable from an actual rendered page.
# PercussionChord has no such problem: it's still ONE linear stream (like the
# original single-winner version), just with more than one Unpitched note at
# a shared position when a segment genuinely has simultaneous hits — no second
# voice, no rest-filling, no interleaving.
DRUM_VOICE_PRIORITY = [36, 38, 42]  # kick, snare, hihat — stacking/display order

# Stem label -> display name used for each stem's group in a combined multi-stem
# score (StaffGroup name/abbreviation, or the single Part's instrument name for
# single-staff stems). Falls back to the raw stem_label (title-cased) if not listed.
STEM_DISPLAY_NAMES = {
    "guitar_accompaniment": "Guitar",
    "bass": "Bass",
    "vocal_melody": "Vocals",
    "drums": "Drums",
    "piano_accompaniment": "Piano",
    "unknown_accompaniment": "Piano",
    "other_accompaniment": "Other",
}


class Segment(NamedTuple):
    start_beat: float
    end_beat: float
    pitches: List[int]  # empty list = rest


def run(result: QuantizationResult, output_name: str, title: Optional[str] = None) -> Path:
    """Convert a single QuantizationResult into its own MusicXML score/file.

    This is the single-stem entry point (used by test_musicxml.py/test_export.py and
    anywhere else only one stem's notation is needed). For combining multiple stems'
    transcriptions into one multi-part score, see run_combined() below.

    output_name is the on-disk filename stem only. title is what's shown as the
    score's visible title (defaults to output_name) — callers with a filename that
    isn't human-readable (e.g. readable_output_name()'s job-id-suffixed form) should
    pass the clean track name separately here so the job id never ends up rendered
    on the sheet music itself. See run_combined()'s docstring for the full reasoning.
    """
    score = build_score([result], title=title if title is not None else output_name)

    MUSICXML_DIR.mkdir(parents=True, exist_ok=True)
    output_path = MUSICXML_DIR / f"{output_name}.musicxml"
    score.write("musicxml", fp=str(output_path))

    return output_path


def run_combined(results: List[QuantizationResult], output_name: str, title: Optional[str] = None) -> Path:
    """Combine multiple stems' QuantizationResults into one multi-part MusicXML score.

    Each stem becomes its own part (or treble/bass PartStaff pair, for stems that get
    the piano grand-staff treatment) within a single Score, so the whole multi-
    instrument transcription opens as one file — the user can mute/hide/extract
    individual parts later in MuseScore or any other notation program, rather than
    juggling one file per stem.

    output_name is the on-disk filename stem only, not what gets displayed. It's
    allowed to carry a collision-proofing suffix (e.g. a job-id fragment, see
    pipeline_service.readable_output_name()) that has no place on the actual sheet
    music. title is the human-readable name actually drawn on the score (and, since
    export_service.to_mscz() converts from this file, on the MSCZ too) — defaults to
    output_name for callers (tests, the CLI script) that pass an already-clean name.
    """
    score = build_score(results, title=title if title is not None else output_name)

    MUSICXML_DIR.mkdir(parents=True, exist_ok=True)
    output_path = MUSICXML_DIR / f"{output_name}.musicxml"
    score.write("musicxml", fp=str(output_path))

    return output_path


def build_score(results: List[QuantizationResult], title: str) -> stream.Score:
    """Build a music21 Score containing one part (or part-group) per stem.

    Routing by each result's stem_label:
    - "guitar_accompaniment": single treble-clef staff, Guitar instrument.
    - "bass": single bass-clef staff, Electric Bass instrument.
    - "vocal_melody": single treble-clef staff, Vocalist instrument — NOT the
      piano grand-staff split (a vocal melody is monophonic; splitting it across
      treble/bass "hands" by pitch register doesn't make sense for a single line
      and can drop/misroute notes — see the branch's own comment for detail).
    - "drums": single percussion-clef staff of Unpitched notes (kick/snare/
      hi-hat), NOT the pitched grand-staff path — drum_transcription_service.py
      emits GM percussion pitch numbers as a stand-in "pitch" so drum hits can
      flow through the same NoteEvent/quantization pipeline as every other
      stem; _build_percussion_part() is what actually interprets those numbers
      as staff positions instead of real melodic pitches (see
      DRUM_STAFF_POSITIONS above).
    - anything else (piano_accompaniment / unknown_accompaniment / no label):
      two-staff (treble/bass) piano grand staff. Each note is assigned to
      treble or bass exactly once (_assign_staff_per_note), based on the notes
      sounding at its onset, so a single sustained note can never flip staves
      mid-hold; _drop_octave_overflow then guarantees neither staff's
      simultaneous chord width exceeds MAX_CHORD_SPAN.

    Each stem's key signature is detected independently from its own notes
    (_detect_key) — stems in a mixed-instrument piece are not assumed to share a key,
    though in practice most will agree since they're all transcribed from the same
    underlying song.

    A single result produces a one-stem score (this is what run() calls); multiple
    results produce a combined multi-part score, one part-group per stem, in the
    order given (this is what run_combined() calls).
    """
    score = stream.Score()
    score.metadata = metadata.Metadata(title=title)

    multi_stem = len(results) > 1
    # Each stem is transcribed/quantized independently and can end at a different
    # real duration (different tempo, different audio length after separation). A
    # multi-part MusicXML score requires every part to have the SAME number of
    # measures — MuseScore hard-rejects files where one part's measures run out
    # before another's ("Incomplete measure ... Found: 0/1. Expected: 4/4.",
    # confirmed via storage/musicxml debugging: two independently-valid single-stem
    # files each converted fine alone, but failed combined once one part had fewer
    # measures than another).
    #
    # Padding target must be based on real time (seconds), not raw beat/measure
    # counts — a stem's beat count alone says nothing about how long it actually
    # lasts once its own tempo is applied. But converting a shared seconds value
    # into each stem's own beats and rounding independently can still land two
    # stems on different measure counts (observed: a ~0.5s gap between two stems'
    # rounded end times, purely from each stem's own tempo rounding that gap to a
    # different number of measures). So: find the real end time of whichever stem
    # runs longest, convert that same end time into every stem's own measure count
    # (not just the longest one — a shorter-sounding stem's rounding can still push
    # it past the nominal longest stem's own count), and pad every stem to the max
    # of those conversions.
    combined_end_seconds = max(
        (max(n.offset_beat for n in r.notes) * 60.0 / r.tempo_bpm for r in results if r.notes),
        default=0.0,
    )
    combined_measures = max(
        (
            math.ceil(combined_end_seconds * r.tempo_bpm / 60.0 / _beats_per_measure(r.time_signature) - 1e-9)
            for r in results
        ),
        default=0,
    )

    for result in results:
        segments = _sweep_line_segments(result.notes)
        beats_per_measure = _beats_per_measure(result.time_signature)
        stem_end_beat = combined_measures * beats_per_measure
        segments = _pad_to_end_beat(segments, stem_end_beat)
        group_name = STEM_DISPLAY_NAMES.get(result.stem_label, result.stem_label.replace("_", " ").title())

        if result.stem_label == "drums":
            # No _detect_key() here — GM percussion pitch numbers (36/38/42) aren't
            # real melodic pitches, so key analysis on them would be meaningless.
            # Percussion staves conventionally have no key signature at all.
            part = _build_percussion_part(segments, result.tempo_bpm, result.time_signature)
            if multi_stem:
                part.partName = part.partAbbreviation = group_name
            score.insert(0, part)
            continue

        detected_key = _detect_key(result.notes)

        if result.stem_label == "guitar_accompaniment":
            part = _build_staff_part(
                segments, result.tempo_bpm, clef.TrebleClef(), detected_key, result.time_signature,
                part_instrument=instrument.Guitar(), as_part_staff=False,
            )
            if multi_stem:
                part.partName = part.partAbbreviation = group_name
            score.insert(0, part)
        elif result.stem_label == "bass":
            part = _build_staff_part(
                segments, result.tempo_bpm, clef.BassClef(), detected_key, result.time_signature,
                part_instrument=instrument.ElectricBass(), as_part_staff=False,
            )
            if multi_stem:
                part.partName = part.partAbbreviation = group_name
            score.insert(0, part)
        elif result.stem_label == "vocal_melody":
            # Single treble-clef staff, not the piano grand-staff split — a vocal
            # melody is monophonic (one note at a time), so splitting it across
            # treble/bass "hands" by pitch register (_assign_staff_per_note(), built
            # for simultaneous piano chords) doesn't apply: a melodic phrase that
            # dips low would get incorrectly routed to the bass staff mid-phrase,
            # or have notes dropped by _drop_octave_overflow() (built for dense
            # simultaneous chords, not a single line). Previously fell through to
            # the piano-grand-staff else branch below — a known simplification,
            # fixed here.
            part = _build_staff_part(
                segments, result.tempo_bpm, clef.TrebleClef(), detected_key, result.time_signature,
                part_instrument=instrument.Vocalist(), as_part_staff=False,
            )
            if multi_stem:
                part.partName = part.partAbbreviation = group_name
            score.insert(0, part)
        else:
            treble_notes, bass_notes = _assign_staff_per_note(result.notes)
            treble_notes = _drop_octave_overflow(treble_notes)
            bass_notes = _drop_octave_overflow(bass_notes)
            treble_segments = _pad_to_end_beat(_sweep_line_segments(treble_notes), stem_end_beat)
            bass_segments = _pad_to_end_beat(_sweep_line_segments(bass_notes), stem_end_beat)
            # part_instrument is required here (unlike the single-staff branches
            # above, where it's a nice-to-have) — without it, music21 invents its
            # own Instrument with a random id at export time, and OSMD/MuseScore
            # fall back to displaying THAT id (e.g. "Instr. Pe0993900b...") as the
            # part's label whenever partName is unset.
            #
            # The name has to be set on the INSTRUMENT, not just the Part (below) —
            # confirmed by direct repro: when two-PartStaff groups are grouped under
            # a StaffGroup, music21's MusicXML writer merges each pair into one
            # combined <part> at export time, and only the Instrument's partName
            # survives that merge. Part.partName alone left one twin's <score-part>
            # declaration empty (<part-name />), which is what caused OSMD to fall
            # back to the random instrument id — same class of bug as the id
            # fallback above, just surfacing because Part.partName wasn't actually
            # the authoritative source here.
            treble_instrument = instrument.Piano()
            treble_instrument.partName = treble_instrument.partAbbreviation = group_name
            bass_instrument = instrument.Piano()
            bass_instrument.partName = bass_instrument.partAbbreviation = group_name
            treble = _build_staff_part(
                treble_segments, result.tempo_bpm, clef.TrebleClef(), detected_key,
                result.time_signature, part_instrument=treble_instrument, as_part_staff=True,
            )
            bass = _build_staff_part(
                bass_segments, result.tempo_bpm, clef.BassClef(), detected_key,
                result.time_signature, part_instrument=bass_instrument, as_part_staff=True,
            )
            if multi_stem:
                treble.partName = treble.partAbbreviation = group_name
                bass.partName = bass.partAbbreviation = group_name
            score.insert(0, treble)
            score.insert(0, bass)
            score.insert(0, layout.StaffGroup(
                [treble, bass], name=group_name, abbreviation=group_name[:4] + ".", symbol="brace"
            ))

    return score


def write_stem_musicxml(result: QuantizationResult, output_name: str, input_stem: Optional[str] = None) -> Path:
    """Write a single stem's MusicXML to storage/musicxml/stems/ (not storage/musicxml/).

    Intended for inspecting/testing each stem's transcription individually during a
    multi-stem run, before they're combined into one score by run_combined() — kept
    in a separate folder from the single-stem/combined outputs in MUSICXML_DIR so
    it's obvious which files are this intermediate, per-stem form.

    input_stem: the ORIGINAL sample's filename stem (e.g. "sample5"), not
    output_name (the Demucs stem name, e.g. "drums") — when given, nests under
    storage/musicxml/stems/<input_stem>/ instead of writing flat, so a multi-stem
    run on two different samples can't overwrite each other's same-named stem
    files (e.g. two different samples both producing "drums.musicxml"). See
    transcription_service.run()'s docstring for the full reasoning.
    """
    score = build_score([result], title=output_name)

    stems_dir = stem_output_dir(MUSICXML_STEMS_DIR, input_stem)
    stems_dir.mkdir(parents=True, exist_ok=True)
    output_path = stems_dir / f"{output_name}.musicxml"
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


def _beats_per_measure(time_signature: str) -> float:
    """Beats (quarter-note units) per measure for a "N/D" time signature string.

    E.g. "4/4" -> 4.0, "6/8" -> 3.0 (six eighth notes = three quarter notes).
    """
    numerator, denominator = time_signature.split("/")
    return float(numerator) * 4.0 / float(denominator)


def _pad_to_end_beat(segments: List[Segment], end_beat: float) -> List[Segment]:
    """Append a trailing rest segment so this part's content reaches end_beat.

    Needed so every part in a combined multi-stem score has the same total length
    (see the comment in build_score() for why — MuseScore rejects a multi-part score
    where one part's measures run out before another's). A no-op if this stem's
    content already reaches (or exceeds) end_beat.
    """
    current_end = segments[-1].end_beat if segments else 0.0
    if end_beat <= current_end + 1e-9:
        return segments
    return segments + [Segment(current_end, end_beat, [])]


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

        # A segment (note, chord, or rest) longer than MAX_DURATION_BEATS must be
        # split into multiple consecutive elements, not just truncated to one
        # MAX_DURATION_BEATS-long element — appending only the capped element while
        # still advancing the cursor by the segment's FULL length silently drops the
        # remainder from the part entirely. For notes/chords this discards real
        # transcribed content; for the trailing padding rest added by _pad_to_end_beat
        # (see build_score()) it leaves the part short of the combined score's total
        # length, which MuseScore hard-rejects as an "Incomplete measure" in every
        # part after the first that ran out of appended elements.
        remaining = seg.end_beat - seg.start_beat
        while remaining > 1e-9:
            span = min(remaining, MAX_DURATION_BEATS)
            note_duration = duration.Duration(quarterLength=span)

            if not seg.pitches:
                element = note.Rest(duration=note_duration)
            elif len(seg.pitches) == 1:
                element = note.Note(seg.pitches[0], duration=note_duration)
            else:
                element = chord.Chord(seg.pitches, duration=note_duration)
            part.append(element)

            remaining -= span

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


def _build_percussion_part(
    segments: List[Segment],
    tempo_bpm: float,
    time_signature: str = "4/4",
) -> stream.Part:
    """Build a single percussion-clef staff of Unpitched notes from drum hit segments.

    Parallel to _build_staff_part() (same rest-filling, MAX_DURATION_BEATS-splitting,
    and makeMeasures()/makeTies() cleanup), but for Unpitched percussion notation
    instead of real pitched Note/Chord elements — no key signature (percussion
    doesn't have one) and no accidental suppression (nothing to suppress).

    Each segment's "pitches" are GM percussion pitch numbers from
    drum_transcription_service.py (see DRUM_STAFF_POSITIONS above). A segment
    with more than one simultaneous pitch (e.g. kick+hihat together) is notated
    as a music21.percussion.PercussionChord — multiple Unpitched noteheads
    sharing one stem/position — via _drum_pitches_to_element(), rather than
    dropping to a single winner or splitting into a second music21 Voice (both
    tried first; see DRUM_VOICE_PRIORITY's comment for why PercussionChord won).

    One instrument.UnpitchedPercussion() for the whole part/drum kit (not one per
    note — that was tried and reverted: giving each note its own concrete Instrument
    subclass (BassDrum/SnareDrum/HiHatCymbal) DID get each staff position playing
    back as its own correct drum sound via per-instrument percMapPitch, but broke
    the MusicXML's part-list structure — confirmed 6 real <part> elements but 7
    <score-part> entries in a real combined score, an extra dangling <score-part>
    with no matching <part>; MuseScore silently tolerated it but it's not valid,
    clean MusicXML, and the real bug lives somewhere in how music21's PartExporter
    handles multiple Instrument subclasses inserted into one stream). Reverted to
    one shared instrument for the whole part: writes <midi-channel>10</midi-channel>
    (General MIDI's percussion channel — this alone is what fixes playback sounding
    like piano) but leaves percMapPitch unset, so every note falls back to one
    single default percussion sound regardless of staff position (accepted
    trade-off for now — a real per-voice drum-kit sound mapping is a follow-up,
    not solved by this pass).
    """
    part = stream.Part()
    part.append(instrument.UnpitchedPercussion())
    part.append(clef.PercussionClef())
    part.append(meter.TimeSignature(time_signature))
    part.append(tempo.MetronomeMark(number=round(tempo_bpm)))

    cursor = 0.0
    for seg in segments:
        if seg.start_beat > cursor:
            part.append(note.Rest(duration=duration.Duration(quarterLength=seg.start_beat - cursor)))

        drum_pitches = _drum_voices_present(seg.pitches)

        # Same over-length splitting as _build_staff_part() — see that function's
        # comment for why this matters (silently-dropped content / MuseScore
        # rejecting mismatched part lengths in a combined score otherwise).
        remaining = seg.end_beat - seg.start_beat
        while remaining > 1e-9:
            span = min(remaining, MAX_DURATION_BEATS)
            note_duration = duration.Duration(quarterLength=span)
            element = _drum_pitches_to_element(drum_pitches, note_duration)
            part.append(element)

            remaining -= span

        cursor = seg.end_beat

    part = part.makeMeasures()
    part.makeTies(inPlace=True)

    return part


def _drum_voices_present(pitches: List[int]) -> List[int]:
    """Which known GM percussion pitches are sounding in a segment, in
    DRUM_VOICE_PRIORITY's display order (kick, snare, hihat).

    Any pitch not in DRUM_STAFF_POSITIONS (shouldn't happen — drum_transcription_
    service.py only emits the 3 known GM numbers) is dropped rather than crashing.
    """
    known = [p for p in pitches if p in DRUM_STAFF_POSITIONS]
    return sorted(known, key=lambda p: DRUM_VOICE_PRIORITY.index(p))


def _drum_pitches_to_element(drum_pitches: List[int], note_duration: duration.Duration):
    """Build the actual music21 element for a segment's drum pitch set.

    Empty -> Rest. One pitch -> a plain Unpitched note (same as before this
    supported simultaneous hits at all). Two or more -> a PercussionChord, all
    sharing note_duration, each keeping its own staff position/notehead shape —
    this is what actually notates simultaneous hits (e.g. kick+hihat) as real
    independent noteheads instead of picking one and dropping the rest.
    """
    if not drum_pitches:
        return note.Rest(duration=note_duration)

    unpitched_notes = []
    for pitch in drum_pitches:
        staff_position, notehead, _display_name = DRUM_STAFF_POSITIONS[pitch]
        n = note.Unpitched(displayName=staff_position)
        n.notehead = notehead
        unpitched_notes.append(n)

    if len(unpitched_notes) == 1:
        element = unpitched_notes[0]
        element.duration = note_duration
        return element

    p_chord = percussion.PercussionChord(unpitched_notes)
    p_chord.duration = note_duration
    return p_chord


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
