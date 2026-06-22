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
        t = spec["transformations"]
        return t if isinstance(t, dict) else {}
    if variant == "alternative" and "alternative_spec" in spec:
        t = spec.get("alternative_spec", {}).get("transformations", {})
        return t if isinstance(t, dict) else {}
    if "primary_spec" in spec:
        t = spec.get("primary_spec", {}).get("transformations", {})
        return t if isinstance(t, dict) else {}
    t = spec.get("transformations", {})
    return t if isinstance(t, dict) else {}


def get_preserved(spec: dict[str, Any]) -> dict[str, Any]:
    return spec.get("preserved", {})


def get_tempo_bpm(transform: dict[str, Any], preserved: dict[str, Any] | None = None) -> float:
    if "tempo_bpm" in transform:
        tempo_val = transform["tempo_bpm"]
        if isinstance(tempo_val, dict):
            for key in ("target_bpm", "target", "bpm", "value"):
                if key in tempo_val:
                    return float(tempo_val[key])
        else:
            return float(tempo_val)
    tempo = transform.get("tempo", {})
    if isinstance(tempo, dict) and "target_bpm" in tempo:
        return float(tempo["target_bpm"])
    if preserved and "tempo_bpm" in preserved:
        preserved_tempo = preserved["tempo_bpm"]
        if isinstance(preserved_tempo, dict):
            for key in ("target_bpm", "target", "bpm", "value"):
                if key in preserved_tempo:
                    return float(preserved_tempo[key])
        else:
            return float(preserved_tempo)
    return 90.0


def get_song_id(spec: dict[str, Any], preserved: dict[str, Any] | None = None) -> str:
    meta = spec.get("metadata", {})
    if "input_song_id" in meta:
        return meta["input_song_id"]
    if preserved and "input_song_id" in preserved:
        return preserved["input_song_id"]
    raise ValueError("arrangement spec missing metadata.input_song_id")


def _progression_entries(block: dict[str, Any] | None, *keys: str) -> list[dict[str, Any]]:
    if not block:
        return []
    for key in keys:
        entries = block.get(key)
        if isinstance(entries, list):
            return [e for e in entries if isinstance(e, dict)]
    return []


def bar_chord_overrides(
    transform: dict[str, Any],
    preserved: dict[str, Any] | None = None,
) -> dict[int, str]:
    """
    Per-bar chord overrides applied on top of POP909 chord_midi.txt.

    Precedence (later wins): preserved.original_chord_progression
      → transformations.chord_progression_preview
      → transformations.chord_progression
    """
    overrides: dict[int, str] = {}
    for item in _progression_entries(preserved, "original_chord_progression"):
        bar = int(item.get("bar", 0))
        if bar > 0:
            overrides[bar] = item.get("chord", "N")
    for item in _progression_entries(
        transform, "chord_progression_preview", "chord_progression_by_bar"
    ):
        bar = int(item.get("bar", 0))
        if bar > 0:
            overrides[bar] = item.get("chord", "N")
    for item in _progression_entries(
        transform, "chord_progression", "chord_progression_by_bar"
    ):
        bar = int(item.get("bar", 0))
        if bar > 0:
            overrides[bar] = item.get("chord", "N")
    return overrides


def summarize_active_spec(
    spec: dict[str, Any],
    variant: str = "primary",
    style_definitions_path: str | None = None,
) -> dict[str, Any]:
    """Human-readable snapshot of fields that actually drive MIDI generation."""
    from .style_render import build_render_plan

    preserved = get_preserved(spec)
    transform = get_transformations(spec, variant=variant)
    overrides = bar_chord_overrides(transform, preserved)
    spec_tempo = get_tempo_bpm(transform, preserved)
    plan = build_render_plan(transform, spec_tempo, spec_tempo, style_definitions_path)
    return {
        "variant": variant,
        "spec_shape": (
            "dual_output" if "primary_spec" in spec else "converged"
        ),
        "tempo_bpm": plan.tempo_bpm,
        "rhythm_pattern": plan.rhythm_pattern,
        "rhythm_grid": plan.rhythm_cfg.get("grid"),
        "rhythm_swing": plan.rhythm_cfg.get("swing_ratio"),
        "voicing_style": plan.voicing_style,
        "voicing_velocity": plan.voicing_cfg.get("velocity"),
        "texture_density": plan.texture_density,
        "instrumentation": plan.instrumentation,
        "melody_program": plan.melody.program_name,
        "melody_quantize_strength": plan.melody.quantize_strength,
        "melody_duration_ratio": plan.melody.duration_ratio,
        "include_drums": plan.include_drums,
        "include_pad": plan.include_pad,
        "chord_override_bars": len(overrides),
        "chord_override_preview": dict(sorted(overrides.items())[:8]),
        "ignored_fields": [
            "natural_language_summary",
            "metadata (except input_song_id)",
            "instrumentation.ambient (synthesis not implemented)",
        ],
        "wav_policy": "always trimmed to data/wav_renders/<song_id>.wav length (30s)",
    }
