"""Load arrangement_spec.json and extract active transformations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_spec(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def get_transformations(
    spec: dict[str, Any],
    variant: str = "primary",
) -> dict[str, Any]:
    """
    Return the transformations block to render.

    variant: 'primary' | 'alternative' | 'baseline' (uses top-level transformations)
    """
    if variant == "baseline" and "transformations" in spec:
        return spec["transformations"]
    if variant == "alternative" and "alternative_spec" in spec:
        return spec["alternative_spec"]["transformations"]
    if "primary_spec" in spec:
        return spec["primary_spec"]["transformations"]
    return spec["transformations"]


def get_preserved(spec: dict[str, Any]) -> dict[str, Any]:
    return spec.get("preserved", {})


def get_tempo_bpm(transform: dict[str, Any], preserved: dict[str, Any] | None = None) -> float:
    if "tempo_bpm" in transform:
        return float(transform["tempo_bpm"])
    tempo = transform.get("tempo", {})
    if isinstance(tempo, dict) and "target_bpm" in tempo:
        return float(tempo["target_bpm"])
    if preserved and "tempo_bpm" in preserved:
        return float(preserved["tempo_bpm"])
    return 90.0


def get_song_id(spec: dict[str, Any], preserved: dict[str, Any] | None = None) -> str:
    meta = spec.get("metadata", {})
    if "input_song_id" in meta:
        return meta["input_song_id"]
    if preserved and "input_song_id" in preserved:
        return preserved["input_song_id"]
    raise ValueError("arrangement spec missing metadata.input_song_id")


def bar_chord_overrides(transform: dict[str, Any]) -> dict[int, str]:
    """Optional per-bar chord overrides from spec preview / progression."""
    overrides: dict[int, str] = {}
    for key in ("chord_progression", "chord_progression_preview"):
        entries = transform.get(key) or []
        for item in entries:
            bar = int(item.get("bar", 0))
            if bar > 0:
                overrides[bar] = item.get("chord", "N")
    return overrides
