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
