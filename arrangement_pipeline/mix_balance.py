"""Per-track velocity scaling for clearer, more listenable renders."""

from __future__ import annotations

import pretty_midi

_TRACK_SCALE: dict[str, dict[str, float]] = {
    "jazz": {
        "MELODY": 0.88,
        "piano": 0.78,
        "comp": 0.78,
        "rhodes": 0.78,
        "walking_bass": 0.84,
        "bass": 0.84,
        "drums": 0.62,
        "string_pad": 0.55,
    },
    "lofi": {
        "MELODY": 0.9,
        "piano": 0.68,
        "comp": 0.68,
        "rhodes": 0.68,
        "walking_bass": 0.76,
        "bass": 0.76,
        "drums": 0.58,
        "string_pad": 0.42,
    },
    "default": {
        "MELODY": 0.92,
        "drums": 0.7,
        "string_pad": 0.55,
    },
}


def _scale_for_track(name: str, family: str) -> float:
    family_map = _TRACK_SCALE.get(family, _TRACK_SCALE["default"])
    if name in family_map:
        return family_map[name]
    lowered = name.lower()
    for key, scale in family_map.items():
        if key in lowered:
            return scale
    return family_map.get(name, _TRACK_SCALE["default"].get(name, 1.0))


def apply_listenability_mix(pm: pretty_midi.PrettyMIDI, family: str) -> None:
    for inst in pm.instruments:
        scale = _scale_for_track(inst.name, family)
        if scale == 1.0:
            continue
        for note in inst.notes:
            note.velocity = max(1, min(127, int(note.velocity * scale)))
