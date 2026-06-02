"""Render MIDI to WAV via FluidSynth (fallback: pretty_midi synthesis)."""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pretty_midi


def find_soundfont() -> Path | None:
    candidates = [
        "/usr/share/sounds/sf2/FluidR3_GM.sf2",
        "/usr/share/sounds/sf2/TimGM6mb.sf2",
        "/opt/homebrew/share/soundfonts/FluidR3_GM.sf2",
        str(Path.home() / "Library/Audio/Sounds/FluidR3_GM.sf2"),
    ]
    for pattern in (
        "/opt/homebrew/Cellar/fluid-synth/*/share/soundfonts/FluidR3_GM.sf2",
        "/opt/homebrew/Cellar/fluid-synth/*/share/soundfonts/default.sf2",
    ):
        matches = glob.glob(pattern)
        if matches:
            return Path(matches[-1])
    for path in candidates:
        if os.path.exists(path):
            return Path(path)
    return None


def find_fluidsynth() -> str | None:
    for name in ("fluidsynth", "fluidsynth.exe"):
        found = shutil.which(name)
        if found:
            return found
    for pattern in ("/opt/homebrew/bin/fluidsynth", "/usr/local/bin/fluidsynth"):
        if os.path.exists(pattern):
            return pattern
    return None


def render_midi_to_wav(
    midi_path: Path,
    wav_path: Path,
    sample_rate: int = 44100,
    soundfont: Path | None = None,
) -> Path:
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    sf2 = soundfont or find_soundfont()
    fs_bin = find_fluidsynth()

    if fs_bin and sf2 and sf2.exists():
        cmd = [
            fs_bin,
            "-ni",
            str(sf2),
            str(midi_path),
            "-F",
            str(wav_path),
            "-r",
            str(sample_rate),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        return wav_path

    try:
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError(
            "FluidSynth or soundfont unavailable and soundfile not installed for fallback."
        ) from exc

    pm = pretty_midi.PrettyMIDI(str(midi_path))
    audio = pm.synthesize(fs=sample_rate)
    peak = float(np.max(np.abs(audio))) + 1e-9
    audio = 0.9 * (audio / peak)
    sf.write(str(wav_path), audio, sample_rate)
    return wav_path
