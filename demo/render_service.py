"""Arrangement rendering for the Streamlit demo."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from arrangement_pipeline.fluidsynth_render import render_midi_with_fluidsynth
from arrangement_pipeline.pipeline import ArrangementPipeline
from arrangement_pipeline.reference_wav import read_reference_duration, reference_wav_path

from .paths import REPO_ROOT

# -------------------------------------------------------------------
# Known-valid values the pipeline will accept without raising KeyError
# -------------------------------------------------------------------
_VALID_INSTRUMENTS = {
    "acoustic_bass", "acoustic_piano", "bossa_shaker_brush", "clavinet_lead",
    "concert_grand_piano", "electric_bass_finger", "fretless_bass", "funk_drum_kit",
    "gospel_kit", "hammond_organ", "jazz_brushed_kit", "lofi_brushed_kit", "nylon_guitar",
    "orchestral_double_bass", "pop_light_kit", "rhodes_electric_piano", "soul_drums",
    "steel_string_guitar", "upright_bass", "walking_upright_bass",
}
_DENSITY_TEXT = {"low": 0.3, "medium": 0.5, "med": 0.5, "high": 0.7, "moderate": 0.5}

_VALID_RHYTHM_PATTERNS = {
    "ballad_arpeggio", "ballad_sustained_pads", "bossa_clave",
    "funk_straight_16th", "funk_syncopated_16th", "gospel_half_time",
    "gospel_shuffle_8th", "jazz_straight_4th", "jazz_swing_8th",
    "lofi_straight_8th", "lofi_swung_16th", "pop_arpeggio_16th",
    "pop_strum_8th", "samba_lite", "soul_laid_back_16th", "soul_straight_8th",
}
_VALID_VOICING_STYLES = {
    "block_chords", "bossa_guitar_voicing", "capo_style_tight", "drop2_voicing",
    "funk_sparse_7ths", "funk_stabs_tight", "gospel_hammond_blocks",
    "gospel_rich_choir_spread", "neo_soul_extensions", "open_triad_spread",
    "open_voicing_wide_spread", "rootless_LH_voicing", "shell_voicing",
    "soul_compact_voicing", "spread_with_9ths",
}


def _clean_chord(raw: str) -> str:
    return raw.split("(")[0].strip() or "N"


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"(\d+\.?\d*)", str(value))
    return float(m.group(1)) if m else None


def _deep_extract(obj: Any, result: dict[str, Any], depth: int = 0) -> None:
    """Recursively walk any JSON structure looking for arrangement fields."""
    if depth > 6:
        return
    if isinstance(obj, list):
        for item in obj:
            _deep_extract(item, result, depth + 1)
        return
    if not isinstance(obj, dict):
        return

    for key, val in obj.items():
        key_lower = key.lower()

        if "tempo" in key_lower or "bpm" in key_lower:
            f = _parse_float(val)
            if f and 40 <= f <= 300:
                result.setdefault("tempo_bpm", f)

        if isinstance(val, str) and val in _VALID_RHYTHM_PATTERNS:
            result.setdefault("rhythm_pattern", val)

        if isinstance(val, str):
            if val in _VALID_VOICING_STYLES:
                result.setdefault("voicing_style", val)
            else:
                for vs in _VALID_VOICING_STYLES:
                    if vs in val:
                        result.setdefault("voicing_style", vs)
                        break

        if "density" in key_lower:
            if isinstance(val, str) and val.lower() in _DENSITY_TEXT:
                result.setdefault("texture_density", _DENSITY_TEXT[val.lower()])
            else:
                f = _parse_float(val)
                if f is not None and 0.0 < f <= 1.0:
                    result.setdefault("texture_density", f)

        if ("drum" in key_lower or "percussion" in key_lower) and val:
            if isinstance(val, str) and val in _VALID_INSTRUMENTS:
                result.setdefault("_percussion_name", val)
            elif isinstance(val, dict):
                opts = val.get("instrument_options", [])
                if isinstance(opts, list) and opts and opts[0] in _VALID_INSTRUMENTS:
                    result.setdefault("_percussion_name", opts[0])
                else:
                    result.setdefault("_has_drums", True)
            else:
                result.setdefault("_has_drums", True)

        if isinstance(val, list) and val and isinstance(val[0], dict):
            if "chord" in val[0] and "bar" in val[0]:
                cleaned = [
                    {"bar": int(e["bar"]), "chord": _clean_chord(e.get("chord", "N"))}
                    for e in val
                    if isinstance(e, dict) and e.get("bar")
                ]
                if cleaned:
                    result.setdefault("chord_progression", cleaned)

        if isinstance(val, (dict, list)):
            _deep_extract(val, result, depth + 1)


def _promote_drums(t: dict[str, Any]) -> None:
    """Move _has_drums/_percussion_name → instrumentation.percussion."""
    perc_name = t.pop("_percussion_name", None)
    has_drums = t.pop("_has_drums", None)
    if perc_name or has_drums:
        inst = t.get("instrumentation")
        if not isinstance(inst, dict):
            t["instrumentation"] = {}
            inst = t["instrumentation"]
        inst.setdefault("percussion", perc_name or "soul_drums")


def _extract_transformations_from_schema(spec: dict[str, Any]) -> dict[str, Any]:
    t = spec.get("transformations")
    if isinstance(t, dict) and t:
        return t

    result: dict[str, Any] = {}

    if isinstance(t, list):
        _deep_extract(t, result)

    _deep_extract(spec, result)

    for wrapper_key in ("primary_spec", "alternative_spec"):
        inner = spec.get(wrapper_key, {})
        if isinstance(inner, dict):
            inner_t = inner.get("transformations")
            if isinstance(inner_t, dict) and inner_t:
                for k, v in inner_t.items():
                    result.setdefault(k, v)
            else:
                _deep_extract(inner, result)

    return result


def _normalize_spec(spec: dict[str, Any], song_id: str | None = None) -> dict[str, Any]:
    spec = copy.deepcopy(spec)

    # 1. metadata.input_song_id
    if not isinstance(spec.get("metadata"), dict):
        spec["metadata"] = {}
    if not spec["metadata"].get("input_song_id"):
        sid = (
            spec.get("song_id")
            or (spec.get("export_metadata") or {}).get("song_id")
            or song_id
        )
        if sid:
            spec["metadata"]["input_song_id"] = sid

    # 2. Top-level transformations
    t = spec.get("transformations")
    if not isinstance(t, dict):
        spec["transformations"] = _extract_transformations_from_schema(spec)
    _promote_drums(spec["transformations"])

    # 3. primary_spec.transformations
    if isinstance(spec.get("primary_spec"), dict):
        pt = spec["primary_spec"].get("transformations")
        if not isinstance(pt, dict):
            spec["primary_spec"]["transformations"] = _extract_transformations_from_schema(
                spec["primary_spec"]
            )
        _promote_drums(spec["primary_spec"]["transformations"])

    return spec


def render_arrangement(
    spec_path: Path,
    out_dir: Path,
    *,
    song_id: str | None = None,
    variant: str = "primary",
    reference_wav: Path | None = None,
    source_midi: Path | None = None,
    chord_annotation: Path | None = None,
    beat_annotation: Path | None = None,
    source_tempo_bpm: float | None = None,
    include_drums: bool = True,
) -> tuple[Path, Path]:
    """Render arranged.mid + arranged.wav from a spec JSON.

    Returns (midi_path, wav_path).
    """
    from arrangement_pipeline.spec_loader import get_preserved, get_song_id, load_spec

    spec = load_spec(spec_path)
    spec = _normalize_spec(spec, song_id=song_id)

    spec_path = Path(spec_path)
    spec_path.write_text(
        json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    preserved = get_preserved(spec)
    if reference_wav is None:
        sid = get_song_id(spec, preserved)
        ref_wav = reference_wav_path(REPO_ROOT, sid)
    else:
        ref_wav = Path(reference_wav)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pipeline = ArrangementPipeline(repo_root=REPO_ROOT)
    result = pipeline.run(
        spec_path=spec_path,
        out_dir=out_dir,
        source_midi=source_midi,
        chord_annotation=chord_annotation,
        beat_annotation=beat_annotation,
        variant=variant,
        render_wav=False,
        include_drums=include_drums,
        source_tempo_bpm=source_tempo_bpm,
    )

    wav_out = out_dir / "arranged.wav"
    render_midi_with_fluidsynth(
        midi_path=result.midi_path,
        wav_path=wav_out,
        reference_wav_path=ref_wav,
    )

    import soundfile as sf

    ref_frames, ref_sr, _ = read_reference_duration(ref_wav)
    out_info = sf.info(str(wav_out))
    if out_info.frames != ref_frames or out_info.samplerate != ref_sr:
        raise RuntimeError(
            f"Length mismatch: arranged {out_info.frames}@{out_info.samplerate} "
            f"vs reference {ref_frames}@{ref_sr}"
        )

    return result.midi_path, wav_out
