"""Build render settings directly from arrangement spec transformations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .melody_treatment import MelodyRenderSettings, derive_melody_treatment
from .style_registry import get_instrument, get_rhythm_pattern, get_voicing_style


@dataclass(frozen=True)
class RenderPlan:
    tempo_bpm: float
    rhythm_pattern: str
    rhythm_cfg: dict[str, Any]
    voicing_style: str
    voicing_cfg: dict[str, Any]
    texture_density: float
    instrumentation: dict[str, Any]
    melody: MelodyRenderSettings
    include_drums: bool
    include_pad: bool
    style_family: str


def resolve_render_tempo(source_bpm: float, spec_bpm: float) -> float:
    if spec_bpm > 0:
        return spec_bpm
    return source_bpm if source_bpm > 0 else 90.0


def _style_family(rhythm_pattern: str) -> str:
    name = rhythm_pattern.lower()
    if name.startswith("jazz"):
        return "jazz"
    if name.startswith("lofi"):
        return "lofi"
    if name.startswith("ballad"):
        return "ballad"
    if name.startswith("bossa"):
        return "bossa"
    return "default"


def build_render_plan(
    transform: dict[str, Any],
    spec_tempo_bpm: float,
    source_tempo_bpm: float,
    style_definitions_path: str | None = None,
) -> RenderPlan:
    """Map spec transformations + style_definitions.json to concrete render knobs."""
    from .style_registry import load_style_definitions

    defs = load_style_definitions(style_definitions_path)
    rhythm_pattern = str(transform.get("rhythm_pattern", "lofi_swung_16th"))
    rhythm_cfg = get_rhythm_pattern(rhythm_pattern, defs)
    voicing_style = str(transform.get("voicing_style", "spread_with_9ths"))
    voicing_cfg = get_voicing_style(voicing_style, defs)
    texture_density = float(transform.get("texture_density", 0.4))
    instrumentation = dict(transform.get("instrumentation") or {})

    grid = rhythm_cfg.get("grid", "16th")
    swing = float(rhythm_cfg.get("swing_ratio", 0.66))
    family = _style_family(rhythm_pattern)

    voicing_vel = int(voicing_cfg.get("velocity", rhythm_cfg.get("comp_velocity", 60)))
    lead_program = "Acoustic Grand Piano"
    if instrumentation.get("lead"):
        lead_program = get_instrument(instrumentation["lead"], defs)["gm_program"]

    melody = derive_melody_treatment(
        family=family,
        rhythm_cfg=rhythm_cfg,
        voicing_style=voicing_style,
        texture_density=texture_density,
        instrumentation=instrumentation,
        lead_program=lead_program,
    )

    include_drums = bool(instrumentation.get("percussion"))
    include_pad = family in ("lofi", "ballad")

    return RenderPlan(
        tempo_bpm=resolve_render_tempo(source_tempo_bpm, spec_tempo_bpm),
        rhythm_pattern=rhythm_pattern,
        rhythm_cfg=rhythm_cfg,
        voicing_style=voicing_style,
        voicing_cfg=voicing_cfg,
        texture_density=texture_density,
        instrumentation=instrumentation,
        melody=melody,
        include_drums=include_drums,
        include_pad=include_pad,
        style_family=family,
    )


def style_family(rhythm_pattern: str) -> str:
    return _style_family(rhythm_pattern)
