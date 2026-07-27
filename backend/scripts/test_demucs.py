"""Standalone smoke test for demucs_service."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import demucs_service


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_demucs.py <audio_path>")
        raise SystemExit(1)

    stems = demucs_service.run(sys.argv[1])

    print("Demucs separation complete")
    for stem_name, path in stems.items():
        print(f"  {stem_name:8s}: {path}")


if __name__ == "__main__":
    main()