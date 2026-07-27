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
# Per-stem MusicXML written during a multi-stem run, before stems are combined into
# one score — kept separate from MUSICXML_DIR (which holds single-stem AND combined
# output) purely so it's obvious at a glance which files are the intermediate,
# testing-only per-stem versions vs. the final combined score.
MUSICXML_STEMS_DIR = MUSICXML_DIR / "stems"
PDF_DIR = STORAGE_DIR / "pdf"
MSCZ_DIR = STORAGE_DIR / "mscz"

SAMPLES_DIR = PROJECT_DIR / "samples"

MUSESCORE_PATH = r"C:\Program Files\MuseScore 4\bin\MuseScore4.exe"


def stem_output_dir(base_dir: Path, input_stem: str | None) -> Path:
    """Resolve where a per-stem output file should live.

    When input_stem is given (the ORIGINAL sample's filename stem, e.g. "sample5" —
    not the Demucs stem name like "drums"), nests under base_dir/input_stem/, matching
    storage/stems/<model>/<input_stem>/<stem_name>.wav's layout. This is needed
    because run_pipeline.py's multi-stem run writes one file per Demucs stem name
    (drums.mid, piano.notes.json, etc.) — running the pipeline on two different
    samples would otherwise silently overwrite each other's same-named stem files.

    When input_stem is omitted (the single-file test scripts — test_musicxml.py,
    test_export.py, etc. — where output_name already IS the sample name, e.g.
    "sample2.musicxml", so there's no collision to avoid), returns base_dir
    unchanged — same flat layout as before.
    """
    return base_dir / input_stem if input_stem else base_dir

# --- separation stage (Demucs) ---
# htdemucs_6s is the only Demucs variant with guitar/piano as their own
# stems (vanilla htdemucs lumps them into "other"). It always produces all 6
# stems regardless of DEMUCS_STEM_NAMES; this just controls which of those
# output files demucs_service.run() reads back and returns to the rest of
# the pipeline. All 6 are used now (previously bass/other were left on disk
# unused).
DEMUCS_MODEL = "htdemucs_6s"
DEMUCS_STEM_NAMES = ("vocals", "drums", "bass", "guitar", "piano", "other")

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

# --- drum transcription stage ---
# Basic Pitch is a pitched-note model (fundamental-frequency estimation) — it has
# no concept of unpitched percussion, so running it on a drums stem mostly misses
# real hits entirely and mislabels what little it does catch as near-arbitrary
# melodic pitches (confirmed on a real drum stem: 17 "notes" out of a 50-second
# track, all low-confidence ~0.15-0.3s blips clustered in one narrow pitch range —
# not real melodic content). drum_transcription_service.py uses onset detection +
# rule-based spectral classification instead — see that module for the approach.
DRUM_SAMPLE_RATE = 22050
# General MIDI percussion pitch numbers — used so drum "notes" flow through the
# existing NoteEvent/quantization pipeline unchanged; musicxml_service.py maps
# these specific numbers to percussion-clef staff positions instead of treating
# them as normal pitched notes.
DRUM_VOICE_MIDI_PITCH = {
    "kick": 36,
    "snare": 38,
    "hihat": 42,
}
DRUM_ONSET_WINDOW_SECONDS = 0.15  # spectral analysis window right after each onset
# Kick classification: NOT spectral centroid — checked against 191 real onsets from
# a separated drum stem and found useless for this (every single real onset's
# centroid landed 1000-7000Hz, since a short post-onset window is dominated by
# broadband transient "click" energy regardless of drum type, drowning out a kick's
# actual low-frequency body; would have classified 0 of 191 real onsets as kick).
# Low-frequency energy RATIO (STFT energy below DRUM_LOW_FREQ_CUTOFF_HZ, as a
# fraction of the window's total energy) instead showed a clean bimodal split on
# the same real data: roughly half the onsets sat near ~0.0-0.1 (no bass content)
# and the other half above ~0.7 (kick-dominated) — DRUM_KICK_LOW_ENERGY_RATIO sits
# in the gap between those clusters.
DRUM_LOW_FREQ_CUTOFF_HZ = 150.0
DRUM_KICK_LOW_ENERGY_RATIO = 0.5
# Snare vs. hi-hat classification (among onsets already ruled out as kicks): back to
# spectral centroid, since low-energy ratio doesn't distinguish these two — real
# non-kick onsets from the same test clustered fairly tightly around ~4200Hz median;
# this threshold is a pragmatic midpoint of that observed range, not a validated
# clean bimodal split (this stem may not have had many/any clearly-separated snare
# hits to calibrate against) — treat snare-vs-hihat as the least reliable of the
# three voice classifications.
DRUM_SPECTRAL_CENTROID_SNARE_HZ = 4200.0  # below this (and not a kick): snare; above: hi-hat
# Drum hits have no natural "offset" to detect (onset detection only gives a start
# time), so a duration has to be invented. A single fixed duration doesn't work: at
# 0.1s, it's barely larger than a 16th note at common tempos (e.g. ~0.094s at
# 160 BPM) — checked against 188 real onsets from a real drum stem, 156 of them
# (83%) had their onset/offset SNAP TO THE SAME beat-grid position in
# quantization_service._snap() and got silently dropped as "zero duration" by
# run()'s `if offset_beat <= onset_beat: continue` check. Using a fraction of the
# gap until the NEXT onset instead scales the duration to the actual note density
# (short between fast hi-hat hits, longer between sparse kicks) — long enough to
# reliably survive 16th-note snapping, short enough not to visually overlap the
# next hit. Capped at a max for isolated/final hits with no nearby next onset.
DRUM_ONSET_DURATION_FRACTION_OF_GAP = 0.8
DRUM_ONSET_MIN_DURATION_SECONDS = 0.15
DRUM_ONSET_MAX_DURATION_SECONDS = 0.3
