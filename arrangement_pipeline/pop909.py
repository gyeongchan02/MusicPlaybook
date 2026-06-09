"""POP909 MIDI utilities: track resolution and chord annotation I/O."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pretty_midi


@dataclass(frozen=True)
class ChordSegment:
    start: float
    end: float
    symbol: str


def resolve_tracks(pm: pretty_midi.PrettyMIDI) -> dict[str, pretty_midi.Instrument | None]:
    """Return melody / bridge / piano instruments (POP909 naming convention)."""
    out: dict[str, pretty_midi.Instrument | None] = {
        "melody": None,
        "bridge": None,
        "piano": None,
    }
    for inst in pm.instruments:
        name = (inst.name or "").lower()
        if "melody" in name and out["melody"] is None:
            out["melody"] = inst
        elif "bridge" in name and out["bridge"] is None:
            out["bridge"] = inst
        elif "piano" in name and out["piano"] is None:
            out["piano"] = inst
    for idx, role in enumerate(["melody", "bridge", "piano"]):
        if out[role] is None and idx < len(pm.instruments):
            out[role] = pm.instruments[idx]
    return out


def load_pop909_midi(path: Path) -> pretty_midi.PrettyMIDI:
    return pretty_midi.PrettyMIDI(str(path))


def parse_chord_file(chord_txt: Path) -> list[ChordSegment]:
    segments: list[ChordSegment] = []
    if not chord_txt.exists():
        return segments
    with open(chord_txt, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                start = float(parts[0])
                end = float(parts[1])
            except ValueError:
                continue
            symbol = " ".join(parts[2:])
            segments.append(ChordSegment(start=start, end=end, symbol=symbol))
    return segments


def pop909_song_dir(dataset_root: Path, song_id: str) -> Path:
    """Map POP909_026 → .../POP909/026."""
    numeric = song_id.replace("POP909_", "").lstrip("0") or "0"
    folder = numeric.zfill(3) if numeric.isdigit() else numeric
    return dataset_root / "POP909" / folder


def default_paths(repo_root: Path, song_id: str) -> tuple[Path, Path, Path]:
    song_dir = pop909_song_dir(repo_root / "data" / "POP909-Dataset", song_id)
    numeric = song_id.replace("POP909_", "").lstrip("0") or "0"
    folder = numeric.zfill(3) if numeric.isdigit() else numeric
    midi_path = song_dir / f"{folder}.mid"
    chord_path = song_dir / "chord_midi.txt"
    beat_path = song_dir / "beat_midi.txt"
    return midi_path, chord_path, beat_path


def estimate_num_bars(pm: pretty_midi.PrettyMIDI, beats_per_bar: int = 4) -> int:
    end_time = pm.get_end_time()
    tempo = pm.estimate_tempo()
    if tempo <= 0:
        tempo = 120.0
    bar_sec = 60.0 / tempo * beats_per_bar
    return max(1, int(round(end_time / bar_sec)))


def bar_starts(tempo_bpm: float, num_bars: int, beats_per_bar: int = 4) -> list[float]:
    bar_sec = 60.0 / tempo_bpm * beats_per_bar
    return [i * bar_sec for i in range(num_bars)]


def chord_at_time(segments: Iterable[ChordSegment], time_sec: float) -> str:
    for seg in segments:
        if seg.start <= time_sec < seg.end:
            return seg.symbol
    return "N"


def segments_for_bar(
    segments: list[ChordSegment],
    bar_start: float,
    bar_end: float,
) -> list[tuple[float, float, str]]:
    """Slice chord segments overlapping [bar_start, bar_end)."""
    out: list[tuple[float, float, str]] = []
    for seg in segments:
        if seg.end <= bar_start or seg.start >= bar_end:
            continue
        out.append(
            (
                max(seg.start, bar_start),
                min(seg.end, bar_end),
                seg.symbol,
            )
        )
    if not out:
        out.append((bar_start, bar_end, "N"))
    return out
