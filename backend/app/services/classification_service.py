"""Classify a Demucs 'other' stem as guitar or piano accompaniment.

Scope: Demucs already separates and names vocals/drums/bass/other — those
four labels are used directly, no model needed. This service only handles
the one gap Demucs leaves: 'other.wav' still mixes piano, guitar, and other
accompaniment together. It is not called on vocals/drums/bass.

First version: a lightweight rule-based classifier using librosa spectral
features (spectral centroid, zero-crossing rate, harmonic ratio). No new
heavy dependencies — avoids the TensorFlow/YAMNet conflict risk flagged in
CLAUDE.md. Swapping in a real pretrained model later only means replacing
the body of `classify_stem`; the input/output contract stays the same.

Known limitation: Demucs's 'other' stem is its noisiest output (some
vocal/drum bleed is common — see CLAUDE.md gotchas and Demucs's own
per-stem benchmarks). The harmonic-ratio check below exists specifically
to fall back to "unknown_accompaniment" on that kind of non-tonal bleed,
rather than force a guitar/piano guess on it.
"""

from pathlib import Path

import librosa
import numpy as np

from app.config.settings import (
    CLASSIFICATION_SAMPLE_RATE,
    MIN_HARMONIC_RATIO_FOR_LABEL,
    SPECTRAL_CENTROID_GUITAR_HZ,
    ZERO_CROSSING_RATE_GUITAR_THRESHOLD,
)


def classify_stem(stem_path: str) -> str:
    """Classify a Demucs 'other' stem WAV as guitar or piano accompaniment.

    Returns one of: "piano_accompaniment", "guitar_accompaniment",
    "unknown_accompaniment".
    """
    audio_path = Path(stem_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"Stem file not found: {stem_path}")

    y, sr = librosa.load(str(audio_path), sr=CLASSIFICATION_SAMPLE_RATE, mono=True)

    if np.max(np.abs(y)) < 1e-4:
        return "unknown_accompaniment"

    y_harmonic, _y_percussive = librosa.effects.hpss(y)
    harmonic_energy = float(np.sum(y_harmonic**2))
    total_energy = float(np.sum(y**2)) or 1e-9
    harmonic_ratio = harmonic_energy / total_energy

    spectral_centroid = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr)))
    zero_crossing_rate = float(np.mean(librosa.feature.zero_crossing_rate(y)))

    return _rule_based_label(harmonic_ratio, spectral_centroid, zero_crossing_rate)


def _rule_based_label(harmonic_ratio: float, spectral_centroid: float, zero_crossing_rate: float) -> str:
    """
    Placeholder decision logic, thresholds validated against synthetic test
    signals only (not real audio) — see scripts/test_classification.py.
    Treat the output as a suggestion the user can override, same as any
    other stage in this pipeline (Project_Proposal.md 5.4).
    """
    if harmonic_ratio < MIN_HARMONIC_RATIO_FOR_LABEL:
        # Mostly non-tonal — likely drum/noise bleed into the 'other' stem
        # rather than a clean guitar or piano signal. Don't force a guess.
        return "unknown_accompaniment"

    if spectral_centroid >= SPECTRAL_CENTROID_GUITAR_HZ and zero_crossing_rate >= ZERO_CROSSING_RATE_GUITAR_THRESHOLD:
        return "guitar_accompaniment"

    return "piano_accompaniment"
