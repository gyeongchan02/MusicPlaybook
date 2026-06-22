"""Stepwise walking bass lines for jazz-style accompaniment."""

from __future__ import annotations

from .chords import ParsedChord


def _bass_chord_tones(parsed: ParsedChord) -> list[int]:
    root = 36 + parsed.root_pc
    tones = {root, min(58, root + 7)}
    for pitch in parsed.pitches:
        p = pitch
        while p > 58:
            p -= 12
        while p < 36:
            p += 12
        if 36 <= p <= 58:
            tones.add(p)
    return sorted(tones)


def _next_walk_pitch(
    prev_pitch: int,
    chord_tones: list[int],
    next_root: int | None,
    beat_idx: int,
) -> int:
    candidates: set[int] = set()
    for tone in chord_tones:
        for delta in (-2, -1, 0, 1, 2, 3, 4, 5):
            candidates.add(tone + delta)

    if beat_idx == 3 and next_root is not None:
        candidates.update({next_root - 2, next_root - 1, next_root, next_root + 1})

    in_range = [c for c in candidates if 36 <= c <= 58]
    if not in_range:
        return chord_tones[0]

    def cost(candidate: int) -> float:
        step = abs(candidate - prev_pitch)
        score = float(step)
        if step > 5:
            score += (step - 5) * 4.0
        if candidate == prev_pitch:
            score += 12.0
        if candidate in chord_tones:
            score -= 2.5
        if beat_idx == 3 and next_root is not None:
            score -= 4.0 * max(0.0, 3.0 - abs(candidate - (next_root - 1)))
        return score

    return min(in_range, key=cost)


def walking_bass_pitch(
    prev_pitch: int | None,
    parsed: ParsedChord,
    next_parsed: ParsedChord | None,
    beat_idx: int,
) -> int:
    tones = _bass_chord_tones(parsed)
    next_root = None
    if next_parsed is not None:
        next_root = 36 + next_parsed.root_pc

    if prev_pitch is None:
        return tones[0]

    return _next_walk_pitch(prev_pitch, tones, next_root, beat_idx)
