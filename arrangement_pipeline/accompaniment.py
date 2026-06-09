"""Generate bass, Rhodes comp, and optional drums from chord timeline + style JSON."""

from __future__ import annotations

import pretty_midi

from .chords import ParsedChord, parse_chord_symbol
from .rhythm import select_active_steps, step_duration, steps_per_bar
from .style_registry import get_instrument, get_rhythm_pattern, get_voicing_style
from .timing import BeatGrid
from .voicing import build_voicing


def _gm_program(name: str) -> int:
    return pretty_midi.instrument_name_to_program(name)


def _append_note(
    inst: pretty_midi.Instrument,
    pitch: int,
    start: float,
    end: float,
    velocity: int,
) -> None:
    inst.notes.append(
        pretty_midi.Note(
            velocity=max(1, min(127, int(velocity))),
            pitch=int(pitch),
            start=float(start),
            end=float(max(start + 0.02, end)),
        )
    )


def generate_accompaniment(
    segments: list[tuple[float, float, str]],
    tempo_bpm: float,
    num_bars: int,
    rhythm_pattern: str,
    voicing_style: str,
    texture_density: float,
    instrumentation: dict,
    beat_grid: BeatGrid | None = None,
    style_definitions_path: str | None = None,
    include_drums: bool = True,
) -> list[pretty_midi.Instrument]:
    from .style_registry import load_style_definitions

    defs = load_style_definitions(style_definitions_path)
    rhythm_cfg = get_rhythm_pattern(rhythm_pattern, defs)
    voicing_cfg = get_voicing_style(voicing_style, defs)

    bar_sec = 60.0 / tempo_bpm * 4.0
    grid = rhythm_cfg.get("grid", "16th")
    swing = float(rhythm_cfg.get("swing_ratio", 0.66))

    bass_inst_name = instrumentation.get("bass", "upright_bass")
    lead_inst_name = instrumentation.get("lead", "rhodes_electric_piano")
    perc_name = instrumentation.get("percussion")

    bass_meta = get_instrument(bass_inst_name, defs)
    rhodes_meta = get_instrument(lead_inst_name, defs)

    bass = pretty_midi.Instrument(
        program=_gm_program(bass_meta["gm_program"]),
        name=bass_meta.get("track_name", "bass"),
    )
    rhodes = pretty_midi.Instrument(
        program=_gm_program(rhodes_meta["gm_program"]),
        name="rhodes_comp",
    )
    drums: pretty_midi.Instrument | None = None
    if include_drums and perc_name:
        drums = pretty_midi.Instrument(program=0, is_drum=True, name="drums")

    comp_candidates = rhythm_cfg.get("comp_active_steps", [0, 4, 8, 12])
    comp_steps = select_active_steps(comp_candidates, texture_density)
    bass_steps = rhythm_cfg.get("bass_pattern_steps", [0])
    drum_cfg = rhythm_cfg.get("drum", {})

    for bar_idx in range(num_bars):
        if beat_grid is not None:
            src_start, src_end = beat_grid.bar_bounds(bar_idx)
            bar_start = beat_grid.map_time(src_start, tempo_bpm)
            bar_end = beat_grid.map_time(src_end, tempo_bpm)
            bar_sec_local = bar_end - bar_start
        else:
            bar_start = bar_idx * bar_sec
            bar_end = bar_start + bar_sec
            bar_sec_local = bar_sec
        bar_segments = [
            (s, e, sym)
            for s, e, sym in segments
            if s < bar_end and e > bar_start
        ]
        if not bar_segments:
            bar_segments = [(bar_start, bar_end, "N")]

        for seg_start, seg_end, symbol in bar_segments:
            parsed = parse_chord_symbol(symbol)
            if parsed is None:
                continue

            voices = build_voicing(parsed, voicing_cfg)
            root_bass = 36 + parsed.root_pc
            comp_vel = int(voicing_cfg.get("velocity", rhythm_cfg.get("comp_velocity", 58)))
            comp_dur = rhythm_cfg.get("comp_duration_ratio", 0.42) * step_duration(
                bar_sec_local, grid
            )
            bass_vel = int(rhythm_cfg.get("bass_velocity", 82))
            bass_dur = (
                rhythm_cfg.get("bass_duration_ratio", 0.88)
                * bar_sec_local
                / max(1, len(bass_steps))
            )

            n_steps = steps_per_bar(grid)
            if beat_grid is not None:
                step_times = beat_grid.step_times_for_bar(
                    bar_idx, tempo_bpm, n_steps=n_steps, swing_ratio=swing
                )
            else:
                from .rhythm import swung_step_time

                step_times = [
                    swung_step_time(bar_start, step, bar_sec_local, grid, swing)
                    for step in range(n_steps)
                ]
            for step, t in enumerate(step_times):
                if t < seg_start or t >= seg_end:
                    continue

                if step in bass_steps:
                    _append_note(bass, root_bass, t, min(seg_end, t + bass_dur), bass_vel)

                if step in comp_steps:
                    for pitch in voices:
                        _append_note(rhodes, pitch, t, min(seg_end, t + comp_dur), comp_vel)

                if drums and drum_cfg:
                    if step in drum_cfg.get("kick_steps", []):
                        _append_note(
                            drums,
                            drum_cfg["kick_pitch"],
                            t,
                            t + 0.08,
                            drum_cfg.get("kick_velocity", 78),
                        )
                    if step in drum_cfg.get("snare_steps", []):
                        _append_note(
                            drums,
                            drum_cfg["snare_pitch"],
                            t,
                            t + 0.08,
                            drum_cfg.get("snare_velocity", 62),
                        )
                    if step in drum_cfg.get("hat_steps", []):
                        _append_note(
                            drums,
                            drum_cfg["hat_pitch"],
                            t,
                            t + 0.04,
                            drum_cfg.get("hat_velocity", 40),
                        )

    instruments = [bass, rhodes]
    if drums is not None:
        instruments.append(drums)
    return instruments


def build_full_chord_timeline(
    annotation_segments: list,
    tempo_bpm: float,
    num_bars: int,
    bar_overrides: dict[int, str] | None = None,
    beat_grid: BeatGrid | None = None,
) -> list[tuple[float, float, str]]:
    """Merge POP909 chord file with optional per-bar spec overrides."""
    from .pop909 import ChordSegment, bar_starts, segments_for_bar

    bar_overrides = bar_overrides or {}
    bar_sec = 60.0 / tempo_bpm * 4.0
    timeline: list[tuple[float, float, str]] = []

    ann = [
        ChordSegment(start=s.start, end=s.end, symbol=s.symbol)
        if hasattr(s, "symbol")
        else ChordSegment(start=s[0], end=s[1], symbol=s[2])
        for s in annotation_segments
    ]

    for bar_idx in range(num_bars):
        bar_number = bar_idx + 1
        if beat_grid is not None:
            src_start, src_end = beat_grid.bar_bounds(bar_idx)
            bar_start = beat_grid.map_time(src_start, tempo_bpm)
            bar_end = beat_grid.map_time(src_end, tempo_bpm)
        else:
            src_start = bar_idx * bar_sec
            src_end = src_start + bar_sec
            bar_start, bar_end = src_start, src_end
        if bar_number in bar_overrides:
            timeline.append((bar_start, bar_end, bar_overrides[bar_number]))
            continue
        for seg_start, seg_end, symbol in segments_for_bar(ann, src_start, src_end):
            if beat_grid is not None:
                timeline.append(
                    (
                        beat_grid.map_time(seg_start, tempo_bpm),
                        beat_grid.map_time(seg_end, tempo_bpm),
                        symbol,
                    )
                )
            else:
                timeline.append((seg_start, seg_end, symbol))
    return timeline
