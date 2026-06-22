"""Align preserved melody to the same swung grid as accompaniment."""

from __future__ import annotations

import pretty_midi

from .timing import BeatGrid


def _mapped_bar_bounds(
    beat_grid: BeatGrid,
    bar_idx: int,
    tempo_bpm: float,
) -> tuple[float, float]:
    src_start, src_end = beat_grid.bar_bounds(bar_idx)
    return (
        beat_grid.map_time(src_start, tempo_bpm),
        beat_grid.map_time(src_end, tempo_bpm),
    )


def _bar_index_for_time(
    time_sec: float,
    beat_grid: BeatGrid,
    tempo_bpm: float,
    num_bars: int,
) -> int:
    for bar_idx in range(num_bars):
        start, end = _mapped_bar_bounds(beat_grid, bar_idx, tempo_bpm)
        if start <= time_sec < end - 1e-9:
            return bar_idx
    return max(0, num_bars - 1)


def quantize_notes_to_beat_grid(
    notes: list[pretty_midi.Note],
    beat_grid: BeatGrid,
    tempo_bpm: float,
    num_bars: int,
    *,
    n_steps: int = 8,
    swing_ratio: float = 0.72,
    strength: float = 0.62,
) -> None:
    """
    Soft-quantize note onsets to the POP909 beat grid within each bar.

    Snapping bar-locally avoids pulling notes across bar lines. Duration is
    preserved (lightly shortened) so phrasing stays musical.
    """
    if not notes:
        return

    for note in notes:
        original_dur = max(0.08, note.end - note.start)
        bar_idx = _bar_index_for_time(note.start, beat_grid, tempo_bpm, num_bars)
        step_times = beat_grid.step_times_for_bar(
            bar_idx,
            tempo_bpm,
            n_steps=n_steps,
            swing_ratio=swing_ratio,
        )
        if not step_times:
            continue
        nearest = min(step_times, key=lambda t: abs(t - note.start))
        note.start = note.start + (nearest - note.start) * strength
        note.end = note.start + max(0.08, original_dur * 0.92)
