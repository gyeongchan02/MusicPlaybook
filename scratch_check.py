# === Section 0.1: Imports ===
import os
import sys
import json
import time
import math
import random
import datetime
import re
from pathlib import Path
from collections import Counter

import numpy as np
import pandas as pd

RANDOM_SEED = 42
random.seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)

ART_DIR = Path("./artifacts").resolve()
OUT_DIR = Path("./outputs").resolve()
OUT_DIR.mkdir(parents=True, exist_ok=True)
print(f"Artifacts dir: {ART_DIR}")
print(f"Outputs dir:   {OUT_DIR}")

# === Section 0.2: OpenAI API key ===
def _load_openai_key():
    # Priority 1: env var
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"]
    # Priority 2: ~/.secrets/openai_api_key
    secret_path = os.path.expanduser("~/.secrets/openai_api_key")
    if os.path.exists(secret_path):
        with open(secret_path) as f:
            key = f.read().strip()
        if key:
            os.environ["OPENAI_API_KEY"] = key
            return key
    # Priority 3: Colab Secrets
    try:
        from google.colab import userdata
        key = userdata.get("OPENAI_API_KEY")
        if key:
            os.environ["OPENAI_API_KEY"] = key
            return key
    except Exception:
        pass
    return None

OPENAI_API_KEY = _load_openai_key()
if OPENAI_API_KEY is None:
    print("[WARN] OPENAI_API_KEY not found.")
    print("       Create ~/.secrets/openai_api_key with your key.")
else:
    print(f"OPENAI_API_KEY loaded (length={len(OPENAI_API_KEY)}).")

# === Section 0.3: Install openai sdk if needed ===
try:
    import openai
    print(f"openai sdk already installed (v{openai.__version__})")
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "openai>=1.40.0"], check=True)
    import openai
    print(f"openai sdk installed (v{openai.__version__})")

from openai import OpenAI
client = OpenAI(api_key=OPENAI_API_KEY)

# === Section 1.1: Load everything from 01 notebook ===
features          = pd.read_parquet(ART_DIR / "features.parquet")
clap_embs         = np.load(ART_DIR / "clap_embeddings.npy")
style_profiles    = json.loads((ART_DIR / "style_profiles.json").read_text())
style_text_embs   = np.load(ART_DIR / "style_text_embeddings.npy")
style_text_index  = json.loads((ART_DIR / "style_text_index.json").read_text())

print(f"features:        {features.shape}")
print(f"clap_embs:       {clap_embs.shape}")
print(f"style_profiles:  {list(style_profiles.keys())}")
print(f"style_text_embs: {style_text_embs.shape}")

# Stack vector columns to matrices for batch ops
chord_mat  = np.stack(features["chord_histogram"].apply(np.asarray).values).astype(np.float32)
pcd_mat    = np.stack(features["pitch_class_dist"].apply(np.asarray).values).astype(np.float32)
rhythm_mat = np.stack(features["rhythm_pattern"].apply(np.asarray).values).astype(np.float32)

# === Section 2.1: Retrieval helpers ===
def _cos_sim_batch(q, mat):
    qn = q / (np.linalg.norm(q) + 1e-9)
    mn = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9)
    return mn @ qn


HYBRID_WEIGHTS = {"clap": 0.4, "chord": 0.3, "rhythm": 0.2, "key": 0.1}

def retrieve_similar(query_idx: int, k: int = 5, exclude_self: bool = True) -> list[dict]:
    q_clap  = clap_embs[query_idx]
    q_chord = chord_mat[query_idx]
    q_rhy   = rhythm_mat[query_idx]
    q_key   = features.iloc[query_idx]["key"]
    q_mode  = features.iloc[query_idx]["mode"]

    s_clap  = _cos_sim_batch(q_clap,  clap_embs)
    s_chord = _cos_sim_batch(q_chord, chord_mat)
    s_rhy   = _cos_sim_batch(q_rhy,   rhythm_mat)
    s_key   = ((features["key"].values == q_key) &
               (features["mode"].values == q_mode)).astype(np.float32)

    score = (HYBRID_WEIGHTS["clap"]   * s_clap +
             HYBRID_WEIGHTS["chord"]  * s_chord +
             HYBRID_WEIGHTS["rhythm"] * s_rhy +
             HYBRID_WEIGHTS["key"]    * s_key)
    if exclude_self:
        score[query_idx] = -1e9

    top = np.argsort(score)[::-1][:k]
    return [
        {"song_id": features.iloc[i]["song_id"],
         "score":   float(score[i]),
         "key":     features.iloc[i]["key"],
         "mode":    features.iloc[i]["mode"],
         "tempo":   float(features.iloc[i]["tempo"]),
         "note_density": float(features.iloc[i]["note_density"]),
         "channel_scores": {
             "clap": float(s_clap[i]),
             "chord": float(s_chord[i]),
             "rhythm": float(s_rhy[i]),
             "key": float(s_key[i]),
         }}
        for i in top
    ]


def retrieve_style_refs(target_style: str, k: int = 5) -> dict:
    if target_style not in style_profiles:
        raise ValueError(f"Unknown style: {target_style}")
    prof  = style_profiles[target_style]
    qtext = style_text_embs[style_text_index[target_style]]
    sims  = _cos_sim_batch(qtext, clap_embs)
    top   = np.argsort(sims)[::-1][:k]

    refs, tempos, ndens = [], [], []
    for i in top:
        row = features.iloc[i]
        refs.append({
            "song_id":      row["song_id"],
            "similarity":   float(sims[i]),
            "key":          row["key"],
            "mode":         row["mode"],
            "tempo":        float(row["tempo"]),
            "note_density": float(row["note_density"]),
            "chord_progression_preview": list(row["chord_progression"][:8]),
        })
        tempos.append(float(row["tempo"]))
        ndens.append(float(row["note_density"]))
    return {
        "target_style": target_style,
        "clap_text_prompt": prof["clap_text_prompt"],
        "reference_pieces": refs,
        "aggregated_style_features": {
            "mean_tempo_of_refs":  float(np.mean(tempos)) if tempos else None,
            "tempo_std_of_refs":   float(np.std(tempos))  if tempos else None,
            "mean_note_density_of_refs": float(np.mean(ndens)) if ndens else None,
            "preferred_chord_extensions": prof["preferred_chord_extensions"],
            "rhythm_pattern_options":     prof["rhythm_pattern_options"],
            "voicing_style_options":      prof["voicing_style_options"],
            "tempo_range_bpm":            prof["tempo_range_bpm"],
            "texture_density_range":      prof["texture_density_range"],
            "instrumentation_options":    prof["instrumentation_options"],
        },
    }


# Demo: retrieve for the first song
print("Retrieval A demo (similar to song 0):")
for h in retrieve_similar(0, k=3):
    print(f"  {h['song_id']:14s}  score={h['score']:.3f}")

print("\nRetrieval B demo (lo-fi chill):")
for r in retrieve_style_refs("lo-fi chill", k=3)["reference_pieces"]:
    print(f"  {r['song_id']:14s}  sim={r['similarity']:+.3f}")

# === Section 3.1: LLMClient with cost tracking ===
# Per-1M-token pricing (USD), updated 2026-05. Adjust to your billing tier.
MODEL_PRICING = {
    "gpt-4o":          {"in": 2.50,  "out": 10.00},
    "gpt-4o-mini":     {"in": 0.15,  "out": 0.60},
    "gpt-3.5-turbo":   {"in": 0.50,  "out": 1.50},
    "text-embedding-3-small": {"in": 0.02, "out": 0.00},
}

COST_BUDGET_USD = 5.00       # hard cap; raise once verified
WARN_AT_USD     = 1.00

class LLMClient:
    """Thin wrapper around OpenAI chat completions with bookkeeping."""

    def __init__(self, model: str, name: str = ""):
        self.model = model
        self.name  = name or model
        self.calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.cost = 0.0

    def chat_json(self, system: str, user: str,
                  temperature: float = 0.6,
                  max_retries: int = 1) -> dict:
        """Call the LLM expecting a JSON object back.

        Uses OpenAI's `response_format={'type':'json_object'}` (works on 4o family
        and 3.5-turbo-0125+). Returns parsed dict; on parse failure raises ValueError.
        """
        global TOTAL_LLM_CALLS

        if _global_budget_state["cost"] > COST_BUDGET_USD:
            raise RuntimeError(
                f"Cost budget exceeded (${_global_budget_state['cost']:.4f} > ${COST_BUDGET_USD}). "
                f"Raise COST_BUDGET_USD if intentional."
            )

        last_err = None
        for attempt in range(max_retries + 1):
            try:
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user",   "content": user},
                    ],
                    temperature=temperature,
                    response_format={"type": "json_object"},
                )
                content = resp.choices[0].message.content
                usage   = resp.usage
                # Bookkeeping
                self.calls       += 1
                self.tokens_in   += usage.prompt_tokens
                self.tokens_out  += usage.completion_tokens
                price = MODEL_PRICING.get(self.model, {"in": 0, "out": 0})
                call_cost = (usage.prompt_tokens     * price["in"]  / 1_000_000 +
                             usage.completion_tokens * price["out"] / 1_000_000)
                self.cost += call_cost
                _global_budget_state["cost"] += call_cost
                _global_budget_state["calls"] += 1

                if _global_budget_state["cost"] > WARN_AT_USD and not _global_budget_state["warned"]:
                    print(f"[BUDGET WARN] Total cost has passed ${WARN_AT_USD:.2f}.")
                    _global_budget_state["warned"] = True

                try:
                    return json.loads(content)
                except json.JSONDecodeError as je:
                    raise ValueError(f"Model returned invalid JSON:\n{content[:500]}") from je

            except Exception as e:
                last_err = e
                if attempt < max_retries:
                    wait = 2 ** attempt
                    print(f"  [retry] {self.name} error: {e}; sleeping {wait}s...")
                    time.sleep(wait)
                    continue
                raise

    def stats(self) -> dict:
        return {"name": self.name, "model": self.model,
                "calls": self.calls,
                "tokens_in": self.tokens_in, "tokens_out": self.tokens_out,
                "cost_usd": round(self.cost, 6)}


# Global budget tracker shared across all clients
_global_budget_state = {"cost": 0.0, "calls": 0, "warned": False}

def total_cost_so_far():
    return _global_budget_state["cost"]

# === Section 3.2: Embedding client (separate; used by convergence metric) ===
class EmbeddingClient:
    """Small wrapper for text-embedding-3-small."""
    def __init__(self, model: str = "text-embedding-3-small"):
        self.model = model
        self.calls = 0
        self.tokens = 0
        self.cost = 0.0

    def embed(self, text: str) -> np.ndarray:
        resp = client.embeddings.create(model=self.model, input=text)
        emb = np.array(resp.data[0].embedding, dtype=np.float32)
        emb = emb / (np.linalg.norm(emb) + 1e-9)
        # cost (input only for embeddings)
        u = resp.usage.prompt_tokens
        c = u * MODEL_PRICING[self.model]["in"] / 1_000_000
        self.calls += 1
        self.tokens += u
        self.cost += c
        _global_budget_state["cost"] += c
        return emb


embed_client = EmbeddingClient()

# === Section 3.3: Instantiate the heterogeneous client roster ===
llm_tradition  = LLMClient(model="gpt-5.4-nano",   name="TraditionGuardian")
llm_style      = LLMClient(model="gpt-5.4-nano",        name="StyleTranslator")
llm_validator  = LLMClient(model="gpt-5.4-nano", name="MusicTheoryValidator")
llm_synth      = LLMClient(model="gpt-5.4-nano",   name="Synthesizer")
llm_baseline   = LLMClient(model="gpt-5.4-nano",   name="SingleAgentBaseline")

print("Configured clients:")
for c in [llm_tradition, llm_style, llm_validator, llm_synth, llm_baseline]:
    print(f"  {c.name:25s} -> {c.model}")

# === Section 4.1: Music theory hard rules ===
NOTE_NAMES   = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]
NAME_TO_PC   = {n: i for i, n in enumerate(NOTE_NAMES)}
# Aliases (flats)
NAME_TO_PC.update({"Db": 1, "Eb": 3, "Gb": 6, "Ab": 8, "Bb": 10})

# Diatonic intervals from tonic (in semitones)
MAJOR_SCALE_INTERVALS = [0, 2, 4, 5, 7, 9, 11]
MINOR_SCALE_INTERVALS = [0, 2, 3, 5, 7, 8, 10]

# Borrowed chords commonly accepted (in major key: bVI, bVII, iv, parallel-minor i)
BORROWED_INTERVALS_MAJOR = [3, 8, 10]   # bIII, bVI, bVII
BORROWED_INTERVALS_MINOR = [4, 11]      # major III, leading-tone variants


def _normalize_chord_token(token: str) -> tuple[int | None, str]:
    """Parse e.g. 'Cmaj9', 'Am7', 'F#min', 'Bb7sus4' -> (root_pc, quality_simplified)."""
    if not token or not isinstance(token, str):
        return None, ""
    m = re.match(r"^([A-Ga-g][#b]?)\s*(.*)$", token.strip())
    if not m:
        return None, ""
    root = m.group(1).capitalize().replace("b", "b").replace("#", "#")
    rest = m.group(2).lower()
    pc = NAME_TO_PC.get(root)
    if pc is None:
        return None, ""
    return pc, rest


def chord_in_key(chord_token: str, key_root: str, key_mode: str) -> bool:
    """Check whether chord's root is diatonic (or commonly borrowed) in the given key."""
    pc, _ = _normalize_chord_token(chord_token)
    if pc is None:
        return True   # unknown token -> skip (don't fail run)
    key_pc = NAME_TO_PC.get(key_root.capitalize())
    if key_pc is None:
        return True
    rel = (pc - key_pc) % 12
    if key_mode == "major":
        return rel in set(MAJOR_SCALE_INTERVALS + BORROWED_INTERVALS_MAJOR)
    elif key_mode == "minor":
        return rel in set(MINOR_SCALE_INTERVALS + BORROWED_INTERVALS_MINOR)
    return True


def tempo_within_bounds(proposed_tempo: float, input_tempo: float, pct: float = 0.20) -> bool:
    lo = input_tempo * (1 - pct)
    hi = input_tempo * (1 + pct)
    return lo <= proposed_tempo <= hi


def enum_check(value: str, allowed: list) -> bool:
    return value in allowed



def check_cadence(progression: list, key_root: str) -> str | None:
    if len(progression) < 2: return None
    c1 = progression[-2].get("chord", "")
    c2 = progression[-1].get("chord", "")
    pc1, _ = _normalize_chord_token(c1)
    pc2, _ = _normalize_chord_token(c2)
    if pc1 is None or pc2 is None: return None
    key_pc = NAME_TO_PC.get(key_root.capitalize())
    if key_pc is None: return None
    
    rel1 = (pc1 - key_pc) % 12
    rel2 = (pc2 - key_pc) % 12
    
    # If ends on tonic but preceded by something unrelated
    if rel2 == 0 and rel1 not in [5, 7, 11, 2, 4]: 
        return f"Weak cadence: {c1} -> {c2} does not strongly resolve to tonic."
    return None

def check_voice_leading(progression: list) -> list:
    warnings = []
    for i in range(len(progression)-1):
        c1 = progression[i].get("chord", "")
        c2 = progression[i+1].get("chord", "")
        pc1, _ = _normalize_chord_token(c1)
        pc2, _ = _normalize_chord_token(c2)
        if pc1 is not None and pc2 is not None:
            diff = min((pc1 - pc2) % 12, (pc2 - pc1) % 12)
            if diff == 6:
                warnings.append(f"Tritone root movement {c1} -> {c2} might be harsh.")
    return warnings

def hard_rule_validate(spec: dict, input_key: str, input_mode: str,
                       input_tempo: float, target_style: str) -> dict:
    """Apply 4 hard rules. Returns a verdict dict; never raises."""
    violations, warnings = [], []
    prof = style_profiles.get(target_style, {})

    transforms = spec.get("transformations", {})
    progression = transforms.get("chord_progression", [])
    
    # Rule 1: chord-in-key
    for entry in progression:
        chord = entry.get("chord", "")
        if not chord_in_key(chord, input_key, input_mode):
            violations.append({"rule": "chord_in_key",
                               "detail": f"chord {chord!r} not diatonic/borrowed in {input_key} {input_mode}"})

    # Rule 3: tempo bound
    proposed_tempo = transforms.get("tempo_bpm")
    if proposed_tempo is not None:
        if not tempo_within_bounds(float(proposed_tempo), float(input_tempo)):
            violations.append({"rule": "tempo_bound",
                               "detail": f"proposed tempo {proposed_tempo} not within ±20% of input {input_tempo}"})

    # Rule 4: enum checks against style profile
    rp = transforms.get("rhythm_pattern")
    if rp and not enum_check(rp, prof.get("rhythm_pattern_options", [])):
        violations.append({"rule": "rhythm_pattern_enum",
                           "detail": f"{rp!r} not in {prof.get('rhythm_pattern_options')}"})
    vs = transforms.get("voicing_style")
    if vs and not enum_check(vs, prof.get("voicing_style_options", [])):
        violations.append({"rule": "voicing_style_enum",
                           "detail": f"{vs!r} not in {prof.get('voicing_style_options')}"})

    # Rule 5: Cadence check
    cadence_warn = check_cadence(progression, input_key)
    if cadence_warn:
        warnings.append({"rule": "cadence", "detail": cadence_warn})
        
    # Rule 6: Voice leading check
    vl_warns = check_voice_leading(progression)
    for w in vl_warns:
        warnings.append({"rule": "voice_leading", "detail": w})

    # Rule 2: melody clash detection (soft-ish)
    if not progression:
        warnings.append({"rule": "melody_clash", "detail": "no chord progression to check"})

    return {
        "passed":     len(violations) == 0,
        "violations": violations,
        "warnings":   warnings,
    }

# Quick sanity check
sanity_spec = {
    "transformations": {
        "chord_progression": [
            {"bar": 1, "chord": "Cmaj7"},
            {"bar": 2, "chord": "Am7"},
            {"bar": 3, "chord": "Dmaj7"},  # not in C major; should violate
        ],
        "tempo_bpm": 75,
        "rhythm_pattern": "lofi_swung_16th",
        "voicing_style": "spread_with_9ths",
    }
}
print(hard_rule_validate(sanity_spec, input_key="C", input_mode="major",
                          input_tempo=80.0, target_style="lo-fi chill"))

# === Section 5.1: Shared schemas ===
REASONING_CONSTRAINTS = """REASONING CONSTRAINTS — follow strictly:
1. Do NOT assert features not present in the retrieved evidence. If a property is not given
   (e.g. dynamics, articulation, pedalling), do not invent it.
2. `chord_progression_preview` is the FIRST ~8 chord tokens — an opening excerpt, not the
   whole piece. Do not generalize about overall form or climaxes from the preview alone.
3. Separate retrieved evidence from creative recommendation. In every `reasoning` field,
   when a claim goes beyond what the retrieval directly shows, mark it explicitly
   (e.g. "creative suggestion: ...").
4. STAY IN YOUR LANE. If the role description says X is NOT your job, do not produce X.
"""

ANALYSIS_SCHEMA = '''{
  "summary": string,                    // 2-3 sentence overall characterisation
  "musical_traits": [                   // 4-6 concrete observed traits
    {"trait": string, "evidence": string}
  ],
  "implications_for_arrangement": [string, ...]   // 2-4 bullets
}'''

# Proposals are tightly constrained to the spec schema fields so that they can be merged
# field-by-field by the synthesizer.
PROPOSAL_SCHEMA = '''{
  "key_observations": [string, ...],
  "proposals": {
    "chord_progression": [             // EXACTLY 8 bars for the opening section; agents can extend later
      {"bar": int, "chord": string}
    ],
    "rhythm_pattern":   string,        // MUST be one of the style profile enums
    "tempo_bpm":        number,        // MUST be within ±20% of input tempo
    "voicing_style":    string,        // MUST be one of the style profile enums
    "texture_density":  number,        // 0.0 - 1.0 (within style profile range)
    "instrumentation":  {              // pick one option from style profile
      "lead": string, "bass": string,
      "percussion": string | null, "ambient": string | null
    }
  },
  "reservations":   [string, ...],     // points you defer to other agents
  "disagreements":  [string, ...]      // empty in round 1; populated in round 2+
}'''

# === Section 5.2: Tradition Guardian agent ===
TRADITION_SYSTEM = f"""You are the **Tradition Guardian** — one of three agents in a music arrangement debate.

YOUR ROLE — strictly only this:
- Decide what musical features of the INPUT SONG must be PRESERVED so the piece remains recognizable.
- Decide what is SAFE TO TRANSFORM in service of the target style.
- React to other agents' proposals from the perspective of "does this damage the input's identity?"

NOT YOUR JOB:
- Proposing target-style idioms (the Style Translator owns that).
- Judging music theory correctness (the Music Theory Validator owns that).
- If you find yourself describing target-style devices, STOP. That belongs to Style Translator.

WHEN PROPOSING:
- Your `chord_progression` should be CONSERVATIVE — close to the input song's harmonic motion.
- `tempo_bpm` should stay near the input tempo (you naturally prefer minimal change).
- `texture_density` should reflect the input song's density (do not invent a target-style density).

{REASONING_CONSTRAINTS}

OUTPUT FORMAT — return STRICT JSON ONLY, no markdown fences:
{PROPOSAL_SCHEMA}
"""

def tradition_guardian_propose(user_query, retrieval_a, my_analysis, other_proposals=None, round_num=1):
    user_msg = f"""USER QUERY:
{json.dumps(user_query, ensure_ascii=False, indent=2)}

RETRIEVAL A (input song + similar pieces):
{json.dumps(retrieval_a, ensure_ascii=False, indent=2)}

YOUR PRE-DEBATE ANALYSIS:
{json.dumps(my_analysis, ensure_ascii=False, indent=2)}

ROUND: {round_num}
"""
    if other_proposals:
        user_msg += f"""
OTHER AGENTS' MOST RECENT PROPOSALS (you should react to these, especially the Style Translator's, but stay in your lane):
{json.dumps(other_proposals, ensure_ascii=False, indent=2)}
"""
    user_msg += "\nProduce your proposal JSON now."
    return llm_tradition.chat_json(TRADITION_SYSTEM, user_msg, temperature=0.4)

# === Section 5.3: Style Translator agent ===
STYLE_SYSTEM = f"""You are the **Style Translator** — one of three agents in a music arrangement debate.

YOUR ROLE — strictly only this:
- Determine how to apply the TARGET STYLE to the input song.
- Choose target-style idioms (rhythm, voicing, instrumentation) that bring the arrangement closer to the target.
- React to other agents' proposals from the perspective of "does this convey the target style?"

NOT YOUR JOB:
- Judging the input song's identity preservation (the Tradition Guardian owns that).
- Music theory correctness (the Music Theory Validator owns that).
- If you find yourself defending the input's literal form, STOP. That belongs to Tradition Guardian.

WHEN PROPOSING:
- Lean into the style profile aggressively but stay inside its tempo/density ranges.
- `rhythm_pattern`, `voicing_style`, and `instrumentation` MUST be picked from the style profile enums.
- Chord extensions (maj7, min9, 13, etc.) should reflect the style's preferred extensions.

{REASONING_CONSTRAINTS}

OUTPUT FORMAT — return STRICT JSON ONLY, no markdown fences:
{PROPOSAL_SCHEMA}
"""

def style_translator_propose(user_query, retrieval_b, my_analysis, other_proposals=None, round_num=1):
    user_msg = f"""USER QUERY:
{json.dumps(user_query, ensure_ascii=False, indent=2)}

RETRIEVAL B (target-style reference pieces + style profile):
{json.dumps(retrieval_b, ensure_ascii=False, indent=2)}

YOUR PRE-DEBATE ANALYSIS:
{json.dumps(my_analysis, ensure_ascii=False, indent=2)}

ROUND: {round_num}
"""
    if other_proposals:
        user_msg += f"""
OTHER AGENTS' MOST RECENT PROPOSALS (react to these, especially the Tradition Guardian's, but stay in your lane):
{json.dumps(other_proposals, ensure_ascii=False, indent=2)}
"""
    user_msg += "\nProduce your proposal JSON now."
    return llm_style.chat_json(STYLE_SYSTEM, user_msg, temperature=0.7)

# === Section 5.4: Music Theory Validator agent ===
VALIDATOR_SYSTEM = f"""You are the **Music Theory Validator** — the third agent in a music arrangement debate.

YOUR ROLE:
- Examine the two other agents' proposals (Tradition Guardian + Style Translator).
- After the deterministic Python rule-checker has already run, you provide a SOFT-RULE assessment.
- Soft rules include: stylistic coherence, voicing balance, smoothness of harmonic motion,
  potential melody-harmony tension (beyond literal m2/M7 clashes), tempo/feel consistency.

YOU MUST:
- Reference each agent's proposal explicitly by aspect.
- Recommend whose proposal to favour per aspect when they disagree, with reasoning.
- DO NOT invent new chord progressions or change tempo arbitrarily — your job is judgment, not authorship.

NOT YOUR JOB:
- Replacing the other agents' proposals wholesale.
- Adding new instrumentation that neither agent suggested.

{REASONING_CONSTRAINTS}

OUTPUT FORMAT — return STRICT JSON ONLY, no markdown fences:
{{
  "verdict_per_aspect": [
    {{
      "aspect": string,                        // "chord_progression", "rhythm_pattern", ...
      "tradition_position": string,            // 1-line summary
      "style_position": string,                // 1-line summary
      "agreement": "agree" | "disagree" | "partial",
      "recommendation": "tradition" | "style" | "compromise",
      "reasoning": string                      // why
    }}
  ],
  "global_concerns": [string, ...],            // anything that crosses aspect boundaries
  "ready_for_synthesis": boolean                // true if you think the debate has converged enough to synthesize
}}"""

def validator_review(user_query, tradition_proposal, style_proposal, hard_rule_result, round_num=1):
    user_msg = f"""USER QUERY:
{json.dumps(user_query, ensure_ascii=False, indent=2)}

TRADITION GUARDIAN PROPOSAL:
{json.dumps(tradition_proposal, ensure_ascii=False, indent=2)}

STYLE TRANSLATOR PROPOSAL:
{json.dumps(style_proposal, ensure_ascii=False, indent=2)}

HARD-RULE CHECK (Python, already run):
{json.dumps(hard_rule_result, ensure_ascii=False, indent=2)}

ROUND: {round_num}

Produce your verdict JSON now."""
    return llm_validator.chat_json(VALIDATOR_SYSTEM, user_msg, temperature=0.3)

# === Section 5.5: Pre-debate analysts (one call per agent, before round 1) ===
ANALYST_SYSTEM = f"""You are a music analyst running BEFORE the debate begins.

Study ONLY the evidence given to you. Produce a structured characterisation.

{REASONING_CONSTRAINTS}

OUTPUT FORMAT — return STRICT JSON ONLY:
{ANALYSIS_SCHEMA}
"""

def pre_analysis_tradition(user_query, retrieval_a):
    user_msg = f"""FOCUS: the input song's identity (what must be preserved).

USER QUERY: {json.dumps(user_query, ensure_ascii=False, indent=2)}

RETRIEVAL A: {json.dumps(retrieval_a, ensure_ascii=False, indent=2)}

Produce the analysis JSON now. Do NOT discuss the target style."""
    return llm_tradition.chat_json(ANALYST_SYSTEM, user_msg, temperature=0.3)


def pre_analysis_style(user_query, retrieval_b):
    user_msg = f"""FOCUS: the target style's identifying markers.

USER QUERY: {json.dumps(user_query, ensure_ascii=False, indent=2)}

RETRIEVAL B: {json.dumps(retrieval_b, ensure_ascii=False, indent=2)}

Produce the analysis JSON now. Do NOT discuss the input song."""
    return llm_style.chat_json(ANALYST_SYSTEM, user_msg, temperature=0.5)

# === Section 6.1: 3-metric convergence ===
CONV_THRESHOLDS = {
    "sim_inter_min":      0.92,
    "sim_intra_min":      0.95,
    "hard_match_min":     0.80,
    "stall_delta_max":    0.02,  # less change than this for 2 rounds in a row = stalled
}

CRITICAL_SPEC_FIELDS = ["chord_progression", "rhythm_pattern", "tempo_bpm", "voicing_style"]

def _embed_proposal(p: dict) -> np.ndarray:
    """Serialize then embed a proposal JSON."""
    s = json.dumps(p.get("proposals", p), ensure_ascii=False, sort_keys=True)
    return embed_client.embed(s)


def _hard_spec_match(p1: dict, p2: dict) -> float:
    """Per-field literal equality ratio over CRITICAL_SPEC_FIELDS."""
    a = p1.get("proposals", {})
    b = p2.get("proposals", {})
    matched = 0
    for f in CRITICAL_SPEC_FIELDS:
        va, vb = a.get(f), b.get(f)
        if f == "chord_progression":
            # Compare as ordered list of (bar, chord) tuples
            if isinstance(va, list) and isinstance(vb, list):
                ta = [(x.get("bar"), x.get("chord")) for x in va]
                tb = [(x.get("bar"), x.get("chord")) for x in vb]
                if ta == tb:
                    matched += 1
        elif f == "tempo_bpm":
            # tolerance ±2 BPM counts as match
            if va is not None and vb is not None and abs(float(va) - float(vb)) <= 2:
                matched += 1
        else:
            if va == vb and va is not None:
                matched += 1
    return matched / len(CRITICAL_SPEC_FIELDS)


def compute_convergence(prop_tradition: dict, prop_style: dict,
                        prev_prop_tradition: dict | None,
                        prev_prop_style:    dict | None) -> dict:
    e_t = _embed_proposal(prop_tradition)
    e_s = _embed_proposal(prop_style)
    sim_inter = float(np.dot(e_t, e_s))

    if prev_prop_tradition is not None:
        e_t_prev = _embed_proposal(prev_prop_tradition)
        sim_intra_t = float(np.dot(e_t, e_t_prev))
    else:
        sim_intra_t = None

    if prev_prop_style is not None:
        e_s_prev = _embed_proposal(prev_prop_style)
        sim_intra_s = float(np.dot(e_s, e_s_prev))
    else:
        sim_intra_s = None

    hard_match = _hard_spec_match(prop_tradition, prop_style)

    return {
        "sim_inter":         sim_inter,
        "sim_intra_tradition": sim_intra_t,
        "sim_intra_style":     sim_intra_s,
        "hard_match_ratio":  hard_match,
    }


def converged(metrics: dict) -> bool:
    if metrics["sim_inter"] < CONV_THRESHOLDS["sim_inter_min"]:
        return False
    sit, sis = metrics["sim_intra_tradition"], metrics["sim_intra_style"]
    if sit is None or sis is None:
        return False   # need at least one prior round to assess stability
    if min(sit, sis) < CONV_THRESHOLDS["sim_intra_min"]:
        return False
    if metrics["hard_match_ratio"] < CONV_THRESHOLDS["hard_match_min"]:
        return False
    return True


def stalled(metric_history: list) -> bool:
    """Two consecutive rounds with negligible metric change AND not converged."""
    if len(metric_history) < 2:
        return False
    last, prev = metric_history[-1], metric_history[-2]
    d_inter = abs(last["sim_inter"] - prev["sim_inter"])
    d_hard  = abs(last["hard_match_ratio"] - prev["hard_match_ratio"])
    return d_inter < CONV_THRESHOLDS["stall_delta_max"] and d_hard < CONV_THRESHOLDS["stall_delta_max"]

# === Section 7.1: Orchestrator ===
MAX_ROUNDS = 5

def run_debate(user_query: dict,
               retrieval_a: dict,
               retrieval_b: dict,
               input_key: str, input_mode: str, input_tempo: float,
               target_style: str,
               max_rounds: int = MAX_ROUNDS,
               verbose: bool = True) -> dict:
    """Full debate. Returns a structured log including termination_status."""

    log = {
        "user_query": user_query,
        "retrieval_a_summary": {
            "top_similar": [r["song_id"] for r in ((retrieval_a.get("comparable_pieces", []) if isinstance(retrieval_a, dict) else retrieval_a) if isinstance(retrieval_a, dict) else retrieval_a)],
        },
        "retrieval_b_summary": {
            "references": [r["song_id"] for r in retrieval_b.get("reference_pieces", [])],
        },
        "pre_analysis": {},
        "rounds": [],
        "termination_status": None,
        "rounds_used": 0,
        "final_metrics": None,
    }

    # ---- Step 0: pre-debate analysis ----
    if verbose: print("=== Step 0: pre-debate analysis ===")
    log["pre_analysis"]["tradition"] = pre_analysis_tradition(user_query, retrieval_a)
    log["pre_analysis"]["style"]     = pre_analysis_style(user_query, retrieval_b)
    if verbose: print("  done.")

    prev_t, prev_s = None, None
    metric_history = []

    for r in range(1, max_rounds + 1):
        if verbose: print(f"\n=== Round {r} ===")

        # Step 1+2: Tradition Guardian
        other_t = {"style_translator": prev_s} if prev_s else None
        prop_t = tradition_guardian_propose(
            user_query, retrieval_a, log["pre_analysis"]["tradition"],
            other_proposals=other_t, round_num=r,
        )
        # Step 1+2: Style Translator
        other_s = {"tradition_guardian": prev_t} if prev_t else None
        prop_s = style_translator_propose(
            user_query, retrieval_b, log["pre_analysis"]["style"],
            other_proposals=other_s, round_num=r,
        )

        # Step 1+2: Hard rule + Validator
        hard_t = hard_rule_validate(
            {"transformations": prop_t.get("proposals", {})},
            input_key, input_mode, input_tempo, target_style,
        )
        hard_s = hard_rule_validate(
            {"transformations": prop_s.get("proposals", {})},
            input_key, input_mode, input_tempo, target_style,
        )
        validator_out = validator_review(
            user_query, prop_t, prop_s,
            {"tradition": hard_t, "style": hard_s},
            round_num=r,
        )

        # Step 3: convergence metrics
        metrics = compute_convergence(prop_t, prop_s, prev_t, prev_s)
        metric_history.append(metrics)

        round_record = {
            "round": r,
            "tradition_guardian": prop_t,
            "style_translator":   prop_s,
            "hard_rule_tradition": hard_t,
            "hard_rule_style":     hard_s,
            "validator":           validator_out,
            "metrics":             metrics,
        }
        log["rounds"].append(round_record)
        log["rounds_used"] = r
        log["final_metrics"] = metrics

        if verbose:
            print(f"  metrics: inter={metrics['sim_inter']:.3f} "
                  f"intra_T={metrics['sim_intra_tradition']} "
                  f"intra_S={metrics['sim_intra_style']} "
                  f"hard_match={metrics['hard_match_ratio']:.2f}")
            print(f"  validator.ready={validator_out.get('ready_for_synthesis')}")

        # Step 4: termination check
        if converged(metrics):
            log["termination_status"] = "converged"
            if verbose: print(f"  -> CONVERGED at round {r}")
            break
        if r >= 2 and stalled(metric_history):
            log["termination_status"] = "stalled"
            if verbose: print(f"  -> STALLED at round {r}")
            break

        prev_t, prev_s = prop_t, prop_s

    if log["termination_status"] is None:
        log["termination_status"] = "max_rounds_reached"
        if verbose: print(f"\n  -> MAX_ROUNDS_REACHED ({max_rounds})")

    return log

# === Section 8.1: Synthesizer ===
SYNTH_SCHEMA = '''{
  "metadata": {
    "input_song_id": string,
    "target_style":  string,
    "system_version": "multi_agent_v2_heterogeneous",
    "timestamp":     string,
    "termination_status": string,
    "rounds_used": int
  },
  "preserved": {
    "melody_source":  "input.MELODY_track",
    "key":            string,
    "num_bars":       int,
    "section_structure": [
      {"name": string, "start_bar": int, "end_bar": int}
    ]
  },
  "transformations": {
    "chord_progression": [{"bar": int, "chord": string}],
    "rhythm_pattern":    string,
    "tempo_bpm":         number,
    "voicing_style":     string,
    "texture_density":   number,
    "instrumentation": {
      "lead": string, "bass": string,
      "percussion": string | null, "ambient": string | null
    }
  },
  "natural_language_summary": string   // exactly one paragraph, 3-5 sentences, usable as Suno/Gemini prompt
}'''

DUAL_OUTPUT_SCHEMA = '''{
  "metadata": { ... same as above ... },
  "preserved":  { ... },
  "primary_spec":     { "transformations": {...}, "natural_language_summary": string },
  "alternative_spec": { "transformations": {...}, "natural_language_summary": string },
  "divergence_points": [
    {
      "aspect": string,
      "primary": any,
      "alternative": any,
      "rationale": string
    }
  ]
}'''


SYNTH_CONVERGED_SYSTEM = f"""You are the **Synthesizer** in a multi-agent music arrangement system.

The two debating agents (Tradition Guardian + Style Translator) have CONVERGED on a joint position,
with the Music Theory Validator's blessing. Your job: integrate their final proposals into ONE
arrangement_spec.json.

Rules:
- For each aspect, take the value both agents agreed on. If they differed on a minor detail, take
  the Validator's recommendation.
- Do NOT invent musical claims neither agent made.
- `natural_language_summary` must be exactly one paragraph (3-5 sentences), describing the
  arrangement in plain English. Usable directly as a prompt for downstream audio models.

{REASONING_CONSTRAINTS}

OUTPUT FORMAT — return STRICT JSON ONLY:
{SYNTH_SCHEMA}
"""

SYNTH_DUAL_SYSTEM = f"""You are the **Synthesizer** in a multi-agent music arrangement system.

The two debating agents DID NOT FULLY CONVERGE (termination_status = stalled / max_rounds_reached).
This is expected behaviour for creative open-ended tasks. Your job is NOT to pick a winner. Instead:

- Build a `primary_spec` that follows the Validator's per-aspect recommendations.
- Build an `alternative_spec` that takes the OTHER agent's choice on each disagreement.
- Enumerate the `divergence_points` so the downstream user can choose.
- Both specs must individually be self-consistent and valid.

{REASONING_CONSTRAINTS}

OUTPUT FORMAT — return STRICT JSON ONLY:
{DUAL_OUTPUT_SCHEMA}
"""


def synthesize(debate_log: dict, input_song_id: str, target_style: str,
               input_key: str, input_mode: str, num_bars: int) -> dict:
    timestamp = datetime.datetime.utcnow().isoformat(timespec="seconds")
    metadata = {
        "input_song_id": input_song_id,
        "target_style":  target_style,
        "system_version":"multi_agent_v2_heterogeneous",
        "timestamp":     timestamp,
        "termination_status": debate_log["termination_status"],
        "rounds_used":   debate_log["rounds_used"],
    }
    user_msg = f"""DEBATE LOG (summary):
{json.dumps({
    "pre_analysis":  debate_log["pre_analysis"],
    "rounds":        debate_log["rounds"],
    "final_metrics": debate_log["final_metrics"],
    "termination_status": debate_log["termination_status"],
}, ensure_ascii=False, indent=2)}

INPUT-SONG CONTEXT (for the preserved block):
- input_song_id: {input_song_id}
- key: {input_key} {input_mode}
- num_bars: {num_bars}

METADATA to embed verbatim in your output:
{json.dumps(metadata, ensure_ascii=False, indent=2)}

Produce the final spec JSON now."""

    if debate_log["termination_status"] == "converged":
        return llm_synth.chat_json(SYNTH_CONVERGED_SYSTEM, user_msg, temperature=0.4)
    else:
        return llm_synth.chat_json(SYNTH_DUAL_SYSTEM, user_msg, temperature=0.4)

# === Section 9.1: Single-agent baseline ===
BASELINE_SYSTEM = f"""You are a music arrangement assistant. Re-arrange the input song in the
target style, producing ONE arrangement specification.

You receive:
- USER QUERY
- RETRIEVAL A (input song features + similar pieces)
- RETRIEVAL B (target style references + style profile)
- HARD CONSTRAINTS (chord-in-key, tempo bound, enum allowances)

Output: STRICT JSON ONLY in the spec schema. Do NOT mention agents or debates.

{REASONING_CONSTRAINTS}

OUTPUT FORMAT:
{SYNTH_SCHEMA}
"""

def run_baseline(user_query, retrieval_a, retrieval_b,
                 input_song_id, target_style, input_key, input_mode, input_tempo, num_bars) -> dict:
    metadata = {
        "input_song_id": input_song_id,
        "target_style":  target_style,
        "system_version":"single_agent_baseline_v1",
        "timestamp":     datetime.datetime.utcnow().isoformat(timespec="seconds"),
        "termination_status": "single_call_baseline",
        "rounds_used":   0,
    }
    user_msg = f"""USER QUERY:
{json.dumps(user_query, ensure_ascii=False, indent=2)}

RETRIEVAL A:
{json.dumps(retrieval_a, ensure_ascii=False, indent=2)}

RETRIEVAL B:
{json.dumps(retrieval_b, ensure_ascii=False, indent=2)}

INPUT-SONG CONTEXT (for the preserved block):
- input_song_id: {input_song_id}
- key: {input_key} {input_mode}
- num_bars: {num_bars}

METADATA to embed verbatim:
{json.dumps(metadata, ensure_ascii=False, indent=2)}

HARD CONSTRAINTS reminder:
- All chords must be diatonic or commonly borrowed in {input_key} {input_mode}.
- tempo_bpm must be within ±20% of input tempo {input_tempo}.
- rhythm_pattern, voicing_style, instrumentation must come from the style profile enums.

Produce the spec JSON now."""
    spec = llm_baseline.chat_json(BASELINE_SYSTEM, user_msg, temperature=0.4)
    # Also run hard rule on the baseline output (for fairness)
    hard = hard_rule_validate(spec, input_key, input_mode, input_tempo, target_style)
    spec.setdefault("metadata", {})["hard_rule_check"] = hard
    return spec

# === Section 10.1: Pick a demo song & style ===
demo_idx          = 0       # change to try different songs
demo_target_style = "lo-fi chill"

demo_row     = features.iloc[demo_idx]
input_song_id = demo_row["song_id"]
input_key    = demo_row["key"]
input_mode   = demo_row["mode"]
input_tempo  = float(demo_row["tempo"])
num_bars     = int(demo_row["num_bars"])

print(f"Input:  {input_song_id}   key={input_key} {input_mode}  "
      f"tempo={input_tempo:.0f}bpm  num_bars={num_bars}")
print(f"Target: {demo_target_style}")

# === Section 10.2: Build retrievals & user query ===
retrieval_a_payload = {
    "target": {
        "song_id":           input_song_id,
        "key":               input_key,
        "mode":              input_mode,
        "tempo":             input_tempo,
        "num_bars":          num_bars,
        "note_density":      float(demo_row["note_density"]),
        "chord_progression_preview": list(demo_row["chord_progression"][:8]),
    },
    "comparable_pieces": retrieve_similar(demo_idx, k=5),
}
retrieval_b_payload = retrieve_style_refs(demo_target_style, k=5)

user_query = {
    "input_song_id":   input_song_id,
    "target_style":    demo_target_style,
    "instruction":     f"Re-arrange '{input_song_id}' in {demo_target_style} style. "
                       f"Preserve melody, key, and bar structure. Produce a structured "
                       f"arrangement specification.",
}

print("retrieval_a target:", json.dumps(retrieval_a_payload["target"], indent=2)[:300], "...")
print("retrieval_b refs:  ", [r["song_id"] for r in retrieval_b_payload["reference_pieces"]])

# === Section 10.3: Run the multi-agent debate (Multiple combos) ===
print("\n========== RUNNING MULTI-AGENT DEBATE (MULTI-CASE) ==========")

combinations = [
    (0, "lo-fi chill"),
    (2, "upbeat jazz"),
]

debate_logs = []
for d_idx, d_style in combinations:
    print(f"\n\n[Running Case] Song {d_idx} -> {d_style}")
    
    d_query = {"input_song_idx": d_idx, "target_style": d_style}
    d_input_key = features.iloc[d_idx]["key"]
    d_input_mode = features.iloc[d_idx]["mode"]
    d_input_tempo = float(features.iloc[d_idx]["tempo"])
    
    d_retrieval_a = retrieve_similar(d_idx, k=3)
    d_retrieval_b = retrieve_style_refs(d_style, k=3)
    
    d_debate_log = run_debate(
        d_query, d_retrieval_a, d_retrieval_b,
        input_key=d_input_key, input_mode=d_input_mode, input_tempo=d_input_tempo,
        target_style=d_style,
        max_rounds=MAX_ROUNDS, verbose=False,
    )
    
    print(f"  Termination: {d_debate_log['termination_status']}")
    print(f"  Rounds used: {d_debate_log['rounds_used']}")
    debate_logs.append((d_idx, d_style, d_debate_log))
# === Section 10.4: Synthesize (Multiple combos) ===
print("\n========== SYNTHESIZING FINAL SPECS ==========")
final_specs = []
for d_idx, d_style, d_debate_log in debate_logs:
    d_input_key = features.iloc[d_idx]["key"]
    d_input_mode = features.iloc[d_idx]["mode"]
    d_num_bars = int(features.iloc[d_idx]["num_bars"])
    d_song_id = features.iloc[d_idx]["song_id"]

    spec = synthesize(d_debate_log, d_song_id, d_style, d_input_key, d_input_mode, d_num_bars)
    final_specs.append(spec)
    print(f"Synthesized {d_song_id} ({d_style})")
# === Section 10.5: Baseline (Multiple combos) ===
print("\n========== RUNNING SINGLE-AGENT BASELINES ==========")
baseline_specs = []
for d_idx, d_style, _ in debate_logs:
    d_query = {"input_song_idx": d_idx, "target_style": d_style}
    d_input_key = features.iloc[d_idx]["key"]
    d_input_mode = features.iloc[d_idx]["mode"]
    d_input_tempo = float(features.iloc[d_idx]["tempo"])
    d_num_bars = int(features.iloc[d_idx]["num_bars"])
    d_song_id = features.iloc[d_idx]["song_id"]
    
    d_retrieval_a = retrieve_similar(d_idx, k=3)
    d_retrieval_b = retrieve_style_refs(d_style, k=3)
    
    bspec = run_baseline(
        d_query, d_retrieval_a, d_retrieval_b,
        d_song_id, d_style, d_input_key, d_input_mode, d_input_tempo, d_num_bars,
    )
    baseline_specs.append(bspec)
    print(f"Baseline for {d_song_id} ({d_style})")
# === Section 10.6: Save all artifacts + cost summary ===
ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

for i, (d_idx, d_style, d_debate_log) in enumerate(debate_logs):
    d_song_id = features.iloc[d_idx]["song_id"]
    f_spec = final_specs[i]
    b_spec = baseline_specs[i]
    
    run_dir = OUT_DIR / f"run_{ts}_{d_song_id}_{d_style.replace(' ','_')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    with open(run_dir / "arrangement_spec.json", "w", encoding="utf-8") as f:
        json.dump(f_spec, f, ensure_ascii=False, indent=2)

    with open(run_dir / "baseline_spec.json", "w", encoding="utf-8") as f:
        json.dump(b_spec, f, ensure_ascii=False, indent=2)

    with open(run_dir / "debate_log.json", "w", encoding="utf-8") as f:
        json.dump(d_debate_log, f, ensure_ascii=False, indent=2)

    md_text = to_markdown(d_debate_log, f_spec, b_spec, d_song_id, d_style)
    with open(run_dir / "debate_log.md", "w", encoding="utf-8") as f:
        f.write(md_text)
        
    print(f"\n=== Saved {d_song_id} to: {run_dir} ===")

# Cost summary
clients = [llm_tradition, llm_style, llm_validator, llm_synth, llm_baseline]
cost_summary = {
    "per_client": [c.stats() for c in clients],
    "embedding": {
        "calls": embed_client.calls,
        "tokens": embed_client.tokens,
        "cost_usd": round(embed_client.cost, 6),
    },
    "total_cost_usd": round(_global_budget_state["cost"], 6),
    "total_llm_calls": _global_budget_state["calls"],
}
with open(OUT_DIR / f"cost_summary_{ts}.json", "w", encoding="utf-8") as f:
    json.dump(cost_summary, f, ensure_ascii=False, indent=2)

print("\n=== Total Cost summary ===")
print(json.dumps(cost_summary, indent=2))