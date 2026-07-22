from pathlib import Path
from typing import List, NamedTuple

from music21 import chord, clef, duration, instrument, layout, metadata, meter, note, stream, tempo

from app.config.settings import MUSICXML_DIR
from app.schemas.transcription import QuantizationResult

MAX_DURATION_BEATS = 4.0  # cap a single note/chord at one whole note (4/4 backbone)
MIDDLE_C = 60  # staff-split threshold: segment's average pitch >= this -> treble, else bass


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
      its own branch yet): unchanged from the original backbone — two-staff
      (treble/bass) piano grand staff, chosen by per-segment average pitch.
      Notating a vocal melody or drum hits as a piano grand staff is a known
      simplification, not something fixed in this pass.

    Backbone version: a sweep-line pass collapses all overlapping notes into a single
    timeline of non-overlapping chords/notes (real sustain across new onsets is merged
    into a chord for the shared duration, split at the point pitches change), so each
    staff has exactly one voice. No key signature detection (see quality TODOs).
    """
    segments = _sweep_line_segments(result.notes)

    score = stream.Score()
    score.metadata = metadata.Metadata(title=output_name)

    if result.stem_label == "guitar_accompaniment":
        part = _build_staff_part(
            segments, result.tempo_bpm, clef.TrebleClef(),
            part_instrument=instrument.Guitar(), as_part_staff=False,
        )
        score.insert(0, part)
    elif result.stem_label == "bass":
        part = _build_staff_part(
            segments, result.tempo_bpm, clef.BassClef(),
            part_instrument=instrument.ElectricBass(), as_part_staff=False,
        )
        score.insert(0, part)
    else:
        treble_segments, bass_segments = _split_by_staff(segments)
        treble = _build_staff_part(treble_segments, result.tempo_bpm, clef.TrebleClef(), as_part_staff=True)
        bass = _build_staff_part(bass_segments, result.tempo_bpm, clef.BassClef(), as_part_staff=True)
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


def _build_staff_part(
    segments: List[Segment],
    tempo_bpm: float,
    staff_clef,
    part_instrument=None,
    as_part_staff: bool = True,
) -> stream.Part:
    part = stream.PartStaff() if as_part_staff else stream.Part()
    if part_instrument is not None:
        part.append(part_instrument)
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
