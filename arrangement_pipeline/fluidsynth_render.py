"""FluidSynth-only MIDI → WAV rendering with reference-length alignment."""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pretty_midi
import soundfile as sf

from .reference_wav import read_reference_duration


def find_fluidsynth_binary() -> str:
    for name in ("fluidsynth",):
        found = shutil.which(name)
        if found:
            return found
    for path in ("/opt/homebrew/bin/fluidsynth", "/usr/local/bin/fluidsynth"):
        if os.path.exists(path):
            return path
    raise FileNotFoundError(
        "FluidSynth binary not found. Install with: brew install fluid-synth"
    )


def find_soundfont() -> Path:
    """Locate a GM soundfont (same search order as 01_data_retrieval)."""
    candidates = [
        "/usr/share/sounds/sf2/FluidR3_GM.sf2",
        "/usr/share/sounds/sf2/TimGM6mb.sf2",
        "/usr/share/soundfonts/FluidR3_GM.sf2",
        str(Path(__file__).resolve().parents[1] / "assets" / "FluidR3_GM.sf2"),
    ]
    bundled = Path(pretty_midi.__file__).resolve().parent / "TimGM6mb.sf2"
    if bundled.exists():
        candidates.insert(0, str(bundled))
    for pattern in (
        "/opt/homebrew/Cellar/fluid-synth/*/share/fluid-synth/sf2/*.sf2",
        "/opt/homebrew/share/soundfonts/*.sf2",
    ):
        for match in sorted(glob.glob(pattern)):
            candidates.append(match)
    for path in candidates:
        if path and os.path.exists(path):
            return Path(path)
    raise FileNotFoundError(
        "No GM soundfont found for FluidSynth. "
        "Install fluid-synth (brew install fluid-synth) or place FluidR3_GM.sf2 under assets/."
    )


def align_audio_length(
    audio: np.ndarray,
    target_frames: int,
) -> np.ndarray:
    """Trim or zero-pad to match reference wav frame count."""
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)
    audio = np.asarray(audio, dtype=np.float32)
    if len(audio) >= target_frames:
        return audio[:target_frames]
    return np.pad(audio, (0, target_frames - len(audio)))


def clip_midi_to_duration(
    midi_path: Path,
    duration_sec: float,
    out_path: Path | None = None,
) -> Path:
    """Write a temporary MIDI containing only [0, duration_sec) for faster rendering."""
    pm = pretty_midi.PrettyMIDI(str(midi_path))
    for inst in pm.instruments:
        clipped = []
        for note in inst.notes:
            if note.start >= duration_sec:
                continue
            note.end = min(note.end, duration_sec)
            if note.end > note.start:
                clipped.append(note)
        inst.notes = clipped
    target = out_path or midi_path.with_suffix(".clip.mid")
    pm.write(str(target))
    return target


def normalize_peak(audio: np.ndarray, target_peak: float = 0.8912509381) -> np.ndarray:
    """Peak-normalize to ~-1 dBFS (matches 01_data_retrieval notebook)."""
    peak = float(np.max(np.abs(audio))) + 1e-9
    return (audio / peak) * target_peak


def _render_via_fluidsynth_cli(
    midi_path: Path,
    sample_rate: int,
    soundfont: Path,
) -> np.ndarray:
    """Render full MIDI to a float32 mono array using the fluidsynth CLI."""
    fs_bin = find_fluidsynth_binary()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        # FluidSynth 2.x: options before soundfont/MIDI; -F is --fast-render
        cmd = [
            fs_bin,
            "-ni",
            "-q",
            "-r",
            str(sample_rate),
            "-F",
            str(tmp_path),
            str(soundfont),
            str(midi_path),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        audio, _ = sf.read(str(tmp_path), dtype="float32", always_2d=False)
        return audio
    finally:
        tmp_path.unlink(missing_ok=True)


def _render_via_pyfluidsynth(
    midi_path: Path,
    sample_rate: int,
    soundfont: Path,
) -> np.ndarray:
    pm = pretty_midi.PrettyMIDI(str(midi_path))
    return pm.fluidsynth(fs=sample_rate, sf2_path=str(soundfont))


def synthesize_midi_audio(
    midi_path: Path,
    sample_rate: int,
    soundfont: Path | None = None,
) -> np.ndarray:
    sf2 = soundfont or find_soundfont()
    try:
        import fluidsynth  # noqa: F401 — pyfluidsynth

        return _render_via_pyfluidsynth(midi_path, sample_rate, sf2)
    except ImportError:
        return _render_via_fluidsynth_cli(midi_path, sample_rate, sf2)


def render_midi_with_fluidsynth(
    midi_path: Path,
    wav_path: Path,
    reference_wav_path: Path,
    soundfont: Path | None = None,
    target_peak: float = 0.8912509381,
) -> Path:
    """
    Render MIDI with FluidSynth and match reference wav length exactly.

    Uses the first N seconds/frames of the arrangement (same policy as wav_renders).
    """
    target_frames, sample_rate, ref_duration = read_reference_duration(reference_wav_path)
    clip_path = clip_midi_to_duration(midi_path, ref_duration + 0.5)
    try:
        audio = synthesize_midi_audio(clip_path, sample_rate, soundfont)
    finally:
        if clip_path != midi_path and clip_path.exists():
            clip_path.unlink(missing_ok=True)
    audio = align_audio_length(audio, target_frames)
    audio = normalize_peak(audio, target_peak=target_peak)

    wav_path = Path(wav_path)
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(wav_path), audio, sample_rate)
    return wav_path
