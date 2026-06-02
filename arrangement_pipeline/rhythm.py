"""Rhythm grid utilities (swung 16ths, step scheduling)."""

from __future__ import annotations


def steps_per_bar(grid: str) -> int:
    return 16 if grid == "16th" else 8


def step_duration(bar_sec: float, grid: str) -> float:
    return bar_sec / steps_per_bar(grid)


def swung_step_time(
    bar_start: float,
    step_index: int,
    bar_sec: float,
    grid: str,
    swing_ratio: float,
) -> float:
    """
    Place step_index on a swung subdivision grid.

    swing_ratio in (0.5, 1.0]: 0.66 ≈ triplet swing on 16ths.
    """
    n = steps_per_bar(grid)
    step = step_index % n
    pair = step // 2
    is_off = step % 2 == 1
    pair_dur = bar_sec / (n // 2)
    long = pair_dur * swing_ratio
    short = pair_dur - long
    t = bar_start
    for _ in range(pair):
        t += long + short
    if is_off:
        t += long
    return t


def select_active_steps(
    candidate_steps: list[int],
    texture_density: float,
) -> list[int]:
    """
    texture_density in [0, 1]: fraction of candidate comp steps to keep.
    """
    density = max(0.0, min(1.0, float(texture_density)))
    if density <= 0:
        return []
    if density >= 1:
        return list(candidate_steps)
    keep = max(1, int(round(len(candidate_steps) * density)))
    return candidate_steps[:keep]
