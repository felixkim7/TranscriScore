"""Shared audio-loading, loudness normalization, mel-spectrogram, and
tempo/onset detection — and, via preprocess_stem(), the per-stem pass that now
runs BEFORE Basic Pitch transcription for every pitched stem.

Per CLAUDE.md's pipeline table, this stage is "load, resample, mel-spectrogram,
tempo/onset." Tempo and onset detection already existed before this file, just
duplicated inline in the stages that needed them (quantization_service.py's
detect_tempo()/run(), drum_transcription_service.py's onset_detect() call) —
each independently re-loading and re-analyzing the same audio. This module
centralizes that logic into one implementation both stages now call, rather
than duplicating it a third time here and leaving the original two in place.

load_audio() is a thin librosa.load() wrapper, not a shared cache: different
callers genuinely need different sample rates (quantization needs the native
rate for accurate beat positions; drum classification needs a fixed rate for
its spectral analysis — see DRUM_SAMPLE_RATE), so this is one implementation
parameterized by sr, not one array reused everywhere.

Why preprocess_stem() exists (the "help Basic Pitch transcribe better" ask):
Basic Pitch's predict() (transcription_service.py) only accepts a FILE PATH —
it does its own internal librosa.load(sr=22050, mono=True) and its own internal
feature extraction, unconditionally, regardless of what's fed in. That rules
out most "preprocessing" as something that can change what Basic Pitch's model
actually sees — sample-rate/mono normalization, our mel-spectrogram, our onset
detection none of these can be passed into predict() directly; there's no
parameter for it. Checked directly against basic_pitch.inference's source
before deciding this.

The one thing that DOES change transcription quality, and what preprocess_stem()
does before every pitched stem is transcribed: LOUDNESS NORMALIZATION changes
the actual audio bytes Basic Pitch reads, since we write a new wav and point
predict() at THAT path instead of the raw stem. Basic Pitch's onset_threshold/
frame_threshold are fixed energy thresholds tuned once against whatever
loudness the validation clips happened to be at — a quiet stem can have real
notes fall under threshold, a hot one can trigger spurious activations.
Normalizing every stem to the same peak level first removes stem-to-stem
loudness variance as a confound.

Two other ideas were tried and REMOVED after real testing (see
transcription_service.run()'s docstring for the full writeup): passing
predict()'s minimum_frequency/maximum_frequency per stem type (negligible
effect), and a post-transcription filter cross-checking Basic Pitch's note
onsets against this module's independently-detected onset times (REMOVED —
cut 190->109 notes, 43%, on a real vocals stem, and on listening turned out
to be overfiltering real content, not just phantom notes).

mel_spectrogram() and detect_tempo_onset()'s onset_times/tempo/beats, still
computed by preprocess_stem(), do NOT feed Basic Pitch's model (no such input
exists) and are NOT currently consumed by anything after the onset-filter
removal — kept on PreprocessResult as available groundwork (per CLAUDE.md's
spec for this stage), same "detected but not yet used" status as
pipeline_service.py's reference_tempo_bpm/reference_beat_times on the Job.
"""

from dataclasses import dataclass
from typing import Optional, Tuple

import librosa
import numpy as np
import soundfile as sf

from app.config.settings import PREPROCESSED_AUDIO_DIR, PREPROCESSING_TARGET_PEAK_DBFS, stem_output_dir


@dataclass
class TempoOnsetResult:
    tempo_bpm: float
    # Raw beat frame POSITIONS (librosa's native output from beat_track) and the
    # matching real-seconds times — kept as two arrays (not just the tempo float)
    # because quantization_service._beat_grid() needs actual beat positions to
    # interpolate a note's onset/offset against, not just a BPM number.
    beat_frames: np.ndarray
    beat_times: np.ndarray
    onset_times: np.ndarray


@dataclass
class PreprocessResult:
    # Path to the LOUDNESS-NORMALIZED copy of the stem, written to
    # PREPROCESSED_AUDIO_DIR — pass this to transcription_service.run(),
    # NOT the raw stem path, so Basic Pitch actually transcribes the
    # normalized audio.
    normalized_audio_path: str
    tempo_bpm: float
    beat_times: np.ndarray
    onset_times: np.ndarray
    mel_spectrogram: np.ndarray


def load_audio(path: str, sr: Optional[int] = None, mono: bool = True) -> Tuple[np.ndarray, int]:
    """Load an audio file, resampling to sr if given (native rate if sr=None).

    Thin wrapper around librosa.load() — the value isn't in changing the
    behavior, it's in having ONE place callers ask for audio instead of each
    stage independently calling librosa.load() with its own assumptions.
    """
    y, actual_sr = librosa.load(path, sr=sr, mono=mono)
    return y, actual_sr


def mel_spectrogram(
    y: np.ndarray,
    sr: int,
    n_mels: int = 128,
    n_fft: int = 2048,
    hop_length: int = 512,
) -> np.ndarray:
    """Compute a log-power mel-spectrogram for y.

    Returns a (n_mels, n_frames) array in dB (librosa.power_to_db), the
    conventional representation for feeding into spectrogram-based analysis —
    raw power spectrograms span too many orders of magnitude to threshold or
    compare directly.
    """
    mel = librosa.feature.melspectrogram(y=y, sr=sr, n_mels=n_mels, n_fft=n_fft, hop_length=hop_length)
    return librosa.power_to_db(mel, ref=np.max)


def detect_tempo_onset(y: np.ndarray, sr: int) -> TempoOnsetResult:
    """Detect tempo, the beat grid, and onset times from an already-loaded signal.

    Takes y/sr (not a file path) so a caller that already loaded the audio (at
    whatever sample rate it needed) doesn't have to reload it a second time
    just to get tempo/onsets — load_audio() once, pass the result here.

    beat_track() and onset_detect() are two independent librosa analyses (not
    onset_detect() derived from the beat grid or vice versa) — same as they
    were run independently in quantization_service.py and
    drum_transcription_service.py before this refactor, so behavior here
    matches what both already did, just in one place.
    """
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units="frames")
    tempo = float(np.asarray(tempo).item())
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    onset_times = librosa.onset.onset_detect(y=y, sr=sr, units="time", backtrack=True)

    return TempoOnsetResult(
        tempo_bpm=tempo,
        beat_frames=np.asarray(beat_frames, dtype=float),
        beat_times=np.asarray(beat_times, dtype=float),
        onset_times=np.asarray(onset_times, dtype=float),
    )


def normalize_loudness(y: np.ndarray, target_peak_dbfs: float = PREPROCESSING_TARGET_PEAK_DBFS) -> np.ndarray:
    """Scale y so its peak amplitude sits at target_peak_dbfs (near 0dBFS, not clipping).

    Peak normalization, not full loudness/LUFS normalization — simpler, and
    sufficient for the actual goal here (removing stem-to-stem loudness
    variance as a confound for Basic Pitch's fixed onset/frame thresholds), not
    perceptual loudness matching. Silent input (peak == 0, e.g. a stem with no
    real content) is returned unchanged rather than dividing by zero.
    """
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    if peak <= 0.0:
        return y

    target_linear = 10.0 ** (target_peak_dbfs / 20.0)
    gain = target_linear / peak
    return y * gain


def preprocess_stem(
    audio_path: str,
    stem_name: str,
    input_stem: Optional[str] = None,
) -> PreprocessResult:
    """Run the full preprocessing pass on one separated stem, before it's
    handed to transcription — load, loudness-normalize (write the result to
    disk), mel-spectrogram, tempo estimation, beat tracking, onset detection.

    stem_name: the Demucs stem name (e.g. "vocals") — used only to name the
    normalized output file consistently with the input.
    input_stem: see load_audio()-adjacent callers' convention throughout this
    codebase (transcription_service.run(), quantization_service.run(), etc.) —
    the ORIGINAL sample's filename stem (job_id for API-driven runs), for
    nesting output under PREPROCESSED_AUDIO_DIR/<input_stem>/ so a multi-stem
    run on two different samples can't overwrite each other's same-named
    stem files. Omit for single-file runs where there's no collision risk.
    """
    y, sr = load_audio(audio_path, sr=None, mono=True)

    normalized = normalize_loudness(y)

    out_dir = stem_output_dir(PREPROCESSED_AUDIO_DIR, input_stem)
    out_dir.mkdir(parents=True, exist_ok=True)
    normalized_path = out_dir / f"{stem_name}.wav"
    sf.write(str(normalized_path), normalized, sr)

    mel = mel_spectrogram(normalized, sr)
    tempo_onset = detect_tempo_onset(normalized, sr)

    return PreprocessResult(
        normalized_audio_path=str(normalized_path),
        tempo_bpm=tempo_onset.tempo_bpm,
        beat_times=tempo_onset.beat_times,
        onset_times=tempo_onset.onset_times,
        mel_spectrogram=mel,
    )
