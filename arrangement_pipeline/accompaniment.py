"""Generate bass, comp, optional pad, and drums from chord timeline + style JSON."""

from __future__ import annotations

import pretty_midi

from .chords import parse_chord_symbol
from .chords import ParsedChord
from .rhythm import comp_steps_for_bar, step_duration, steps_per_bar
from .style_registry import get_instrument, get_rhythm_pattern, get_voicing_style
from .timing import BeatGrid
from .voicing import build_voicing
from .walking_bass import walking_bass_pitch


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


def _bar_density(base: float, bar_idx: int) -> float:
    """Gentle 8-bar swell with a breath bar before the next phrase."""
    phase = (bar_idx % 8) / 7.0
    swell = 0.1 * phase
    section = 0.06 if (bar_idx // 8) % 2 == 1 else 0.0
    breath = -0.18 if bar_idx % 8 == 7 else 0.0
    return max(0.2, min(1.0, base + swell + section + breath))


def _vary_velocity(base: int, bar_idx: int, step: int, salt: int = 0) -> int:
    wobble = ((bar_idx * 17 + step * 7 + salt) % 17) - 8
    return max(1, min(127, base + wobble))


def _humanize_time(t: float, bar_idx: int, step: int) -> float:
    shift = ((bar_idx * 13 + step * 5) % 7 - 3) * 0.009
    return max(0.0, t + shift)


def _drum_velocity_scale(bar_idx: int, base: int, step: int = 0) -> int:
    accent = 6 if bar_idx % 4 == 0 else 0
    dip = -8 if bar_idx % 8 == 7 else 0
    ghost = -10 if step not in (0, 4, 8, 12) else 0
    return _vary_velocity(base + accent + dip + ghost, bar_idx, step, salt=3)


def _melody_near(
    melody_windows: list[tuple[float, float]] | None, t: float, pad: float = 0.22
) -> bool:
    if not melody_windows:
        return False
    for start, end in melody_windows:
        if start - pad <= t <= end + pad:
            return True
    return False


def _comp_voices(
    voices: list[int],
    *,
    melody_active: bool = False,
) -> list[int]:
    if not voices:
        return voices
    if melody_active and len(voices) >= 2:
        return voices[-2:]
    return voices


def _bass_pitch(parsed: ParsedChord, step: int, bar_idx: int, bass_steps: list[int]) -> int:
    root = 36 + parsed.root_pc
    if step not in bass_steps:
        return root
    pos = bass_steps.index(step)
    if pos == 0:
        return root
    tones = sorted({max(36, min(60, p)) for p in parsed.pitches})
    if len(tones) >= 3 and bar_idx % 3 == 1:
        return tones[2]
    if len(tones) >= 2 and bar_idx % 2 == 1:
        return tones[1]
    return min(60, root + 7)


def _hat_steps_for_bar(bar_idx: int, hat_steps: list[int]) -> list[int]:
    if not hat_steps:
        return []
    if bar_idx % 8 == 7:
        return hat_steps[: max(1, len(hat_steps) // 2)]
    rotations = [
        hat_steps,
        hat_steps[::2],
        hat_steps[1::2] or hat_steps,
    ]
    return rotations[bar_idx % 3] or hat_steps


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
    include_pad: bool = True,
    melody_windows: list[tuple[float, float]] | None = None,
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
    lead_meta = get_instrument(lead_inst_name, defs)

    bass = pretty_midi.Instrument(
        program=_gm_program(bass_meta["gm_program"]),
        name=bass_meta.get("track_name", "bass"),
    )
    comp = pretty_midi.Instrument(
        program=_gm_program(lead_meta["gm_program"]),
        name=lead_meta.get("track_name", "comp"),
    )
    pad: pretty_midi.Instrument | None = None
    if include_pad:
        pad = pretty_midi.Instrument(
            program=_gm_program("Synth Strings 1"),
            name="string_pad",
        )
    drums: pretty_midi.Instrument | None = None
    if include_drums and perc_name:
        drums = pretty_midi.Instrument(program=0, is_drum=True, name="drums")

    comp_candidates = rhythm_cfg.get("comp_active_steps", [0, 4, 8, 12])
    bass_steps = rhythm_cfg.get("bass_pattern_steps", [0])
    drum_cfg = rhythm_cfg.get("drum", {})

    is_lofi = rhythm_pattern.lower().startswith("lofi")
    is_jazz = rhythm_pattern.lower().startswith("jazz")
    use_walking_bass = "walking" in bass_inst_name.lower()
    if is_jazz:
        include_pad = False
    walking_prev_pitch: int | None = None

    for bar_idx in range(num_bars):
        bar_density = _bar_density(texture_density, bar_idx)
        comp_steps = comp_steps_for_bar(
            bar_idx, comp_candidates, bar_density, rhythm_pattern
        )
        breath_bar = bar_idx % 8 == 7

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

        next_parsed = None
        if bar_idx + 1 < num_bars:
            if beat_grid is not None:
                n_src_start, n_src_end = beat_grid.bar_bounds(bar_idx + 1)
                n_bar_start = beat_grid.map_time(n_src_start, tempo_bpm)
                n_bar_end = beat_grid.map_time(n_src_end, tempo_bpm)
            else:
                n_bar_start = (bar_idx + 1) * bar_sec
                n_bar_end = n_bar_start + bar_sec
            for s, e, sym in segments:
                if s < n_bar_end and e > n_bar_start:
                    next_parsed = parse_chord_symbol(sym)
                    break

        for seg_start, seg_end, symbol in bar_segments:
            parsed = parse_chord_symbol(symbol)
            if parsed is None:
                continue

            voices = build_voicing(parsed, voicing_cfg)
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
            if use_walking_bass:
                beat_dur = bar_sec_local / max(1, len(bass_steps))
                bass_dur = beat_dur * rhythm_cfg.get("bass_duration_ratio", 0.88)
            pad_vel = max(30, comp_vel - 24 - (8 if breath_bar else 0))
            pad_dur = max(comp_dur, (seg_end - seg_start) * (0.72 if breath_bar else 0.82))

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

            pad_written = False
            hat_steps = _hat_steps_for_bar(bar_idx, drum_cfg.get("hat_steps", []))
            for step, t in enumerate(step_times):
                if t < seg_start or t >= seg_end:
                    continue

                t_play = t if (is_jazz or is_lofi) else _humanize_time(t, bar_idx, step)

                if step in bass_steps:
                    if use_walking_bass:
                        beat_idx = bass_steps.index(step)
                        bass_pitch = walking_bass_pitch(
                            walking_prev_pitch,
                            parsed,
                            next_parsed,
                            beat_idx,
                        )
                        walking_prev_pitch = bass_pitch
                    else:
                        bass_pitch = _bass_pitch(parsed, step, bar_idx, bass_steps)
                    _append_note(
                        bass,
                        bass_pitch,
                        t_play,
                        min(seg_end, t_play + bass_dur),
                        _vary_velocity(bass_vel, bar_idx, step, salt=1),
                    )

                if step in comp_steps:
                    melody_active = _melody_near(melody_windows, t_play)
                    step_voices = _comp_voices(voices, melody_active=melody_active)
                    step_vel = _vary_velocity(comp_vel, bar_idx, step, salt=2)
                    if melody_active:
                        step_vel = max(42, step_vel - (6 if is_jazz else 10))
                    if breath_bar and not is_jazz:
                        step_vel = max(40, step_vel - 6)
                    for pitch in step_voices:
                        _append_note(
                            comp,
                            pitch,
                            t_play,
                            min(seg_end, t_play + comp_dur),
                            step_vel,
                        )

                if (
                    pad is not None
                    and not pad_written
                    and step == 0
                    and not is_jazz
                    and not (is_lofi and breath_bar)
                ):
                    pad_voices = voices[-2:] if len(voices) >= 2 else voices
                    for pitch in pad_voices:
                        _append_note(
                            pad,
                            min(84, pitch + 12),
                            seg_start,
                            min(seg_end, seg_start + pad_dur),
                            _vary_velocity(pad_vel, bar_idx, step, salt=4),
                        )
                    pad_written = True

                if drums and drum_cfg:
                    if step in drum_cfg.get("kick_steps", []) and not (
                        is_lofi and breath_bar and step not in (0,)
                    ):
                        _append_note(
                            drums,
                            drum_cfg["kick_pitch"],
                            t_play,
                            t_play + 0.08,
                            _drum_velocity_scale(
                                bar_idx, drum_cfg.get("kick_velocity", 78), step
                            ),
                        )
                    snare_steps = drum_cfg.get("snare_steps", [])
                    if step in snare_steps and not (breath_bar and step in snare_steps[1:]):
                        _append_note(
                            drums,
                            drum_cfg["snare_pitch"],
                            t_play,
                            t_play + 0.08,
                            _drum_velocity_scale(
                                bar_idx, drum_cfg.get("snare_velocity", 62), step
                            ),
                        )
                    ride_steps = drum_cfg.get("hat_steps", [])
                    if step in ride_steps:
                        ride_vel = drum_cfg.get("hat_velocity", 40)
                        if is_jazz:
                            ride_accents = {0: 10, 2: 4, 4: 8, 6: 2}
                            ride_vel += ride_accents.get(step, 0)
                        _append_note(
                            drums,
                            drum_cfg["hat_pitch"],
                            t_play,
                            t_play + (0.12 if is_jazz else 0.04),
                            _vary_velocity(ride_vel, bar_idx, step, salt=5),
                        )

    instruments = [bass, comp]
    if pad is not None and pad.notes:
        instruments.append(pad)
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
    from .pop909 import ChordSegment, segments_for_bar

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
