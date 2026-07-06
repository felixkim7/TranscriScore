from collections import defaultdict
from pathlib import Path
from typing import List, Tuple

from music21 import chord, duration, metadata, meter, note, stream, tempo

from app.config.settings import MUSICXML_DIR
from app.schemas.transcription import QuantizationResult

MAX_DURATION_BEATS = 4.0  # cap a single note/chord at one whole note (4/4 backbone)

NoteGroup = Tuple[float, float, List[int]]  # (onset_beat, offset_beat, pitches)


def run(result: QuantizationResult, output_name: str) -> Path:
    """Convert a QuantizationResult into a single-part, multi-voice MusicXML score.

    Backbone version: fixed 4/4, one treble-clef part. Notes sharing an identical
    onset/offset are grouped into chords; notes that overlap in time without sharing
    onset/offset (e.g. a held note under a moving line) are split across separate
    music21 Voice streams via greedy interval-graph coloring, so overlapping notes
    aren't silently dropped or misplaced. No key signature detection, no independent
    staves per hand (see quality TODOs).
    """
    groups = _group_by_onset_offset(result)
    voices = _assign_voices(groups)

    part = stream.Part()
    part.append(meter.TimeSignature("4/4"))
    part.append(tempo.MetronomeMark(number=round(result.tempo_bpm)))

    for voice_groups in voices:
        part.insert(0, _build_voice(voice_groups))

    score = stream.Score()
    score.metadata = metadata.Metadata(title=output_name)
    score.insert(0, part)

    MUSICXML_DIR.mkdir(parents=True, exist_ok=True)
    output_path = MUSICXML_DIR / f"{output_name}.musicxml"
    score.write("musicxml", fp=str(output_path))

    return output_path


def _group_by_onset_offset(result: QuantizationResult) -> List[NoteGroup]:
    """Group quantized notes sharing the same onset/offset into chords, sorted by onset."""
    groups: dict[tuple[float, float], list[int]] = defaultdict(list)
    for n in result.notes:
        groups[(n.onset_beat, n.offset_beat)].append(n.pitch)

    return [
        (onset_beat, offset_beat, sorted(pitches))
        for (onset_beat, offset_beat), pitches in sorted(groups.items())
    ]


def _assign_voices(groups: List[NoteGroup]) -> List[List[NoteGroup]]:
    """Greedily assign note-groups to voices so no voice has overlapping groups.

    Classic interval-graph coloring: each voice tracks when it's next free: a group
    goes into the first voice already free by its onset, otherwise a new voice opens.
    """
    voice_free_at: List[float] = []
    voices: List[List[NoteGroup]] = []

    for onset_beat, offset_beat, pitches in groups:
        placed = False
        for i, free_at in enumerate(voice_free_at):
            if free_at <= onset_beat:
                voices[i].append((onset_beat, offset_beat, pitches))
                voice_free_at[i] = offset_beat
                placed = True
                break
        if not placed:
            voices.append([(onset_beat, offset_beat, pitches)])
            voice_free_at.append(offset_beat)

    return voices


def _build_voice(groups: List[NoteGroup]) -> stream.Voice:
    voice = stream.Voice()
    cursor = 0.0

    for onset_beat, offset_beat, pitches in groups:
        if onset_beat > cursor:
            voice.append(note.Rest(duration=duration.Duration(quarterLength=onset_beat - cursor)))

        note_duration = duration.Duration(
            quarterLength=min(offset_beat - onset_beat, MAX_DURATION_BEATS)
        )
        if len(pitches) == 1:
            element = note.Note(pitches[0], duration=note_duration)
        else:
            element = chord.Chord(pitches, duration=note_duration)
        voice.append(element)

        cursor = offset_beat

    return voice
