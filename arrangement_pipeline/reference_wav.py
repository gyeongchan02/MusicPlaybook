"""Resolve POP909 reference wav paths (30s CLAP renders from 01_data_retrieval)."""

from __future__ import annotations

from pathlib import Path

import soundfile as sf


def reference_wav_path(repo_root: Path, song_id: str) -> Path:
    """
    Map song id to data/wav_renders/POP909_XXX.wav.

    Falls back to rendering metadata from source MIDI if the wav is missing.
    """
    repo_root = Path(repo_root)
    wav = repo_root / "data" / "wav_renders" / f"{song_id}.wav"
    if wav.exists():
        return wav
    raise FileNotFoundError(
        f"Reference wav not found: {wav}. "
        "Run 01_data_retrieval.ipynb §5 to create wav_renders first."
    )


def read_reference_duration(reference_wav: Path) -> tuple[int, int, float]:
    """Return (num_frames, sample_rate, duration_sec)."""
    info = sf.info(str(reference_wav))
    duration = info.frames / float(info.samplerate)
    return info.frames, info.samplerate, duration
