"""Voicing engines driven by style_definitions.json."""

from __future__ import annotations

from .chords import ParsedChord


def _clamp_register(pitches: list[int], low: int = 48, high: int = 84) -> list[int]:
    if not pitches:
        return []
    while min(pitches) < low:
        pitches = [p + 12 for p in pitches]
    while max(pitches) > high:
        pitches = [p - 12 for p in pitches]
    return sorted(set(pitches))


def _add_ninth(pitches: list[int], root_pc: int) -> list[int]:
    if not pitches:
        return pitches
    ninth = max(pitches) + 2
    if ninth % 12 == (root_pc + 2) % 12:
        return sorted(set(pitches + [ninth]))
    return pitches


def build_voicing(
    parsed: ParsedChord,
    style_cfg: dict,
    *,
    register_low: int = 48,
    register_high: int = 84,
) -> list[int]:
    strategy = style_cfg.get("strategy", "spread")
    root_pc = parsed.root_pc
    base = int(style_cfg.get("base_midi", 60))

    if strategy == "drop2":
        intervals = style_cfg.get("drop_intervals", [0, 7, 10, 14])
        voices = [base + (root_pc + i) % 12 + (12 if (root_pc + i) % 12 < root_pc else 0) for i in intervals]
    else:
        spread = style_cfg.get("spread_semitones", [0, 7, 14, 21])
        voices = []
        for offset in spread:
            pitch = base + root_pc + offset
            while pitch < base:
                pitch += 12
            voices.append(pitch)

    if style_cfg.get("add_ninth", False):
        voices = _add_ninth(voices, root_pc)

    max_voices = int(style_cfg.get("max_voices", 5))
    voices = sorted(set(voices))[:max_voices]
    return _clamp_register(voices, low=register_low, high=register_high)
