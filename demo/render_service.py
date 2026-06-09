"""Arrangement rendering for the Streamlit demo."""

from __future__ import annotations

from pathlib import Path

from arrangement_pipeline.fluidsynth_render import render_midi_with_fluidsynth
from arrangement_pipeline.pipeline import ArrangementPipeline
from arrangement_pipeline.reference_wav import read_reference_duration, reference_wav_path

from .paths import REPO_ROOT


def render_arrangement(
    spec_path: Path,
    out_dir: Path,
    *,
    variant: str = "primary",
    reference_wav: Path | None = None,
    source_midi: Path | None = None,
    chord_annotation: Path | None = None,
    beat_annotation: Path | None = None,
    source_tempo_bpm: float | None = None,
    include_drums: bool = True,
) -> tuple[Path, Path]:
    """
    Render arranged.mid + arranged.wav from a spec JSON.

    Returns (midi_path, wav_path).
    """
    from arrangement_pipeline.spec_loader import get_preserved, get_song_id, load_spec

    spec = load_spec(spec_path)
    preserved = get_preserved(spec)
    if reference_wav is None:
        song_id = get_song_id(spec, preserved)
        ref_wav = reference_wav_path(REPO_ROOT, song_id)
    else:
        ref_wav = Path(reference_wav)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pipeline = ArrangementPipeline(repo_root=REPO_ROOT)
    result = pipeline.run(
        spec_path=spec_path,
        out_dir=out_dir,
        source_midi=source_midi,
        chord_annotation=chord_annotation,
        beat_annotation=beat_annotation,
        variant=variant,
        render_wav=False,
        include_drums=include_drums,
        source_tempo_bpm=source_tempo_bpm,
    )

    wav_out = out_dir / "arranged.wav"
    render_midi_with_fluidsynth(
        midi_path=result.midi_path,
        wav_path=wav_out,
        reference_wav_path=ref_wav,
    )

    import soundfile as sf

    ref_frames, ref_sr, _ = read_reference_duration(ref_wav)
    out_info = sf.info(str(wav_out))
    if out_info.frames != ref_frames or out_info.samplerate != ref_sr:
        raise RuntimeError(
            f"Length mismatch: arranged {out_info.frames}@{out_info.samplerate} "
            f"vs reference {ref_frames}@{ref_sr}"
        )

    return result.midi_path, wav_out
