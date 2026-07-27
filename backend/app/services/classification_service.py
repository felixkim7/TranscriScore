"""Verify Demucs's own guitar/piano stem labels from htdemucs_6s.

Role change from the original design: this used to classify Demucs's
"other" stem into guitar-vs-piano, because vanilla htdemucs lumped them
together. Now that demucs_service.py uses htdemucs_6s (which separates
guitar and piano directly), classify_stem() is no longer needed to split
"other.wav" into an instrument guess — see settings.py's DEMUCS_STEM_NAMES.
"other.wav" (whatever htdemucs_6s couldn't assign to any of its 5 named
stems — often synths, strings, or ambiguous instrumentation) is still part
of the pipeline, just trusted directly like vocals/drums rather than run
through classify_stem(), since there's no clear guitar-vs-piano question to
verify for it.

What's left is a real, still-useful job: Demucs's own documentation flags
its piano source as bleed-prone (guitar separation is "decent", piano has
"noticeable bleeding/artifacts"). check_stem_label_confidence() re-runs the
same rule-based spectral features against the label Demucs already
assigned, so a badly-bled piano.wav can be caught and either corrected or
flagged for the user (Project_Proposal.md 5.4's human-in-the-loop step),
instead of blindly trusted.

vocals.wav, drums.wav, bass.wav, and other.wav are all trusted directly with
no check — Demucs is documented as strongest on vocals/drums specifically
(see conversation history / MDX-vs-Demucs benchmark discussion), and there's
no rule-based substitute worth building for bass or the catch-all "other"
stem either (classify_stem() only distinguishes guitar vs. piano).

No new heavy dependencies (librosa only) — avoids the TensorFlow/YAMNet
conflict risk flagged in CLAUDE.md. Swapping in a real pretrained model
later only means replacing the body of `classify_stem`; the input/output
contract stays the same.
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
    """Classify a WAV file as guitar or piano accompaniment based on its
    spectral characteristics, independent of what label it arrived with.

    Returns one of: "piano_accompaniment", "guitar_accompaniment",
    "unknown_accompaniment" (silent, or not clearly tonal — e.g. drum/noise
    bleed rather than a clean instrument signal).
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


def check_stem_label_confidence(stem_path: str, expected_label: str) -> tuple[bool, str]:
    """Sanity-check a label Demucs already assigned (its htdemucs_6s
    'guitar.wav' or 'piano.wav'), by re-running classify_stem()'s rule-based
    features and seeing whether they agree.

    Only meant for guitar.wav/piano.wav — Demucs's own docs flag the piano
    source in particular as bleed-prone; vocals/drums are trusted as-is
    (see this module's docstring).

    Returns (matches, predicted_label). Caller decides what to do on a
    mismatch — e.g. fall back to predicted_label, or flag for manual
    correction (Project_Proposal.md 5.4).
    """
    predicted = classify_stem(stem_path)
    return predicted == expected_label, predicted


def _rule_based_label(harmonic_ratio: float, spectral_centroid: float, zero_crossing_rate: float) -> str:
    """
    Thresholds validated against synthetic test signals only (not real
    audio) — see scripts/test_classification.py. Treat the output as a
    suggestion the user can override, same as any other stage in this
    pipeline (Project_Proposal.md 5.4).
    """
    if harmonic_ratio < MIN_HARMONIC_RATIO_FOR_LABEL:
        # Mostly non-tonal — likely drum/noise bleed rather than a clean
        # guitar or piano signal. Don't force a guess.
        return "unknown_accompaniment"

    if spectral_centroid >= SPECTRAL_CENTROID_GUITAR_HZ and zero_crossing_rate >= ZERO_CROSSING_RATE_GUITAR_THRESHOLD:
        return "guitar_accompaniment"

    return "piano_accompaniment"
