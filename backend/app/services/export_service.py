import subprocess
from pathlib import Path

from app.config.settings import MSCZ_DIR, MUSESCORE_PATH


def to_mscz(musicxml_path: str, output_name: str) -> Path:
    """Convert a MusicXML file into an editable MuseScore (.mscz) project via the
    MuseScore CLI, so a musician can open it directly and correct uncertain notes.
    """
    MSCZ_DIR.mkdir(parents=True, exist_ok=True)
    output_path = MSCZ_DIR / f"{output_name}.mscz"

    result = subprocess.run(
        [MUSESCORE_PATH, "-o", str(output_path), str(musicxml_path)],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"MuseScore export failed (exit {result.returncode}): {result.stderr}"
        )
    if not output_path.exists():
        raise RuntimeError(f"MuseScore reported success but {output_path} was not created")

    return output_path
