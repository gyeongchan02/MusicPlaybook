"""Main arrangement pipeline: POP909 MIDI + spec JSON → arranged.mid / arranged.wav."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pretty_midi

from .accompaniment import build_full_chord_timeline, generate_accompaniment
from .pop909 import (
    build_preserved_melody,
    default_paths,
    load_pop909_midi,
    parse_chord_file,
    resolve_tracks,
)
from .melody_grid import quantize_notes_to_beat_grid
from .melody_treatment import apply_melody_treatment
from .mix_balance import apply_listenability_mix
from .render import render_midi_to_wav
from .style_render import build_render_plan
from .spec_loader import (
    bar_chord_overrides,
    get_preserved,
    get_song_id,
    get_tempo_bpm,
    get_transformations,
    load_spec,
)
from .timing import BeatGrid, lookup_source_tempo, parse_beat_file

MAX_ARRANGEMENT_BARS = 65
PREVIEW_BAR_THRESHOLD = 16


def resolve_num_bars(
    preserved: dict,
    beat_grid: BeatGrid,
    max_bars: int = MAX_ARRANGEMENT_BARS,
) -> int:
    """
    Use full beat-grid length when debate spec only captured a short excerpt.

    Multi-agent specs often set num_bars to ~7–10 for the opening chord preview
    while POP909 songs span many more bars.
    """
    beat_bars = min(beat_grid.num_bars, max_bars)
    spec_bars = preserved.get("num_bars")
    if spec_bars is None:
        return beat_bars
    spec_bars = int(spec_bars)
    if spec_bars >= beat_bars:
        return spec_bars
    if spec_bars <= PREVIEW_BAR_THRESHOLD and beat_bars > spec_bars * 2:
        return beat_bars
    return spec_bars


@dataclass
class PipelineResult:
    midi_path: Path
    wav_path: Path | None
    tempo_bpm: float
    source_tempo_bpm: float
    num_bars: int
    beat_origin: float


class ArrangementPipeline:
    def __init__(
        self,
        repo_root: Path,
        style_definitions_path: Path | None = None,
    ):
        self.repo_root = Path(repo_root)
        self.style_definitions_path = (
            str(style_definitions_path) if style_definitions_path else None
        )

    def run(
        self,
        spec_path: Path,
        out_dir: Path,
        source_midi: Path | None = None,
        chord_annotation: Path | None = None,
        beat_annotation: Path | None = None,
        variant: str = "primary",
        render_wav: bool = True,
        include_drums: bool = True,
        source_tempo_bpm: float | None = None,
    ) -> PipelineResult:
        spec = load_spec(spec_path)
        preserved = get_preserved(spec)
        transform = get_transformations(spec, variant=variant)
        song_id = get_song_id(spec, preserved)
        spec_tempo_bpm = get_tempo_bpm(transform, preserved)

        if source_midi is None or chord_annotation is None:
            default_midi, default_chords, default_beats = default_paths(
                self.repo_root, song_id
            )
            source_midi = source_midi or default_midi
            chord_annotation = chord_annotation or default_chords
            beat_annotation = beat_annotation or default_beats

        source_midi = Path(source_midi)
        chord_annotation = Path(chord_annotation)
        beat_annotation = Path(beat_annotation)
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        if source_tempo_bpm is None:
            preserved_tempo = preserved.get("tempo_bpm")
            if preserved_tempo is not None:
                source_tempo_bpm = float(preserved_tempo)
            else:
                source_tempo_bpm = lookup_source_tempo(self.repo_root, song_id)
        beat_grid = parse_beat_file(beat_annotation, source_tempo_bpm)

        src = load_pop909_midi(source_midi)
        tracks = resolve_tracks(src)
        melody_src = tracks.get("melody")
        if melody_src is None or not melody_src.notes:
            raise ValueError(f"No MELODY track in {source_midi}")

        num_bars = resolve_num_bars(preserved, beat_grid)
        plan = build_render_plan(
            transform,
            spec_tempo_bpm,
            source_tempo_bpm,
            self.style_definitions_path,
        )
        tempo_bpm = plan.tempo_bpm
        mel = plan.melody

        out_pm = pretty_midi.PrettyMIDI(initial_tempo=tempo_bpm)
        melody = build_preserved_melody(
            tracks,
            beat_grid,
            tempo_bpm,
            lead_program_name=mel.program_name,
            velocity_cap=mel.velocity_cap,
            velocity_floor=mel.velocity_floor,
        )
        quantize_notes_to_beat_grid(
            melody.notes,
            beat_grid,
            tempo_bpm,
            num_bars,
            n_steps=mel.quantize_steps,
            swing_ratio=mel.swing_ratio,
            strength=mel.quantize_strength,
        )
        apply_melody_treatment(melody.notes, mel, tempo_bpm)
        out_pm.instruments.append(melody)

        ann = parse_chord_file(chord_annotation)
        overrides = bar_chord_overrides(transform, preserved)
        timeline = build_full_chord_timeline(
            ann,
            tempo_bpm,
            num_bars,
            overrides,
            beat_grid=beat_grid,
        )
        melody_windows = [(n.start, n.end) for n in melody.notes]
        comp_instruments = generate_accompaniment(
            segments=timeline,
            tempo_bpm=tempo_bpm,
            num_bars=num_bars,
            rhythm_pattern=plan.rhythm_pattern,
            voicing_style=plan.voicing_style,
            texture_density=plan.texture_density,
            instrumentation=plan.instrumentation,
            beat_grid=beat_grid,
            style_definitions_path=self.style_definitions_path,
            include_drums=include_drums and plan.include_drums,
            include_pad=plan.include_pad,
            melody_windows=melody_windows,
        )
        out_pm.instruments.extend(comp_instruments)

        apply_listenability_mix(out_pm, plan.style_family)

        midi_out = out_dir / "arranged.mid"
        out_pm.write(str(midi_out))

        wav_out: Path | None = None
        if render_wav:
            wav_out = out_dir / "arranged.wav"
            render_midi_to_wav(midi_out, wav_out)

        return PipelineResult(
            midi_path=midi_out,
            wav_path=wav_out,
            tempo_bpm=tempo_bpm,
            source_tempo_bpm=source_tempo_bpm,
            num_bars=num_bars,
            beat_origin=beat_grid.origin,
        )


def run_pipeline(
    spec_path: str | Path,
    out_dir: str | Path,
    repo_root: str | Path | None = None,
    **kwargs,
) -> PipelineResult:
    root = Path(repo_root) if repo_root else Path(spec_path).resolve().parents[2]
    pipeline = ArrangementPipeline(repo_root=root)
    return pipeline.run(Path(spec_path), Path(out_dir), **kwargs)
