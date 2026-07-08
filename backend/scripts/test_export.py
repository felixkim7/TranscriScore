"""Standalone smoke test for export_service (MusicXML -> MSCZ via MuseScore CLI).

This is the first true end-to-end demo: audio in, editable MuseScore file out.

Usage:
    python scripts/test_export.py                        # first file in samples/, runs the full chain
    python scripts/test_export.py --file ../samples/sample2.mp3
    python scripts/test_export.py --from-cache sample2    # reuse storage/intermediate/sample2.quantized.json
    python scripts/test_export.py --from-musicxml sample2 # reuse storage/musicxml/sample2.musicxml directly
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.settings import MUSICXML_DIR, SAMPLES_DIR
from app.services import export_service, musicxml_service, quantization_service, transcription_service


def pick_default_file() -> Path:
    candidates = sorted(
        p for p in SAMPLES_DIR.glob("*") if p.suffix.lower() in (".mp3", ".wav", ".flac", ".m4a")
    )
    if not candidates:
        raise SystemExit(f"No audio files found in {SAMPLES_DIR}")
    return candidates[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", help="Path to an audio file (defaults to first file in samples/)")
    parser.add_argument(
        "--from-cache",
        metavar="STEM_NAME",
        help="Skip transcription+quantization; load storage/intermediate/<STEM_NAME>.quantized.json instead",
    )
    parser.add_argument(
        "--from-musicxml",
        metavar="STEM_NAME",
        help="Skip straight to export; reuse storage/musicxml/<STEM_NAME>.musicxml directly",
    )
    args = parser.parse_args()

    if args.from_musicxml:
        output_name = args.from_musicxml
        musicxml_path = MUSICXML_DIR / f"{output_name}.musicxml"
        if not musicxml_path.exists():
            raise SystemExit(f"No MusicXML found at {musicxml_path}")
        print(f"Reusing MusicXML: {musicxml_path}")
    else:
        if args.from_cache:
            result = quantization_service.load_quantization_result(args.from_cache)
            output_name = args.from_cache
            print(f"Loaded cached quantization result for: {args.from_cache}")
        else:
            audio_path = Path(args.file) if args.file else pick_default_file()
            output_name = audio_path.stem
            print(f"Transcribing: {audio_path}")
            note_events = transcription_service.run(str(audio_path))
            print(f"Raw note events: {len(note_events)}")
            result = quantization_service.run(note_events, audio_path=str(audio_path))

        print(f"Tempo: {result.tempo_bpm:.2f} BPM, {len(result.notes)} quantized notes")
        musicxml_path = musicxml_service.run(result, output_name=output_name)
        print(f"MusicXML written to: {musicxml_path}")

    mscz_path = export_service.to_mscz(str(musicxml_path), output_name=output_name)
    print(f"MSCZ written to: {mscz_path}")


if __name__ == "__main__":
    main()
