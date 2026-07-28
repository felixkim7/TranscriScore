"""CLI wrapper for the full audio -> combined MusicXML/MSCZ pipeline.

The actual pipeline logic lives in app/services/pipeline_service.py (moved there
so both this script and the async API — app/api/transcribe.py, step 8 — can call
the same code without duplicating it). This script just prints a final summary.

Usage:
    python scripts/run_pipeline.py <audio_path>
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import pipeline_service


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_pipeline.py <audio_path>")
        raise SystemExit(1)

    input_audio_path = sys.argv[1]

    result = pipeline_service.run_full_pipeline(input_audio_path)

    print(f"Combined MusicXML written to: {result['combined_musicxml_path']}")
    print(f"Combined MSCZ written to: {result['combined_mscz_path']}")


if __name__ == "__main__":
    main()
