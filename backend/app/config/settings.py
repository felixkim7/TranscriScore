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

# --- separation stage (Demucs) ---
# htdemucs_6s is the only Demucs variant with guitar/piano as their own
# stems (vanilla htdemucs lumps them into "other"). We only want
# guitar/drums/vocals/piano out of the 6 it produces — bass.wav and
# other.wav still get written to disk by Demucs itself (it always computes
# all 6), demucs_service.run() just doesn't read them back.
DEMUCS_MODEL = "htdemucs_6s"
DEMUCS_STEM_NAMES = ("vocals", "drums", "guitar", "piano")

# --- classification stage ---
# NOT used to split "other.wav" anymore (there is no other.wav in the
# pipeline now — see DEMUCS_STEM_NAMES above). Its job now is verifying
# Demucs's own guitar.wav/piano.wav labels, since Demucs's docs flag the
# piano source specifically as bleed-prone. See classification_service.py.
CLASSIFICATION_SAMPLE_RATE = 22050
CLASSIFICATION_LABELS = (
    "piano_accompaniment",
    "guitar_accompaniment",
    "unknown_accompaniment",
)
MIN_HARMONIC_RATIO_FOR_LABEL = 0.5
SPECTRAL_CENTROID_GUITAR_HZ = 1800.0
ZERO_CROSSING_RATE_GUITAR_THRESHOLD = 0.08
