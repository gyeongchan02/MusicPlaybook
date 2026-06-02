# Arrangement pipeline

Converts MusicPlaybook `arrangement_spec.json` into `arranged.mid` and `arranged.wav`.

## Requirements

```bash
pip install -r arrangement_pipeline/requirements.txt
brew install fluid-synth   # optional but recommended for arranged.wav
```

Python modules: `pretty_midi`, `music21`, `pychord`, `numpy`, `soundfile`  
System: `fluidsynth` + a GM soundfont (e.g. FluidR3_GM.sf2)

## Usage

From the repo root:

```bash
python -m arrangement_pipeline \
  --spec outputs/run_20260528_173722_POP909_026_lo-fi_chill/arrangement_spec.json \
  --out-dir outputs/run_20260528_173722_POP909_026_lo-fi_chill/arranged
```

Options:

| Flag | Description |
|------|-------------|
| `--variant primary` | Use `primary_spec` when debate produced dual output |
| `--variant alternative` | Render `alternative_spec` |
| `--variant baseline` | Render flat `baseline_spec.json` |
| `--no-wav` | MIDI only |
| `--no-drums` | Bass + Rhodes only |
| `--style-definitions` | Custom `style_definitions.json` |

## Pipeline steps

1. Load POP909 source MIDI (`data/POP909-Dataset/POP909/<id>/<id>.mid`).
2. Copy **MELODY** only; drop BRIDGE / PIANO accompaniment.
3. Build harmony from `chord_midi.txt`, with optional per-bar overrides from the spec (`chord_progression_preview`).
4. Parse Harte symbols (`G:sus2`, `A:min`, …) via **pychord** (music21 fallback).
5. Generate accompaniment from `style_definitions.json`:
   - `rhythm_pattern` (e.g. `lofi_swung_16th`)
   - `voicing_style` (e.g. `spread_with_9ths`)
   - `texture_density` in **[0, 1]**
6. Write **upright bass**, **Rhodes comp**, optional **lo-fi drums**.
7. Export `arranged.mid` and render `arranged.wav` with FluidSynth.

## Extending styles

Add entries to `style_definitions.json` only — no Python changes required for new enums that reuse existing strategies:

```json
"rhythm_patterns": {
  "my_new_groove": { "grid": "16th", "swing_ratio": 0.6, ... }
},
"voicing_styles": {
  "my_voicing": { "strategy": "spread", "add_ninth": true, ... }
}
```

Register the new enum names in `artifacts/style_profiles.json` (debate layer) and reference them in `arrangement_spec.json` (render layer).

## Layout

```
arrangement_pipeline/
  style_definitions.json   # rhythm / voicing / GM instrument map
  pop909.py                # MELODY track + chord file I/O
  chords.py                # Harte → pitch classes (pychord + music21)
  spec_loader.py           # arrangement_spec.json
  style_registry.py        # JSON lookup
  rhythm.py                # swung grid timing
  voicing.py               # spread / drop-2 voicings
  accompaniment.py         # bass + Rhodes + drums
  pipeline.py              # orchestration
  render.py                # FluidSynth → WAV
  __main__.py              # CLI
```
