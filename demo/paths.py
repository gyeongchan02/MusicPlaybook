"""Path helpers for the MusicPlaybook Streamlit demo."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = REPO_ROOT / "artifacts"
OUTPUTS_DIR = REPO_ROOT / "outputs"
DATA_DIR = REPO_ROOT / "data"


@dataclass(frozen=True)
class SongInfo:
    row_idx: int
    song_id: str
    key: str
    mode: str
    tempo: float
    num_bars: int
    duration: float

    @property
    def label(self) -> str:
        return (
            f"{self.song_id} — {self.key} {self.mode}, "
            f"{self.tempo:.0f} BPM, {self.num_bars} bars"
        )


@dataclass(frozen=True)
class CachedRun:
    run_dir: Path
    song_id: str
    target_style: str
    timestamp: str

    @property
    def label(self) -> str:
        return f"{self.timestamp} · {self.song_id} · {self.target_style}"


def style_slug(style: str) -> str:
    return style.replace(" ", "_")


def load_songs() -> list[SongInfo]:
    csv_path = ARTIFACTS_DIR / "pop909_sample.csv"
    if not csv_path.exists():
        return []
    songs: list[SongInfo] = []
    with open(csv_path, encoding="utf-8", newline="") as handle:
        for idx, row in enumerate(csv.DictReader(handle)):
            songs.append(
                SongInfo(
                    row_idx=idx,
                    song_id=str(row["song_id"]),
                    key=str(row["key"]),
                    mode=str(row["mode"]),
                    tempo=float(row["tempo"]),
                    num_bars=int(row["num_bars"]),
                    duration=float(row["duration"]),
                )
            )
    return songs


def load_style_profiles() -> dict[str, Any]:
    path = ARTIFACTS_DIR / "style_profiles.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_styles() -> list[str]:
    return list(load_style_profiles().keys()) or ["lo-fi chill"]


def _load_render_definitions() -> dict[str, Any]:
    path = REPO_ROOT / "arrangement_pipeline" / "style_definitions.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def style_render_status(style_name: str) -> tuple[bool, list[str]]:
    """
    Return (is_renderable, missing_items) by cross-checking style_profiles
    against arrangement_pipeline/style_definitions.json.
    """
    profiles = load_style_profiles()
    profile = profiles.get(style_name)
    if not profile:
        return False, [f"unknown style {style_name!r}"]

    defs = _load_render_definitions()
    rhythms = set(defs.get("rhythm_patterns", {}))
    voicings = set(defs.get("voicing_styles", {}))
    instruments = set(defs.get("instruments", {}))

    missing: list[str] = []
    for rhythm in profile.get("rhythm_pattern_options", []):
        if rhythm not in rhythms:
            missing.append(f"rhythm_pattern:{rhythm}")
    for voicing in profile.get("voicing_style_options", []):
        if voicing not in voicings:
            missing.append(f"voicing_style:{voicing}")
    for inst_set in profile.get("instrumentation_options", []):
        for role in ("lead", "bass", "percussion"):
            name = inst_set.get(role)
            if name and name not in instruments:
                missing.append(f"instrument:{name}")

    return len(missing) == 0, missing


def renderable_styles() -> set[str]:
    return {s for s in load_styles() if style_render_status(s)[0]}


_RUN_DIR_RE = re.compile(
    r"^run_(?P<ts>\d{8}_\d{6})_(?P<song_id>POP909_\d+)_(?P<style>.+)$"
)


def parse_run_dir_name(name: str) -> tuple[str, str, str] | None:
    match = _RUN_DIR_RE.match(name)
    if not match:
        return None
    style = match.group("style").replace("_", " ")
    return match.group("ts"), match.group("song_id"), style


def find_cached_runs(
    song_id: str | None = None,
    target_style: str | None = None,
) -> list[CachedRun]:
    if not OUTPUTS_DIR.exists():
        return []
    runs: list[CachedRun] = []
    for path in sorted(OUTPUTS_DIR.iterdir()):
        if not path.is_dir():
            continue
        parsed = parse_run_dir_name(path.name)
        if parsed is None:
            continue
        ts, sid, style = parsed
        if song_id and sid != song_id:
            continue
        if target_style and style != target_style:
            continue
        if not (path / "debate_log.json").exists():
            continue
        runs.append(
            CachedRun(
                run_dir=path,
                song_id=sid,
                target_style=style,
                timestamp=ts,
            )
        )
    return sorted(runs, key=lambda r: r.timestamp, reverse=True)


def reference_wav_path(song_id: str) -> Path | None:
    wav = DATA_DIR / "wav_renders" / f"{song_id}.wav"
    return wav if wav.exists() else None


def pop909_midi_path(song_id: str) -> Path | None:
    from arrangement_pipeline.pop909 import default_paths

    try:
        midi, _, _ = default_paths(REPO_ROOT, song_id)
    except Exception:
        return None
    return midi if midi.exists() else None


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_artifacts(run_dir: Path) -> dict[str, Path | None]:
    names = (
        "debate_log.json",
        "arrangement_spec.json",
        "baseline_spec.json",
        "debate_log.md",
        "cost_summary.json",
    )
    return {name: (run_dir / name if (run_dir / name).exists() else None) for name in names}


def arranged_output_dir(run_dir: Path, variant: str) -> Path:
    folder = {
        "debate": "arranged_debate",
        "baseline": "arranged_baseline",
    }[variant]
    return run_dir / folder
