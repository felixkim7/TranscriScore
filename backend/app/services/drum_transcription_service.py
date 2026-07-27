"""Transcribe a drum stem into note events using onset detection + spectral
classification, instead of Basic Pitch.

Basic Pitch is a pitched-note (fundamental-frequency) model — it has no concept
of unpitched percussion, so running it on a drums stem is the wrong tool, not
just a tuning problem. Confirmed on a real separated drum stem: Basic Pitch found
only 17 "notes" across a 50-second track, all short (~0.15-0.3s) and low-confidence
(amplitude 0.3-0.45), clustered in one narrow MIDI pitch range — not real melodic
content, just occasional transients the model's pitch-onset detector happened to
fire on.

This module instead:
1. Detects onset times directly via librosa's onset-strength peak-picker (built
   for exactly this — finding transient attacks, no assumption of pitch).
2. Classifies each onset into a small set of drum voices (kick/snare/hi-hat) in
   two stages — see _classify_voice()'s docstring for why spectral centroid alone
   (the classification_service.classify_stem() approach) doesn't work for kick
   detection specifically, and what real onset data showed instead.
3. Emits each hit as a NoteEvent using a General MIDI percussion pitch number
   (settings.DRUM_VOICE_MIDI_PITCH) as a STAND-IN for pitch — not a real melodic
   pitch. This lets drum hits flow through the existing NoteEvent -> quantization
   pipeline completely unchanged; musicxml_service.py is what actually interprets
   these specific pitch numbers as percussion-clef staff positions instead of
   normal notes, when stem_label == "drums".
4. Also writes a standalone MIDI file to storage/midi/ (matching transcription_
   service.run()'s output contract, which drums previously lacked — Basic Pitch
   provides a MIDI object for free from predict(), onset detection doesn't, so
   this needs to build one explicitly via _to_midi()). Uses is_drum=True on the
   PrettyMIDI Instrument so pitch 36/38/42 correctly plays back as kick/snare/
   hi-hat on General MIDI channel 10, not as a piano playing those pitches.

Rule-based thresholds, not a trained drum classifier — same caveat as
classification_service.py: treat the voice assignment as a reasonable guess, not
a guarantee, especially on bleed-heavy separated drum stems. The kick/non-kick
split was validated against 191 real onsets from a real separated drum stem; the
snare-vs-hihat split within the non-kick group was not (see _classify_voice()) —
treat that specific distinction as the least reliable of the three.
"""

from pathlib import Path
from typing import List, Optional

import librosa
import numpy as np
import pretty_midi

from app.config.settings import (
    DRUM_KICK_LOW_ENERGY_RATIO,
    DRUM_LOW_FREQ_CUTOFF_HZ,
    DRUM_ONSET_DURATION_FRACTION_OF_GAP,
    DRUM_ONSET_MAX_DURATION_SECONDS,
    DRUM_ONSET_MIN_DURATION_SECONDS,
    DRUM_ONSET_WINDOW_SECONDS,
    DRUM_SAMPLE_RATE,
    DRUM_SPECTRAL_CENTROID_SNARE_HZ,
    DRUM_VOICE_MIDI_PITCH,
    INTERMEDIATE_DIR,
    MIDI_DIR,
    stem_output_dir,
)
from app.schemas.transcription import NoteEvent

import json


def run(input_path: str, stem_label: str = "drums", input_stem: Optional[str] = None) -> List[NoteEvent]:
    """Transcribe a drum stem into note events via onset detection + spectral
    voice classification.

    Writes the resulting MIDI to storage/midi/ and the note events as JSON to
    storage/intermediate/, matching transcription_service.run()'s output contract,
    so downstream stages (quantization, musicxml) don't need to know or care that
    drums took a different recognition path.

    input_stem: see transcription_service.run()'s docstring — the ORIGINAL
    sample's filename stem, for nesting output per-sample in a multi-stem run.
    """
    audio_path = Path(input_path)
    y, sr = librosa.load(str(audio_path), sr=DRUM_SAMPLE_RATE, mono=True)

    onset_times = librosa.onset.onset_detect(y=y, sr=sr, units="time", backtrack=True)
    clip_duration = len(y) / sr

    note_events = []
    window_samples = int(DRUM_ONSET_WINDOW_SECONDS * sr)
    for i, onset_time in enumerate(onset_times):
        start_sample = int(onset_time * sr)
        window = y[start_sample : start_sample + window_samples]
        if len(window) == 0:
            continue

        voice = _classify_voice(window, sr)
        onset = float(onset_time)
        offset = onset + _hit_duration(onset_time, onset_times, i, clip_duration)

        note_events.append(
            NoteEvent(
                pitch=DRUM_VOICE_MIDI_PITCH[voice],
                onset=onset,
                offset=offset,
                duration=offset - onset,
                velocity=_onset_velocity(window),
                confidence=1.0,  # onset detection doesn't produce a per-hit confidence score
                stem_label=stem_label,
            )
        )

    midi_dir = stem_output_dir(MIDI_DIR, input_stem)
    midi_dir.mkdir(parents=True, exist_ok=True)
    midi_path = midi_dir / f"{audio_path.stem}.mid"
    _to_midi(note_events).write(str(midi_path))

    intermediate_dir = stem_output_dir(INTERMEDIATE_DIR, input_stem)
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    notes_path = intermediate_dir / f"{audio_path.stem}.notes.json"
    notes_path.write_text(json.dumps([n.model_dump() for n in note_events], indent=2))

    return note_events


def _hit_duration(onset_time: float, onset_times: np.ndarray, index: int, clip_duration: float) -> float:
    """Duration (seconds) to assign a drum hit, scaled to the gap until the next
    onset rather than a fixed value.

    A fixed small duration (originally 0.1s) doesn't survive quantization's 16th-
    note snapping at common tempos — checked against real data: 83% of hits ended
    up with onset_beat == offset_beat after snapping and were silently dropped as
    "zero duration." Scaling to the gap until the next onset (DRUM_ONSET_DURATION_
    FRACTION_OF_GAP of it, clamped to [MIN, MAX]) keeps hits long enough to survive
    snapping regardless of tempo, without extending into the next hit. The last
    onset in a stem has no "next onset" to measure against — falls back to the gap
    until the clip's end instead (still clamped the same way).
    """
    if index + 1 < len(onset_times):
        gap = onset_times[index + 1] - onset_time
    else:
        gap = clip_duration - onset_time

    duration = gap * DRUM_ONSET_DURATION_FRACTION_OF_GAP
    return max(DRUM_ONSET_MIN_DURATION_SECONDS, min(DRUM_ONSET_MAX_DURATION_SECONDS, duration))


def _to_midi(note_events: List[NoteEvent]) -> pretty_midi.PrettyMIDI:
    """Build a PrettyMIDI object from raw (seconds-based) drum note events.

    is_drum=True on the Instrument routes it to General MIDI channel 10 (the
    standard percussion channel) — this is what makes pitch 36/38/42 actually
    play back as kick/snare/hi-hat in any MIDI player/DAW, instead of a piano
    sounding those pitches as normal melodic notes.
    """
    midi = pretty_midi.PrettyMIDI()
    instrument = pretty_midi.Instrument(program=0, is_drum=True, name="Drums")

    for n in note_events:
        instrument.notes.append(
            pretty_midi.Note(velocity=n.velocity, pitch=n.pitch, start=n.onset, end=n.offset)
        )

    midi.instruments.append(instrument)
    return midi


def _classify_voice(window: np.ndarray, sr: int) -> str:
    """Classify a short post-onset audio window into kick/snare/hihat.

    Two stages, not one spectral-centroid threshold (the classification_service.
    classify_stem() approach) — spectral centroid alone was tried first and found
    useless for kick detection specifically: checked against 191 real onsets from a
    real separated drum stem, EVERY one had a centroid in the 1000-7000Hz range,
    because a short post-onset window is dominated by the broadband transient
    "click" energy present in any drum hit, which drowns out a kick's actual
    low-frequency body. That approach would have classified 0 of 191 real onsets
    as kick.

    Stage 1 (kick vs. not): ratio of STFT energy below DRUM_LOW_FREQ_CUTOFF_HZ to
    the window's total energy. This showed a clean bimodal split on the same real
    data — most onsets sat near ~0.0-0.1 (no real bass content) or above ~0.7
    (kick-dominated), with DRUM_KICK_LOW_ENERGY_RATIO in the gap between clusters.

    Stage 2 (snare vs. hihat, only for onsets that failed stage 1): spectral
    centroid, using DRUM_SPECTRAL_CENTROID_SNARE_HZ. Real onset data didn't show
    as clean a split here — see that constant's comment in settings.py — so this
    stage is a pragmatic midpoint, not a validated threshold.
    """
    if _low_frequency_energy_ratio(window, sr) >= DRUM_KICK_LOW_ENERGY_RATIO:
        return "kick"

    centroid = float(np.mean(librosa.feature.spectral_centroid(y=window, sr=sr)))
    return "snare" if centroid < DRUM_SPECTRAL_CENTROID_SNARE_HZ else "hihat"


def _low_frequency_energy_ratio(window: np.ndarray, sr: int) -> float:
    """Fraction of a window's STFT energy below DRUM_LOW_FREQ_CUTOFF_HZ."""
    spectrum = np.abs(librosa.stft(window, n_fft=512))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=512)
    total_energy = float(np.sum(spectrum**2))
    if total_energy <= 0:
        return 0.0
    low_energy = float(np.sum(spectrum[freqs < DRUM_LOW_FREQ_CUTOFF_HZ] ** 2))
    return low_energy / total_energy


def _onset_velocity(window: np.ndarray) -> int:
    """MIDI velocity (1-127) from a post-onset window's peak amplitude."""
    peak = float(np.max(np.abs(window))) if len(window) else 0.0
    return max(1, min(127, round(peak * 127)))
