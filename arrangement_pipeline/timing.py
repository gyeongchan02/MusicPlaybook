"""POP909 beat grid and tempo-aware time mapping."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BeatGrid:
    """Beat-aligned grid from beat_midi.txt (all beats + downbeats)."""

    beat_times: tuple[float, ...]
    downbeat_times: tuple[float, ...]
    source_tempo_bpm: float

    @property
    def origin(self) -> float:
        return self.downbeat_times[0] if self.downbeat_times else 0.0

    @property
    def num_bars(self) -> int:
        return len(self.downbeat_times)

    def bar_bounds(self, bar_index: int) -> tuple[float, float]:
        """bar_index is 0-based."""
        if bar_index < 0 or bar_index >= len(self.downbeat_times):
            bar_sec = 60.0 / self.source_tempo_bpm * 4.0
            start = self.origin + bar_index * bar_sec
            return start, start + bar_sec
        start = self.downbeat_times[bar_index]
        if bar_index + 1 < len(self.downbeat_times):
            end = self.downbeat_times[bar_index + 1]
        else:
            end = start + 60.0 / self.source_tempo_bpm * 4.0
        return start, end

    def beats_in_bar(self, bar_index: int) -> list[float]:
        """Quarter-beat times in source seconds for one bar."""
        start, end = self.bar_bounds(bar_index)
        beats = [t for t in self.beat_times if start <= t < end - 1e-9]
        if not beats or beats[0] > start + 1e-6:
            beats = [start] + beats
        return beats

    def map_time(self, time_sec: float, target_tempo_bpm: float) -> float:
        """Scale musical time around the first downbeat (preserves pick-up/anacrusis)."""
        if self.source_tempo_bpm <= 0:
            return time_sec
        scale = target_tempo_bpm / self.source_tempo_bpm
        if abs(scale - 1.0) < 1e-6:
            return time_sec
        return self.origin + (time_sec - self.origin) * scale

    def step_times_for_bar(
        self,
        bar_index: int,
        target_tempo_bpm: float,
        n_steps: int = 16,
        swing_ratio: float = 0.66,
    ) -> list[float]:
        """
        Sixteenth-note grid anchored to POP909 beat times (not a synthetic grid).

        Subdivides each inter-beat interval with swing.
        """
        beats = self.beats_in_bar(bar_index)
        if len(beats) < 2:
            start, end = self.bar_bounds(bar_index)
            beats = [start, end]

        intervals = len(beats) - 1
        steps_per_interval = max(1, n_steps // intervals)
        src_times: list[float] = []

        for i in range(intervals):
            a, b = beats[i], beats[i + 1]
            src_times.extend(
                _swung_times_in_interval(a, b, steps_per_interval, swing_ratio)
            )

        # Pad or trim to n_steps
        if len(src_times) < n_steps and src_times:
            last = src_times[-1]
            step = (beats[-1] - beats[0]) / n_steps
            while len(src_times) < n_steps:
                last += step
                src_times.append(last)
        src_times = src_times[:n_steps]

        return [self.map_time(t, target_tempo_bpm) for t in src_times]


def _swung_times_in_interval(
    start: float,
    end: float,
    n_steps: int,
    swing_ratio: float,
) -> list[float]:
    if n_steps <= 0:
        return []
    if n_steps == 1:
        return [start]
    duration = end - start
    n_pairs = max(1, n_steps // 2)
    pair_dur = duration / n_pairs
    long_dur = pair_dur * swing_ratio
    short_dur = pair_dur - long_dur
    times: list[float] = []
    t = start
    for i in range(n_steps):
        times.append(t)
        if i % 2 == 0:
            t += long_dur
        else:
            t += short_dur
    return times


def parse_beat_file(beat_txt: Path, source_tempo_bpm: float) -> BeatGrid:
    """
    Parse POP909 beat_midi.txt.

    Columns: time_sec, beat_index_in_song, beat_position_in_bar (1.0 = downbeat).
    Downbeats use the **third column** (position-in-bar == 1.0), not the second.
    """
    all_beats: list[float] = []
    downbeats: list[float] = []
    if beat_txt.exists():
        with open(beat_txt, encoding="utf-8") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) < 2:
                    continue
                try:
                    t = float(parts[0])
                except ValueError:
                    continue
                all_beats.append(t)
                if len(parts) >= 3:
                    try:
                        in_bar = float(parts[2])
                    except ValueError:
                        in_bar = -1.0
                else:
                    in_bar = float(parts[1])
                if abs(in_bar - 1.0) < 1e-6:
                    downbeats.append(t)
    if not downbeats:
        bar_sec = 60.0 / source_tempo_bpm * 4.0
        downbeats = [i * bar_sec for i in range(65)]
        all_beats = downbeats
    return BeatGrid(
        beat_times=tuple(all_beats),
        downbeat_times=tuple(downbeats),
        source_tempo_bpm=source_tempo_bpm,
    )


def lookup_source_tempo(repo_root: Path, song_id: str, fallback: float = 80.0) -> float:
    """Read canonical tempo from artifacts/pop909_sample.csv."""
    csv_path = Path(repo_root) / "artifacts" / "pop909_sample.csv"
    if not csv_path.exists():
        return fallback
    with open(csv_path, encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("song_id") == song_id:
                try:
                    return float(row["tempo"])
                except (KeyError, ValueError):
                    break
    return fallback


def beat_file_path(chord_path: Path) -> Path:
    return chord_path.parent / "beat_midi.txt"
