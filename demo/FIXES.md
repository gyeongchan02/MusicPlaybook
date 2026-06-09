# Demo Fix Log

Running log of bugs encountered and how they were resolved.
All issues are confined to `demo/` unless otherwise noted.

---

## 2026-06-09

### [1] 403 model_not_found — gpt-4o → gpt-5.4-nano

**File:** `demo/debate_live.py`

**Symptom:**
```
openai.PermissionDeniedError: 403 model_not_found
```

**Cause:** The default model name pointed to a model the API key no longer had access to.

**Fix:** Changed `DEFAULT_MODEL` to `"gpt-5.4-nano"` (also overridable via `DEBATE_MODEL` env var).

**Result:** Live debate ran successfully — Pre-debate analysis, Round 1 (Tradition Guardian +
Style Translator proposals), and max-rounds termination all completed normally.

---

### [2] AttributeError: 'str' object has no attribute 'get' — validator verdicts

**File:** `demo/debate_viz.py` → `render_validator`

**Symptom:**
```
AttributeError: 'str' object has no attribute 'get'
  File "demo/debate_viz.py", in render_validator
    aspect = verdict.get("aspect", "aspect")
```

**Cause:** gpt-5.4-nano returned `verdict_per_aspect` as a list of strings (or a plain string)
instead of the expected list of dicts.

**Fix (defense-in-depth, visualization only):**
- `validator` not a dict → render as plain text and return early.
- `verdict_per_aspect` is a string → `st.markdown` and skip the loop.
- Individual `verdict` item not a dict → render as bullet and `continue`.

Same pattern applied to `render_pre_analysis`, `render_agent_proposal`, `_proposal_summary`.

---

### [3] AttributeError: 'list' object has no attribute 'get' — render_spec_json

**File:** `demo/debate_viz.py` → `render_spec_json`

**Symptom:**
```
AttributeError: 'list' object has no attribute 'get'
  c1.metric("Tempo", f"{transform.get('tempo_bpm', '?')} BPM")
```

**Cause:** gpt-5.4-nano returned `transformations` as a list. Visualization code assumed dict.

**Fix:** Added `isinstance(transform, dict)` guard before the metrics block. Full JSON expander
still renders regardless.

---

### [4] Korean text in frontend — full English pass

**Files:** `demo/app.py`, `demo/custom_input.py`, `demo/theme.py`

**Fix:** Replaced all Korean strings with English equivalents. No logic changes.

---

### [5] KeyError: 'transformations' — Generate button crashes (baseline spec)

**Files:** `arrangement_pipeline/spec_loader.py`, `demo/render_service.py`

**Symptom:**
```
KeyError: 'transformations'
  File "arrangement_pipeline/spec_loader.py", in get_transformations
```

**Cause:** gpt-5.4-nano's baseline spec uses a completely different schema (`tempo_and_groove`,
`instrumentation.rhythm_section`, `chord_progression`) with no `transformations` key.
`get_transformations` fell through to bare `spec["transformations"]`.

**Fix:**
1. `spec_loader.py::get_transformations` — all return paths use `.get("transformations", {})`
   with `isinstance(t, dict)` guard.
2. `render_service.py::_normalize_spec` — normalizes spec before pipeline runs;
   writes corrected spec back to the temp file.

---

### [6] ValueError: arrangement spec missing metadata.input_song_id — debate spec

**Files:** `demo/render_service.py`, `demo/app.py`

**Symptom:**
```
ValueError: arrangement spec missing metadata.input_song_id
```

**Cause:** gpt-5.4-nano's synthesizer omitted `input_song_id` from `metadata`.

**Fix:** `_normalize_spec` fills it from: `metadata.input_song_id` → `spec.song_id` →
`export_metadata.song_id` → `song_id` arg passed from the sidebar selection.
`app.py` passes `song_id=song_id` to `render_arrangement`.

---

### [7] AttributeError: 'list' object has no attribute 'get' — primary_spec.transformations

**Files:** `arrangement_pipeline/spec_loader.py`, `demo/render_service.py`

**Symptom:**
```
AttributeError: 'list' object has no attribute 'get'
  (Multi-agent → Arranged output → Generate)
```

**Cause:** Fix [5] guarded the top-level and `baseline` paths in `get_transformations`, but the
`primary_spec` and `alternative_spec` paths still returned the raw value without `isinstance` check.

**Fix:** `isinstance(t, dict)` guard added to all four return paths. `_normalize_spec` also
patches `primary_spec.transformations` when it is not a dict.

---

### [8] Header badge "SNU Demo" → "P4DS Team 6"

**File:** `demo/theme.py`

**Fix:** Updated the `snu-badge` span in `snu_header`.

---

### [9] Single-agent and multi-agent produce identical audio

**Files:** `demo/render_service.py`, `demo/debate_live.py`

**Symptom:** Both Generate buttons output the same WAV; downloaded files are identical.

**Root cause (layer 1 — extractor):** `_extract_transformations_from_schema` used hardcoded
type-name matching and fixed key paths. gpt-5.4-nano uses completely different type names and
nesting on every single run (e.g. `"tempo_lock"`, `"voicing_and_texture_guidance"`,
`groove_and_rhythm.rhythm_pattern.option_from_evidence`). Both specs normalized to `{}` →
identical pipeline defaults → same audio.

**Root cause (layer 2 — LLM prompt):** `synthesize_spec` and `run_baseline_spec` prompts were
too vague, so gpt-5.4-nano invented its own freeform structure every time with no guarantee of
machine-readable field names.

**Fix 1 — `render_service.py`: recursive deep search (`_deep_extract`)**

Replaces all type/key-name matching. Walks the entire spec tree at any nesting depth:
- Key contains `"tempo"/"bpm"` + numeric value (40–300) → `tempo_bpm`
- String value exactly in rhythm registry → `rhythm_pattern`
- String value containing a voicing style as substring → `voicing_style`
- Key contains `"density"` + numeric value (0–1) → `texture_density`
- List of `{"bar": int, "chord": str}` dicts → `chord_progression`

Verified on real session files (old prompts):
| Spec | rhythm_pattern | voicing_style | tempo_bpm | texture_density |
|------|---------------|---------------|-----------|-----------------|
| Debate | (not found — LLM omitted valid values entirely) | (not found) | 124 ✅ | 0.55 ✅ |
| Baseline | `soul_laid_back_16th` ✅ | `neo_soul_extensions` ✅ | 124 ✅ | — |

**Fix 2 — `debate_live.py`: enforce exact output schema in LLM prompts**

Added `SYNTH_SCHEMA` with the exact required JSON structure and `"MUST be one of"` lists for
`rhythm_pattern` and `voicing_style`. Applied to both `synthesize_spec` and `run_baseline_spec`.
Future runs will produce `transformations` as a flat dict with exact registry-compatible field
names.

**Scope note:** Only the output-format prompts were changed. The debate loop, convergence logic,
and validator (shared with the research notebooks) are untouched.

---

### [10] No drums generated — percussion=None for both specs (follow-up to [9])

**File:** `demo/render_service.py`

**Symptom:**
Both arrangements rendered without drums. Even though rhythm patterns differed, the rhythm difference
was inaudible because `accompaniment.py::generate_accompaniment` only generates the drum track when
`instrumentation.get("percussion")` is truthy — and it was `None` for both specs.

**Root cause (confirmed via parameter logging):**

- Debate spec: drums described under `arrangement_texture[*].details.drums` as a free-text string
  (e.g. `"steady pocket supporting..."`). Not in `instrumentation` dict → never reached the pipeline.
- Baseline spec: `instrumentation.drums.instrument_options[0] = "soul_drums"` — nested one level
  deeper than the pipeline's `instrumentation.percussion` lookup.

Neither spec had a top-level `instrumentation.percussion` key → `perc_name = None` → no drums.

**Fix:**

Added percussion extraction to `_deep_extract` and a post-processing step:

1. **`_deep_extract`**: When any key contains `"drum"` or `"percussion"` with a truthy value:
   - If value is a valid instrument string → `result["_percussion_name"] = val`
   - If value is a dict with `instrument_options` → `result["_percussion_name"] = opts[0]`
   - Otherwise → `result["_has_drums"] = True` (drums implied, no exact name)

2. **`_promote_drums(t)`**: New helper. Reads `_percussion_name`/`_has_drums` sentinels, removes
   them, and writes `t["instrumentation"]["percussion"] = name or "soul_drums"`.

3. **`_normalize_spec`**: Calls `_promote_drums` after setting both `transformations` and
   `primary_spec.transformations`.

---

### [11] texture_density stuck at default 0.4 — text values not parsed

**File:** `demo/render_service.py`

**Symptom:** Both specs rendered at `texture_density=0.4` (pipeline default). Baseline spec had
`global.mix_intent.texture_density_target = "medium"` — a text value, not a float.

**Root cause:** `_deep_extract` density block only called `_parse_float()`, which extracts a leading
number from a string — `"medium"` has no digits → returns `None` → density not set.

**Fix:** Added `_DENSITY_TEXT` lookup table:
```python
_DENSITY_TEXT = {"low": 0.3, "medium": 0.5, "med": 0.5, "high": 0.7, "moderate": 0.5}
```
Density block now checks `val.lower() in _DENSITY_TEXT` before falling back to `_parse_float`.

---

## Root pattern

All issues stem from a single cause: **gpt-5.4-nano produces freeform JSON that does not match
the schema the pipeline was designed for**, even with `response_format: json_object`.

Fix principles:
1. Never assume a field type — always `isinstance` before `.get()`.
2. Normalize at the demo boundary, not inside the pipeline.
3. Validate against known registries before using LLM-provided string values.
4. Keep Full JSON expanders in the UI so raw LLM output is always inspectable.
