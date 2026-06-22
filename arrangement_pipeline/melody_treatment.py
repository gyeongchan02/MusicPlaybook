"""Style-driven melody shaping derived from existing spec transformations."""

from __future__ import annotations

from dataclasses import dataclass

import pretty_midi


@dataclass(frozen=True)
class MelodyRenderSettings:
    program_name: str
    velocity_cap: int
    velocity_floor: int
    quantize_steps: int
    swing_ratio: float
    quantize_strength: float
    duration_ratio: float = 1.0
    velocity_swell: float = 0.1


_FAMILY_MELODY_PROGRAM: dict[str, str] = {
    "jazz": "Electric Guitar (jazz)",
    "lofi": "Electric Piano 2",
    "ballad": "Acoustic Grand Piano",
    "bossa": "Acoustic Guitar (nylon)",
}

_VOICING_DURATION: dict[str, float] = {
    "shell_voicing": 0.9,
    "drop2_voicing": 0.92,
    "spread_with_9ths": 1.04,
    "rootless_LH_voicing": 0.96,
    "open_voicing_wide_spread": 1.08,
}


def resolve_melody_program(
    family: str,
    instrumentation: dict,
    lead_fallback: str,
) -> str:
    if instrumentation.get("melody_lead"):
        from .style_registry import get_instrument, load_style_definitions

        return get_instrument(
            instrumentation["melody_lead"], load_style_definitions()
        )["gm_program"]
    if family in _FAMILY_MELODY_PROGRAM:
        return _FAMILY_MELODY_PROGRAM[family]
    return lead_fallback


def derive_melody_treatment(
    family: str,
    rhythm_cfg: dict,
    voicing_style: str,
    texture_density: float,
    instrumentation: dict,
    lead_program: str,
) -> MelodyRenderSettings:
    """Map rhythm / voicing / density / instrumentation to melody render knobs."""
    grid = rhythm_cfg.get("grid", "16th")
    swing = float(rhythm_cfg.get("swing_ratio", 0.66))
    comp_vel = int(rhythm_cfg.get("comp_velocity", 58))

    if family == "jazz":
        quantize_strength = 0.48 + 0.12 * texture_density
        duration_ratio = _VOICING_DURATION.get(voicing_style, 0.9)
        melody_cap = max(78, min(108, comp_vel + int(22 * texture_density)))
    elif family == "lofi":
        quantize_strength = 0.38 + 0.14 * texture_density
        duration_ratio = _VOICING_DURATION.get(voicing_style, 1.06)
        melody_cap = max(74, min(104, comp_vel + int(28 * texture_density)))
    elif family == "ballad":
        quantize_strength = 0.32
        duration_ratio = 1.12
        melody_cap = 96
    else:
        quantize_strength = 0.42
        duration_ratio = 1.0
        melody_cap = 92

    melody_floor = max(56, melody_cap - 26)

    return MelodyRenderSettings(
        program_name=resolve_melody_program(family, instrumentation, lead_program),
        velocity_cap=melody_cap,
        velocity_floor=melody_floor,
        quantize_steps=16 if grid == "16th" else 8,
        swing_ratio=swing,
        quantize_strength=min(0.72, quantize_strength),
        duration_ratio=duration_ratio,
        velocity_swell=0.14 if family == "jazz" else 0.1,
    )


def apply_melody_treatment(
    notes: list[pretty_midi.Note],
    treatment: MelodyRenderSettings,
    tempo_bpm: float,
) -> None:
    """
    Post-quantize melody shaping: duration, velocity accents, light ornaments.

    Pitch content is unchanged — only articulation and expression vary by style.
    """
    if not notes:
        return

    beat_sec = 60.0 / tempo_bpm
    bar_sec = beat_sec * 4.0
    sorted_notes = sorted(notes, key=lambda n: (n.start, n.pitch))
    ornaments: list[pretty_midi.Note] = []

    for idx, note in enumerate(sorted_notes):
        original_dur = max(0.06, note.end - note.start)
        note.end = note.start + max(0.06, original_dur * treatment.duration_ratio)

        bar_phase = (note.start % bar_sec) / bar_sec if bar_sec > 0 else 0.0
        on_downbeat = bar_phase < 0.06 or abs(bar_phase - 0.5) < 0.06
        accent = int(treatment.velocity_swell * 127) if on_downbeat else 0
        note.velocity = max(
            treatment.velocity_floor,
            min(127, int(note.velocity * (0.92 + 0.08 * treatment.quantize_strength) + accent)),
        )
        note.velocity = min(treatment.velocity_cap, note.velocity)

        prev = sorted_notes[idx - 1] if idx > 0 else None
        gap = note.start - prev.end if prev else 999.0
        long_note = original_dur > beat_sec * 0.55
        if (
            prev is not None
            and gap > beat_sec * 0.12
            and long_note
            and treatment.duration_ratio < 0.98
        ):
            grace_start = max(0.0, note.start - beat_sec * 0.07)
            grace_end = note.start - 0.01
            if grace_end > grace_start:
                ornaments.append(
                    pretty_midi.Note(
                        velocity=max(treatment.velocity_floor, note.velocity - 18),
                        pitch=max(40, note.pitch - 1),
                        start=grace_start,
                        end=grace_end,
                    )
                )

    notes.extend(ornaments)
    notes.sort(key=lambda n: (n.start, n.pitch))
