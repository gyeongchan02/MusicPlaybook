"""CLI: python -m arrangement_pipeline --spec ... --out-dir ..."""

from __future__ import annotations

import argparse
from pathlib import Path

from .pipeline import ArrangementPipeline


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert MusicPlaybook arrangement_spec.json to arranged MIDI/WAV.",
    )
    parser.add_argument(
        "--spec",
        type=Path,
        required=True,
        help="Path to arrangement_spec.json (or baseline_spec.json)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        required=True,
        help="Output directory for arranged.mid and arranged.wav",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="MusicPlaybook repo root (default: parent of arrangement_pipeline)",
    )
    parser.add_argument(
        "--source-midi",
        type=Path,
        default=None,
        help="Override POP909 source .mid path",
    )
    parser.add_argument(
        "--chords",
        type=Path,
        default=None,
        help="Override chord_midi.txt path",
    )
    parser.add_argument(
        "--variant",
        choices=("primary", "alternative", "baseline"),
        default="primary",
        help="Which spec block to render (dual-output uses primary by default)",
    )
    parser.add_argument(
        "--style-definitions",
        type=Path,
        default=None,
        help="Override style_definitions.json path",
    )
    parser.add_argument(
        "--no-wav",
        action="store_true",
        help="Skip FluidSynth WAV render",
    )
    parser.add_argument(
        "--no-drums",
        action="store_true",
        help="Skip percussion track",
    )
    args = parser.parse_args()

    repo_root = args.repo_root or Path(__file__).resolve().parents[1]
    pipeline = ArrangementPipeline(
        repo_root=repo_root,
        style_definitions_path=args.style_definitions,
    )
    result = pipeline.run(
        spec_path=args.spec,
        out_dir=args.out_dir,
        source_midi=args.source_midi,
        chord_annotation=args.chords,
        variant=args.variant,
        render_wav=not args.no_wav,
        include_drums=not args.no_drums,
    )
    print(f"Wrote {result.midi_path}")
    if result.wav_path:
        print(f"Wrote {result.wav_path}")
    print(f"tempo={result.tempo_bpm} bpm, bars={result.num_bars}")


if __name__ == "__main__":
    main()
