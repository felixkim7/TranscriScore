from pathlib import Path
from typing import List, NamedTuple

from music21 import chord, clef, duration, layout, metadata, meter, note, stream, tempo

from app.config.settings import MUSICXML_DIR
from app.schemas.transcription import QuantizationResult

MAX_DURATION_BEATS = 4.0  # cap a single note/chord at one whole note (4/4 backbone)
MIDDLE_C = 60  # staff-split threshold: segment's average pitch >= this -> treble, else bass


class Segment(NamedTuple):
    start_beat: float
    end_beat: float
    pitches: List[int]  # empty list = rest


def run(result: QuantizationResult, output_name: str) -> Path:
    """Convert a QuantizationResult into a two-staff (treble/bass) piano MusicXML score.

    Backbone version: a sweep-line pass collapses all overlapping notes into a single
    timeline of non-overlapping chords/notes (real sustain across new onsets is merged
    into a chord for the shared duration, split at the point pitches change), so each
    staff has exactly one voice. Each resulting chord is then routed to the treble or
    bass staff by its average pitch. No key signature detection (see quality TODOs).
    """
    segments = _sweep_line_segments(result.notes)
    treble_segments, bass_segments = _split_by_staff(segments)

    score = stream.Score()
    score.metadata = metadata.Metadata(title=output_name)

    treble = _build_staff_part(treble_segments, result.tempo_bpm, clef.TrebleClef())
    bass = _build_staff_part(bass_segments, result.tempo_bpm, clef.BassClef())

    score.insert(0, treble)
    score.insert(0, bass)
    score.insert(0, layout.StaffGroup(
        [treble, bass], name="Piano", abbreviation="Pno.", symbol="brace"
    ))

    MUSICXML_DIR.mkdir(parents=True, exist_ok=True)
    output_path = MUSICXML_DIR / f"{output_name}.musicxml"
    score.write("musicxml", fp=str(output_path))

    return output_path


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


def _split_by_staff(segments: List[Segment]):
    treble, bass = [], []
    for seg in segments:
        if not seg.pitches:
            treble.append(seg)
            bass.append(seg)
            continue

        avg_pitch = sum(seg.pitches) / len(seg.pitches)
        target = treble if avg_pitch >= MIDDLE_C else bass
        other = bass if avg_pitch >= MIDDLE_C else treble
        target.append(seg)
        other.append(Segment(seg.start_beat, seg.end_beat, []))

    return treble, bass


def _build_staff_part(segments: List[Segment], tempo_bpm: float, staff_clef) -> stream.PartStaff:
    part = stream.PartStaff()
    part.append(staff_clef)
    part.append(meter.TimeSignature("4/4"))
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

    return part
