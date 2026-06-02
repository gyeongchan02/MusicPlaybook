"""Load style_definitions.json and resolve pattern / voicing / instrument configs."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


DEFAULT_STYLE_PATH = Path(__file__).resolve().parent / "style_definitions.json"


@lru_cache(maxsize=1)
def load_style_definitions(path: str | None = None) -> dict[str, Any]:
    style_path = Path(path) if path else DEFAULT_STYLE_PATH
    with open(style_path, encoding="utf-8") as handle:
        return json.load(handle)


def get_rhythm_pattern(name: str, definitions: dict[str, Any] | None = None) -> dict[str, Any]:
    defs = definitions or load_style_definitions()
    patterns = defs.get("rhythm_patterns", {})
    if name not in patterns:
        raise KeyError(f"Unknown rhythm_pattern {name!r}. Available: {sorted(patterns)}")
    return patterns[name]


def get_voicing_style(name: str, definitions: dict[str, Any] | None = None) -> dict[str, Any]:
    defs = definitions or load_style_definitions()
    styles = defs.get("voicing_styles", {})
    if name not in styles:
        raise KeyError(f"Unknown voicing_style {name!r}. Available: {sorted(styles)}")
    return styles[name]


def get_instrument(name: str, definitions: dict[str, Any] | None = None) -> dict[str, Any]:
    defs = definitions or load_style_definitions()
    instruments = defs.get("instruments", {})
    if name not in instruments:
        raise KeyError(f"Unknown instrument {name!r}. Available: {sorted(instruments)}")
    return instruments[name]
