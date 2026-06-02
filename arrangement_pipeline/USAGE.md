# Arrangement pipeline (add-only entry)

Uses **FluidSynth** via `pretty_midi.PrettyMIDI.fluidsynth()` and matches the **original** `data/wav_renders/<song_id>.wav` length (30s CLAP clip from `01_data_retrieval`).

## Run (recommended)

```bash
cd /Users/hwangsaeyeon/MusicPlaybook

python3.10 -m arrangement_pipeline.run \
  --spec outputs/run_20260528_173722_POP909_026_lo-fi_chill/arrangement_spec.json \
  --out-dir outputs/run_20260528_173722_POP909_026_lo-fi_chill/arranged
```

Outputs:

- `arranged.mid` — full-length arrangement
- `arranged.wav` — first 30s, same frame count / sample rate as `data/wav_renders/POP909_026.wav`

## Requirements

- `pip install -r arrangement_pipeline/requirements.txt`
- `brew install fluid-synth`
- Reference wav must exist (`01_data_retrieval.ipynb` §5)

## Style extension

Edit only `arrangement_pipeline/style_definitions.json` for new `rhythm_pattern` / `voicing_style` enums.

## Legacy CLI

`python -m arrangement_pipeline` (uses `__main__.py`) still works but may fall back to sine synthesis if FluidSynth is missing. Prefer `arrangement_pipeline.run` for spec-compliant WAV export.
