from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent

STORAGE_DIR = BACKEND_DIR / "storage"
UPLOADS_DIR = STORAGE_DIR / "uploads"
STEMS_DIR = STORAGE_DIR / "stems"
INTERMEDIATE_DIR = STORAGE_DIR / "intermediate"
MIDI_DIR = STORAGE_DIR / "midi"
QUANTIZED_MIDI_DIR = MIDI_DIR / "quantized"
MUSICXML_DIR = STORAGE_DIR / "musicxml"
PDF_DIR = STORAGE_DIR / "pdf"
MSCZ_DIR = STORAGE_DIR / "mscz"

SAMPLES_DIR = PROJECT_DIR / "samples"

MUSESCORE_PATH = r"C:\Program Files\MuseScore 4\bin\MuseScore4.exe"

# --- classification stage (stem role classification) ---
# Scope: Demucs already gives us vocals/drums/bass/other directly — those
# four labels are used as-is, no ML needed. This classifier only runs on
# other.wav, to split it into guitar vs piano accompaniment.
CLASSIFICATION_SAMPLE_RATE = 22050
CLASSIFICATION_LABELS = (
    "piano_accompaniment",
    "guitar_accompaniment",
    "unknown_accompaniment",
)
# Heuristic thresholds — validated against synthetic piano/guitar/drum-noise
# test signals (see backend/scripts/test_classification.py), not real audio.
# Real tonal content (piano, guitar) measured harmonic_ratio 0.94-0.99;
# pure percussive/noise content measured 0.00 — 0.5 leaves a wide margin.
# Demucs's "other" stem is its noisiest/least-clean output (drum/vocal bleed
# is common), so this check exists specifically to catch that bleed rather
# than force a guitar/piano guess on non-tonal content.
MIN_HARMONIC_RATIO_FOR_LABEL = 0.5
SPECTRAL_CENTROID_GUITAR_HZ = 1800.0    # guitar measured ~2400-3900Hz vs piano ~300-425Hz
ZERO_CROSSING_RATE_GUITAR_THRESHOLD = 0.08
