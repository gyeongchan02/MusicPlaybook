"""
Entry point: arrangement spec → arranged.mid + arranged.wav (FluidSynth, reference length).

Does not modify core MusicPlaybook assets. Run from repo root:

    python -m arrangement_pipeline.run \\
      --spec outputs/run_.../arrangement_spec.json \\
      --out-dir outputs/run_.../arranged
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .fluidsynth_render import render_midi_with_fluidsynth
from .pipeline import ArrangementPipeline
from .reference_wav import read_reference_duration, reference_wav_path
from .spec_loader import (
    get_preserved,
    get_song_id,
    get_transformations,
    load_spec,
    summarize_active_spec,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Arrangement JSON → MIDI + FluidSynth WAV (reference length).",
    )
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--source-midi", type=Path, default=None)
    parser.add_argument("--chords", type=Path, default=None)
    parser.add_argument(
        "--reference-wav",
        type=Path,
        default=None,
        help="Original wav (default: data/wav_renders/<song_id>.wav)",
    )
    parser.add_argument(
        "--variant",
        choices=("primary", "alternative", "baseline"),
        default="primary",
    )
    parser.add_argument("--style-definitions", type=Path, default=None)
    parser.add_argument("--no-drums", action="store_true")
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print which spec fields are used for rendering",
    )
    args = parser.parse_args()

    repo_root = args.repo_root or Path(__file__).resolve().parents[1]
    spec = load_spec(args.spec)
    if args.verbose:
        import json

        summary = summarize_active_spec(spec, variant=args.variant)
        print("Active arrangement settings:")
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        transform = get_transformations(spec, variant=args.variant)
        if "primary_spec" in spec and args.variant == "primary":
            print(
                "Note: dual-output spec — editing only preserved.* does not change audio; "
                "edit primary_spec.transformations or use --variant alternative."
            )
        if not transform.get("chord_progression") and not transform.get(
            "chord_progression_preview"
        ):
            print(
                "Note: no chord_progression in transformations — "
                "using preserved.original_chord_progression + chord_midi.txt."
            )
    preserved = get_preserved(spec)
    song_id = get_song_id(spec, preserved)
    ref_wav = args.reference_wav or reference_wav_path(repo_root, song_id)

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
        render_wav=False,
        include_drums=not args.no_drums,
    )

    wav_out = args.out_dir / "arranged.wav"
    render_midi_with_fluidsynth(
        midi_path=result.midi_path,
        wav_path=wav_out,
        reference_wav_path=ref_wav,
    )

    import soundfile as sf

    ref_frames, ref_sr, ref_dur = read_reference_duration(ref_wav)
    out_info = sf.info(str(wav_out))
    print(f"Wrote {result.midi_path}")
    print(f"Wrote {wav_out}")
    print(
        f"reference: {ref_wav.name} ({ref_dur:.3f}s @ {ref_sr} Hz) → "
        f"arranged.wav ({out_info.frames / out_info.samplerate:.3f}s, {out_info.frames} frames)"
    )
    if out_info.frames != ref_frames or out_info.samplerate != ref_sr:
        raise RuntimeError(
            f"Length mismatch: arranged {out_info.frames}@{out_info.samplerate} "
            f"vs reference {ref_frames}@{ref_sr}"
        )
    print(
        f"timing: source={result.source_tempo_bpm} bpm → target={result.tempo_bpm} bpm, "
        f"downbeat origin={result.beat_origin:.3f}s"
    )


if __name__ == "__main__":
    main()
