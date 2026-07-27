"""Split a mixed audio file into stems using Demucs.

Reads the model name and expected stem names from settings.py
(DEMUCS_MODEL / DEMUCS_STEM_NAMES) rather than hardcoding them here, so
switching which stems this returns is a one-line config change, not a code
change. Demucs itself always computes every stem for the chosen model —
DEMUCS_STEM_NAMES only controls which of those output files this function
reads back and returns; any stems Demucs wrote that aren't in that list
are simply left on disk unused.
"""

import subprocess
from pathlib import Path
from typing import Dict

from app.config.settings import DEMUCS_MODEL, DEMUCS_STEM_NAMES, STEMS_DIR


def run(input_path: str) -> Dict[str, Path]:
    """Separate a mixed audio file into the stems named in settings.DEMUCS_STEM_NAMES.

    Returns a dict mapping stem name -> wav path. Raises FileNotFoundError if
    Demucs's output layout doesn't match what's expected (e.g. DEMUCS_MODEL
    in settings.py doesn't point at an installed model, or DEMUCS_STEM_NAMES
    names a stem that model doesn't produce — e.g. asking the default
    4-source htdemucs for "guitar").
    """
    audio_path = Path(input_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {input_path}")

    STEMS_DIR.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        ["demucs", "-n", DEMUCS_MODEL, "--out", str(STEMS_DIR), str(audio_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Demucs separation failed (exit {result.returncode}): {result.stderr}"
        )

    output_dir = STEMS_DIR / DEMUCS_MODEL / audio_path.stem

    stems: Dict[str, Path] = {}
    for stem_name in DEMUCS_STEM_NAMES:
        stem_path = output_dir / f"{stem_name}.wav"
        if not stem_path.exists():
            raise FileNotFoundError(
                f"Expected stem '{stem_name}' not found at {stem_path}. "
                f"Check that DEMUCS_MODEL='{DEMUCS_MODEL}' in settings.py "
                f"actually produces a '{stem_name}' stem (guitar/piano need "
                f"htdemucs_6s, not the default 4-source htdemucs)."
            )
        stems[stem_name] = stem_path

    return stems
