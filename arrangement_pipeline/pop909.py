"""POP909 MIDI utilities: track resolution and chord annotation I/O."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pretty_midi

from .timing import BeatGrid


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


def _collapse_to_lead_line(notes: list[pretty_midi.Note]) -> list[pretty_midi.Note]:
    """Keep one note per onset (top pitch) so BRIDGE doublings don't muddy the lead."""
    grouped: dict[float, list[pretty_midi.Note]] = {}
    for note in notes:
        key = round(note.start, 2)
        grouped.setdefault(key, []).append(note)
    collapsed: list[pretty_midi.Note] = []
    for group in grouped.values():
        collapsed.append(max(group, key=lambda n: (n.pitch, n.velocity)))
    collapsed.sort(key=lambda n: (n.start, n.pitch))
    return collapsed


def _map_note(
    note: pretty_midi.Note,
    beat_grid: BeatGrid,
    tempo_bpm: float,
    velocity_cap: int,
    velocity_floor: int,
) -> pretty_midi.Note:
    vel = max(velocity_floor, min(velocity_cap, note.velocity))
    return pretty_midi.Note(
        velocity=vel,
        pitch=note.pitch,
        start=beat_grid.map_time(note.start, tempo_bpm),
        end=beat_grid.map_time(note.end, tempo_bpm),
    )


def build_preserved_melody(
    tracks: dict[str, pretty_midi.Instrument | None],
    beat_grid: BeatGrid,
    tempo_bpm: float,
    lead_program_name: str = "Vibraphone",
    velocity_cap: int = 118,
    velocity_floor: int = 92,
) -> pretty_midi.Instrument:
    """
    Preserve the audible lead line from POP909.

    MELODY is the primary vocal line, but many songs (e.g. POP909_064) carry the
    intro tune on BRIDGE until MELODY enters. Copy MELODY always, and fill the
    pre-entry gap with BRIDGE notes so the opening phrase is not lost.
    """
    melody_src = tracks.get("melody")
    if melody_src is None or not melody_src.notes:
        raise ValueError("No MELODY track notes to preserve")

    melody_first = min(note.start for note in melody_src.notes)
    melody_min_pitch = min(note.pitch for note in melody_src.notes)
    bridge_src = tracks.get("bridge")

    lead_program = pretty_midi.instrument_name_to_program(lead_program_name)
    melody = pretty_midi.Instrument(program=lead_program, name="MELODY")

    for note in melody_src.notes:
        melody.notes.append(
            _map_note(note, beat_grid, tempo_bpm, velocity_cap, velocity_floor)
        )

    if bridge_src is not None:
        bridge_cap = max(velocity_floor, velocity_cap - 6)
        for note in bridge_src.notes:
            if note.start >= melody_first - 1e-6:
                continue
            if note.pitch < melody_min_pitch - 2:
                continue
            melody.notes.append(
                _map_note(note, beat_grid, tempo_bpm, bridge_cap, velocity_floor - 4)
            )

    melody.notes = _collapse_to_lead_line(melody.notes)
    return melody


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
