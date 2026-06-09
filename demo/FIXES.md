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

### [12] TypeError: st.metric() received dict — `{'set_to': 124.0, 'evidence': '...'}`

**File:** `demo/debate_viz.py`

**Symptom:**
```
TypeError: st.metric value must be int, float, str, or None
  c4.metric("Density", transform.get("texture_density", "?"))
```
Tempo box displayed `{'set_to': 124....}` raw dict; Density line raised TypeError.

**Root cause:** gpt-5.4-nano sometimes wraps scalar values in `{"set_to": <value>, "evidence": "..."}`.
`st.metric()` does not accept dicts.

**Fix:** Added `_scalar(v)` helper in `debate_viz.py`:
```python
def _scalar(v): return v.get("set_to", v) if isinstance(v, dict) else v
```
Wrapped all four `st.metric()` calls in `render_spec_json` with `_scalar(...)`.

---

### [13] Unknown instrument error — LLM returns free-text instrument names

**File:** `demo/render_service.py`

**Symptom:**
```
Unknown instrument 'electric bass fingerstyle'. Available: ['acoustic_bass', ...]
```
Pipeline raises `ValueError` when `instrumentation.bass` contains a natural-language description
instead of a registry key.

**Root cause:** The pipeline does a direct dict lookup on instrument names. LLM writes things like
`"electric bass fingerstyle"`, `"soul drum kit"`, `"warm Rhodes electric piano"` — none of which
match registry keys exactly.

**Fix:** Added `_normalize_instrument(val, role)` in `render_service.py`:
1. Exact match → return as-is
2. Normalize to slug (lowercase, spaces→underscores) → exact match
3. Substring: find registry name whose tokens all appear in the slug
4. Reverse substring: slug tokens present in a registry name
5. Fall back to role default (`bass` → `electric_bass_finger`, `lead` → `rhodes_electric_piano`, etc.)

Added `_normalize_instrumentation_dict(inst)` that applies this to all four roles (`lead`, `bass`,
`percussion`, `ambient`) and is called from `_normalize_spec` after `_promote_drums`.

---

### [14] Hard rule violations every round — agents write free-text for rhythm_pattern/voicing_style

**File:** `demo/debate_live.py`

**Symptom:**
```
Hard rules: ❌ failed
rhythm_pattern_enum: R&B-soul groove (creative suggestion): steady 4/4 with kick...
voicing_style_enum: Soul/R&B chord voicings (creative suggestion): prioritize...
```
Every proposal failed `hard_rule_validate` because agents wrote descriptive sentences instead of
exact registry values.

**Root cause:** `PROPOSAL_SCHEMA` declared `rhythm_pattern` and `voicing_style` as plain `string`
with no constraint, so gpt-5.4-nano wrote natural-language descriptions. `SYNTH_SCHEMA` already
had the "MUST be exactly one of" constraint; `PROPOSAL_SCHEMA` did not.

**Fix:** Converted `PROPOSAL_SCHEMA` to an f-string referencing `_VALID_RHYTHM_PATTERNS` and
`_VALID_VOICING_STYLES` (same lists already used by `SYNTH_SCHEMA`):
```
"rhythm_pattern": "MUST be exactly one of: ['ballad_arpeggio', ..., 'soul_straight_8th']"
"voicing_style":  "MUST be exactly one of: ['block_chords', ..., 'spread_with_9ths']"
```
Also moved `_VALID_RHYTHM_PATTERNS` / `_VALID_VOICING_STYLES` definitions above `PROPOSAL_SCHEMA`
to avoid `NameError` at import time.

**Scope note:** Only the output-format schema string was changed. Debate loop, convergence, and
validator logic are untouched.

---

---

## Rollback & Rebuild Log

### [R1] Partial rollback — audio pipeline reverted, UI kept → song_id mismatch

**Trigger:** After fixes [9]–[11] were applied, the audio output sounded wrong.
User requested: "두 음악이 동일하게 나오던 시절로 롤백해줘" (roll back to when both pieces
sounded identical).

**Action:** `git restore` on 3 files only:
- `arrangement_pipeline/spec_loader.py` → committed state (no isinstance guards)
- `demo/render_service.py` → committed state (no normalization layer, no `song_id` param)
- `demo/debate_live.py` → committed state (no `SYNTH_SCHEMA`)

UI files kept as-is (`app.py`, `debate_viz.py`, `theme.py`, `custom_input.py`).

**Consequence:** `app.py` still called `render_arrangement(..., song_id=song_id)` (our addition),
but the restored `render_service.py` had no `song_id` parameter → immediate crash:
```
TypeError: render_arrangement() got an unexpected keyword argument 'song_id'
```
Also: `debate_viz.py` was kept modified but the restored `render_service.py` now passed
`{'set_to': 124.0, ...}` dicts again → st.metric() TypeError on the Specs tab.

**Lesson:** Partial rollback creates silent ABI mismatches between caller and callee when the
two sides were modified together. The partial state was never consistent.

---

### [R2] Accidental full git restore — wiped all uncommitted changes

**Trigger:** User asked to fix the `song_id` mismatch from [R1]. Instead of the targeted
one-line fix (remove `song_id=song_id` from the call, or add the param back), a full
`git restore .` was run.

**Effect:** All uncommitted changes (fixes [1]–[14], UI translations, crash guards,
normalization layer) were wiped. Only `demo/FIXES.md` survived (untracked file).

**Recovery:** Manually reconstructed the full modified state from session memory:
- `arrangement_pipeline/spec_loader.py`: isinstance guards re-applied
- `demo/render_service.py`: full normalization layer re-written from scratch
- `demo/debate_live.py`: `SYNTH_SCHEMA` + valid-value lists re-applied
- `demo/debate_viz.py`: all isinstance crash guards + `_scalar` re-applied
- `demo/app.py`: all Korean→English + `song_id=song_id` re-applied
- `demo/theme.py`: badge re-applied
- `demo/custom_input.py`: error messages re-applied

---

## Root pattern

All issues stem from a single cause: **gpt-5.4-nano produces freeform JSON that does not match
the schema the pipeline was designed for**, even with `response_format: json_object`.

Fix principles:
1. Never assume a field type — always `isinstance` before `.get()`.
2. Normalize at the demo boundary, not inside the pipeline.
3. Validate against known registries before using LLM-provided string values.
4. Keep Full JSON expanders in the UI so raw LLM output is always inspectable.
