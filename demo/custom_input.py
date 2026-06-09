"""Prepare user-uploaded MIDI/WAV for the arrangement pipeline."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pretty_midi
import soundfile as sf

from arrangement_pipeline.fluidsynth_render import (
    align_audio_length,
    normalize_peak,
    render_midi_with_fluidsynth,
    synthesize_midi_audio,
)
from arrangement_pipeline.pop909 import estimate_num_bars, load_pop909_midi, resolve_tracks

from .paths import REPO_ROOT, load_style_profiles


CUSTOM_ROOT = REPO_ROOT / "outputs" / "demo_custom"
MAX_REFERENCE_SEC = 30.0


@dataclass
class MidiInspection:
    track_labels: list[str]
    melody_track_index: int
    source_tempo_bpm: float
    num_bars: int
    duration_sec: float
    note_count: int


@dataclass
class CustomInputAssets:
    session_id: str
    song_id: str
    work_dir: Path
    source_midi: Path
    normalized_midi: Path
    chord_file: Path
    beat_file: Path
    reference_wav: Path
    source_tempo_bpm: float
    num_bars: int
    melody_track_index: int


def _slugify(name: str) -> str:
    stem = Path(name).stem
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", stem).strip("_")
    return slug[:40] or "upload"


def list_midi_tracks(midi_path: Path) -> list[str]:
    pm = load_pop909_midi(midi_path)
    labels: list[str] = []
    for idx, inst in enumerate(pm.instruments):
        role = "drums" if inst.is_drum else "melody"
        name = inst.name or f"track_{idx}"
        labels.append(f"[{idx}] {name} ({role}, {len(inst.notes)} notes)")
    return labels


def inspect_midi(midi_path: Path, melody_track_index: int | None = None) -> MidiInspection:
    pm = load_pop909_midi(midi_path)
    labels = list_midi_tracks(midi_path)

    non_drum = [
        i
        for i, inst in enumerate(pm.instruments)
        if not inst.is_drum and inst.notes
    ]
    if not non_drum:
        raise ValueError("No melody notes found in MIDI (drums only or empty).")

    if melody_track_index is None:
        tracks = resolve_tracks(pm)
        melody_inst = tracks.get("melody")
        if melody_inst is not None:
            melody_track_index = pm.instruments.index(melody_inst)
        else:
            melody_track_index = non_drum[0]
    elif melody_track_index >= len(pm.instruments):
        raise ValueError(f"Track index {melody_track_index} is out of range.")

    melody = pm.instruments[melody_track_index]
    if melody.is_drum or not melody.notes:
        raise ValueError("Selected track has no melody notes.")

    tempo = float(pm.estimate_tempo() or 120.0)
    if tempo <= 0 or tempo > 300:
        tempo = 120.0

    return MidiInspection(
        track_labels=labels,
        melody_track_index=melody_track_index,
        source_tempo_bpm=tempo,
        num_bars=estimate_num_bars(pm),
        duration_sec=float(pm.get_end_time()),
        note_count=len(melody.notes),
    )


def normalize_custom_midi(
    src_path: Path,
    out_path: Path,
    melody_track_index: int,
) -> Path:
    """Write a POP909-compatible MIDI with a single MELODY track."""
    pm = load_pop909_midi(src_path)
    if melody_track_index >= len(pm.instruments):
        raise ValueError(f"Invalid melody track index: {melody_track_index}")

    mel = pm.instruments[melody_track_index]
    if mel.is_drum or not mel.notes:
        raise ValueError("Selected track has no melody notes.")

    tempo = pm.estimate_tempo() or 120.0
    out_pm = pretty_midi.PrettyMIDI(initial_tempo=float(tempo))
    melody = pretty_midi.Instrument(
        program=mel.program,
        name="MELODY",
        is_drum=False,
    )
    melody.notes = list(mel.notes)
    out_pm.instruments.append(melody)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_pm.write(str(out_path))
    return out_path


def write_beat_file(path: Path, tempo_bpm: float, num_bars: int) -> Path:
    bar_sec = 60.0 / tempo_bpm * 4.0
    lines: list[str] = []
    for bar in range(num_bars):
        bar_start = bar * bar_sec
        for beat in range(4):
            t = bar_start + beat * bar_sec / 4.0
            pos = 1.0 if beat == 0 else float(beat + 1)
            lines.append(f"{t:.6f} {bar * 4 + beat + 1} {pos:.1f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_chord_file(
    path: Path,
    tempo_bpm: float,
    num_bars: int,
    default_chord: str = "N",
) -> Path:
    bar_sec = 60.0 / tempo_bpm * 4.0
    lines = [
        f"{i * bar_sec:.6f} {(i + 1) * bar_sec:.6f} {default_chord}"
        for i in range(num_bars)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def save_chord_upload(upload_bytes: bytes, path: Path) -> Path:
    path.write_bytes(upload_bytes)
    return path


def make_reference_wav_from_midi(midi_path: Path, wav_path: Path) -> Path:
    """Render uploaded MIDI to a reference clip (max 30s) for length alignment."""
    import numpy as np

    from arrangement_pipeline.fluidsynth_render import find_soundfont

    pm = load_pop909_midi(midi_path)
    duration = min(float(pm.get_end_time()), MAX_REFERENCE_SEC)
    sample_rate = 44100
    audio = synthesize_midi_audio(midi_path, sample_rate, find_soundfont())
    target_frames = int(duration * sample_rate)
    audio = align_audio_length(audio, target_frames)
    audio = normalize_peak(audio)
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(wav_path), audio, sample_rate)
    return wav_path


def save_reference_wav_upload(upload_bytes: bytes, path: Path) -> Path:
    """Save user WAV and trim/pad to max 30s at 44100 Hz."""
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(upload_bytes)
    audio, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)
    max_frames = int(MAX_REFERENCE_SEC * 44100)
    if sr != 44100:
        import numpy as np

        duration = len(audio) / sr
        src_t = np.linspace(0, duration, len(audio), endpoint=False)
        dst_n = int(duration * 44100)
        dst_t = np.linspace(0, duration, dst_n, endpoint=False)
        audio = np.interp(dst_t, src_t, audio).astype(np.float32)
        sr = 44100
    audio = align_audio_length(audio, min(len(audio), max_frames))
    audio = normalize_peak(audio)
    sf.write(str(path), audio, sr)
    return path


def build_auto_spec(
    *,
    song_id: str,
    target_style: str,
    source_tempo_bpm: float,
    num_bars: int,
    key: str = "C",
    mode: str = "major",
    default_chord: str = "N",
    texture_density: float | None = None,
    target_tempo_bpm: float | None = None,
    rhythm_pattern: str | None = None,
    voicing_style: str | None = None,
) -> dict[str, Any]:
    profiles = load_style_profiles()
    if target_style not in profiles:
        raise ValueError(f"Unknown style: {target_style}")

    profile = profiles[target_style]
    tempo_lo, tempo_hi = profile["tempo_range_bpm"]
    if target_tempo_bpm is None:
        target_tempo_bpm = max(tempo_lo, min(tempo_hi, source_tempo_bpm))
    else:
        target_tempo_bpm = max(tempo_lo, min(tempo_hi, target_tempo_bpm))

    rhythm = rhythm_pattern or profile["rhythm_pattern_options"][0]
    voicing = voicing_style or profile["voicing_style_options"][0]
    inst = dict(profile["instrumentation_options"][0])
    density_range = profile["texture_density_range"]
    density = texture_density
    if density is None:
        density = (density_range[0] + density_range[1]) / 2.0

    preview_bars = min(num_bars, 16)
    chord_prog = [{"bar": b, "chord": default_chord} for b in range(1, preview_bars + 1)]

    return {
        "metadata": {
            "input_song_id": song_id,
            "target_style": target_style,
            "system_version": "demo_custom_upload",
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "termination_status": "user_upload",
            "rounds_used": 0,
        },
        "preserved": {
            "melody_source": "upload.MELODY_track",
            "key": f"{key} {mode}",
            "num_bars": num_bars,
            "tempo_bpm": source_tempo_bpm,
        },
        "transformations": {
            "chord_progression": chord_prog,
            "rhythm_pattern": rhythm,
            "tempo_bpm": target_tempo_bpm,
            "voicing_style": voicing,
            "texture_density": round(float(density), 2),
            "instrumentation": inst,
        },
        "natural_language_summary": (
            f"User-uploaded melody arranged in {target_style} style "
            f"at {target_tempo_bpm:.0f} BPM."
        ),
    }


def prepare_custom_assets(
    *,
    midi_bytes: bytes,
    midi_filename: str,
    wav_bytes: bytes | None = None,
    chord_bytes: bytes | None = None,
    melody_track_index: int | None = None,
    source_tempo_bpm: float | None = None,
    num_bars: int | None = None,
    default_chord: str = "N",
) -> CustomInputAssets:
    session_id = uuid.uuid4().hex[:12]
    slug = _slugify(midi_filename)
    song_id = f"CUSTOM_{slug}"
    work_dir = CUSTOM_ROOT / f"{session_id}_{slug}"
    work_dir.mkdir(parents=True, exist_ok=True)

    source_midi = work_dir / "input.mid"
    source_midi.write_bytes(midi_bytes)

    inspection = inspect_midi(source_midi, melody_track_index)
    track_idx = inspection.melody_track_index
    tempo = source_tempo_bpm or inspection.source_tempo_bpm
    bars = num_bars or inspection.num_bars

    normalized = work_dir / "normalized.mid"
    normalize_custom_midi(source_midi, normalized, track_idx)

    beat_file = write_beat_file(work_dir / "beat_midi.txt", tempo, bars)
    chord_file = work_dir / "chord_midi.txt"
    if chord_bytes:
        save_chord_upload(chord_bytes, chord_file)
    else:
        write_chord_file(chord_file, tempo, bars, default_chord)

    reference_wav = work_dir / "reference.wav"
    if wav_bytes:
        save_reference_wav_upload(wav_bytes, reference_wav)
    else:
        make_reference_wav_from_midi(normalized, reference_wav)

    return CustomInputAssets(
        session_id=session_id,
        song_id=song_id,
        work_dir=work_dir,
        source_midi=source_midi,
        normalized_midi=normalized,
        chord_file=chord_file,
        beat_file=beat_file,
        reference_wav=reference_wav,
        source_tempo_bpm=tempo,
        num_bars=bars,
        melody_track_index=track_idx,
    )
