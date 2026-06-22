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
    """texture_density in [0, 1]: fraction of candidate comp steps to keep."""
    density = max(0.0, min(1.0, float(texture_density)))
    if density <= 0:
        return []
    if density >= 1:
        return list(candidate_steps)
    keep = max(1, round(len(candidate_steps) * density))
    return candidate_steps[:keep]


def _density_trim(steps: list[int], texture_density: float) -> list[int]:
    density = max(0.0, min(1.0, float(texture_density)))
    if not steps or density >= 1.0:
        return list(steps)
    keep = max(1, round(len(steps) * density))
    return sorted(steps)[:keep]


def _pattern_family(rhythm_pattern: str) -> str:
    name = rhythm_pattern.lower()
    if name.startswith("lofi") or "lo_fi" in name:
        return "lofi"
    if name.startswith("ballad"):
        return "ballad"
    if name.startswith("bossa"):
        return "bossa"
    if name.startswith("jazz"):
        return "jazz"
    return "default"


def comp_steps_for_bar(
    bar_idx: int,
    candidate_steps: list[int],
    texture_density: float,
    rhythm_pattern: str,
) -> list[int]:
    """
    Pick comp steps per bar so accompaniment does not repeat the same grid every bar.
    """
    if not candidate_steps:
        return []

    family = _pattern_family(rhythm_pattern)
    candidates = list(candidate_steps)

    if family == "lofi":
        rotations = [
            [0, 5, 10, 12],
            [2, 7, 14],
            [0, 7, 10],
            [5, 12],
        ]
        steps = [s for s in rotations[bar_idx % 4] if s in candidates]
        if bar_idx % 8 == 7:
            steps = steps[: max(1, len(steps) // 2)]
        elif bar_idx % 8 == 3 and len(steps) < len(candidates):
            extras = [s for s in candidates if s not in steps]
            if extras:
                steps = sorted(set(steps + [extras[bar_idx % len(extras)]]))
    elif family == "ballad":
        rotations = [
            [0, 8],
            [0, 4, 12],
            [0, 10],
            [4, 12],
        ]
        steps = [s for s in rotations[bar_idx % 4] if s in candidates]
    elif family == "bossa":
        rotations = [
            [2, 5, 10, 13],
            [2, 10, 13],
            [5, 10],
            [2, 13],
        ]
        steps = [s for s in rotations[bar_idx % 4] if s in candidates]
    elif family == "jazz":
        rotations = [
            [1, 3, 5, 7],
            [1, 5, 7],
            [3, 5, 7],
            [1, 3, 7],
        ]
        steps = [s for s in rotations[bar_idx % 4] if s in candidates]
        return _density_trim(sorted(set(steps)) or candidates, texture_density)
    else:
        keep = max(1, int(len(candidates) * texture_density + 0.5))
        offset = (bar_idx * 2) % len(candidates)
        steps = [candidates[(offset + i) % len(candidates)] for i in range(keep)]

    if not steps:
        steps = select_active_steps(candidates, texture_density)
    return _density_trim(sorted(set(steps)), texture_density)
