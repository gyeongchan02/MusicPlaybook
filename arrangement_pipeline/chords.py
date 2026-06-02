"""Harte / POP909 chord symbol parsing via pychord with music21 fallback."""

from __future__ import annotations

import re
from dataclasses import dataclass

from music21 import harmony
from pychord import Chord as PyChord


@dataclass(frozen=True)
class ParsedChord:
    symbol: str
    root_pc: int
    pitches: tuple[int, ...]


_ROOT_PC = {
    "C": 0,
    "C#": 1,
    "Db": 1,
    "D": 2,
    "D#": 3,
    "Eb": 3,
    "E": 4,
    "F": 5,
    "F#": 6,
    "Gb": 6,
    "G": 7,
    "G#": 8,
    "Ab": 8,
    "A": 9,
    "A#": 10,
    "Bb": 10,
    "B": 11,
}


def _root_pc(root: str) -> int | None:
    return _ROOT_PC.get(root)


def harte_to_pychord(symbol: str) -> str | None:
    """Convert POP909 Harte token (e.g. G:sus2, A:min/5) to pychord string."""
    if not symbol or symbol == "N":
        return None
    body = symbol.strip()
    slash_bass = None
    if "/" in body:
        body, bass = body.split("/", 1)
        slash_bass = bass.strip()
    if ":" not in body:
        return body
    root, quality = body.split(":", 1)
    q = quality.lower()
    if q in ("maj", "major", ""):
        chord = root
    elif q in ("min", "minor", "m"):
        chord = f"{root}m"
    elif q.startswith("maj"):
        ext = q.replace("maj", "")
        chord = f"{root}maj{ext}" if ext else root
    elif q.startswith("min"):
        ext = q.replace("min", "")
        chord = f"{root}m{ext}" if ext else f"{root}m"
    elif "sus2" in q:
        chord = f"{root}sus2"
    elif "sus4" in q:
        chord = f"{root}sus4"
    elif "dim" in q:
        chord = f"{root}dim"
    elif "aug" in q:
        chord = f"{root}aug"
    elif q.startswith("dom") or q == "7":
        chord = f"{root}7"
    else:
        chord = root + q.replace(":", "")
    if slash_bass and slash_bass.isdigit():
        # Harte /5 → bass on fifth above root (e.g. B:min/5)
        try:
            degree = int(slash_bass)
            root_n = _root_pc(root)
            if root_n is not None:
                bass_pc = (root_n + degree - 1) % 12
                bass_name = [k for k, v in _ROOT_PC.items() if v == bass_pc and len(k) == 1]
                if bass_name:
                    chord = f"{chord}/{bass_name[0]}"
        except ValueError:
            pass
    return chord


def parse_chord_symbol(symbol: str, octave: int = 4) -> ParsedChord | None:
    if not symbol or symbol == "N":
        return None

    py_name = harte_to_pychord(symbol)
    pitches: list[int] = []
    root_pc = 0

    if py_name:
        try:
            chord = PyChord(py_name)
            names = chord.components()
            if names:
                root_pc = _root_pc(names[0]) or 0
                base = octave * 12 + 12
                for name in names:
                    pc = _root_pc.get(name)
                    if pc is None:
                        continue
                    midi = base + pc
                    while midi < base + root_pc:
                        midi += 12
                    pitches.append(midi)
        except Exception:
            pitches = []

    if not pitches:
        try:
            cs = harmony.ChordSymbol(symbol.replace(":", ""))
            pcs = [p.pitchClass for p in cs.pitches]
            if pcs:
                root_pc = pcs[0]
                base = octave * 12 + 12
                for pc in pcs:
                    midi = base + pc
                    while midi < base + root_pc:
                        midi += 12
                    pitches.append(midi)
        except Exception:
            return None

    if not pitches:
        m = re.match(r"^([A-G][#b]?)", symbol)
        if not m:
            return None
        root_pc = _root_pc.get(m.group(1), 0)
        pitches = [octave * 12 + 12 + root_pc, octave * 12 + 16 + root_pc, octave * 12 + 19 + root_pc]

    unique = tuple(sorted(set(pitches)))
    return ParsedChord(symbol=symbol, root_pc=root_pc, pitches=unique)
