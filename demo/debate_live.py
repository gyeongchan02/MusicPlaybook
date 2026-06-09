"""
Self-contained live multi-agent debate for the Streamlit demo.

Uses pop909_sample.csv + style_profiles.json only (no features.parquet).
Saves results under demo/sessions/ — does not modify outputs/ or artifacts/.
"""

from __future__ import annotations

import csv
import datetime
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np

from demo.paths import REPO_ROOT, load_style_profiles

SESSIONS_DIR = Path(__file__).resolve().parent / "sessions"
DEFAULT_MODEL = os.environ.get("DEBATE_MODEL", "gpt-4o-mini")
MAX_ROUNDS_DEFAULT = 3
COST_BUDGET_USD = float(os.environ.get("DEBATE_COST_BUDGET", "2.0"))

# --- shared schemas (from scratch_check) ---
REASONING_CONSTRAINTS = """REASONING CONSTRAINTS — follow strictly:
1. Do NOT assert features not present in the retrieved evidence.
2. `chord_progression_preview` is an opening excerpt, not the whole piece.
3. Mark creative suggestions explicitly.
4. STAY IN YOUR LANE per agent role.
"""

ANALYSIS_SCHEMA = """{
  "summary": string,
  "musical_traits": [{"trait": string, "evidence": string}],
  "implications_for_arrangement": [string]
}"""

PROPOSAL_SCHEMA = """{
  "key_observations": [string],
  "proposals": {
    "chord_progression": [{"bar": int, "chord": string}],
    "rhythm_pattern": string,
    "tempo_bpm": number,
    "voicing_style": string,
    "texture_density": number,
    "instrumentation": {"lead": string, "bass": string, "percussion": string|null, "ambient": string|null}
  },
  "reservations": [string],
  "disagreements": [string]
}"""

SYNTH_SCHEMA = """{
  "metadata": {...},
  "preserved": {...},
  "transformations": {...},
  "natural_language_summary": string
}"""

CONV_THRESHOLDS = {
    "sim_inter_min": 0.92,
    "sim_intra_min": 0.95,
    "hard_match_min": 0.80,
    "stall_delta_max": 0.02,
}
CRITICAL_SPEC_FIELDS = ["chord_progression", "rhythm_pattern", "tempo_bpm", "voicing_style"]

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
NAME_TO_PC = {n: i for i, n in enumerate(NOTE_NAMES)}
NAME_TO_PC.update({"Db": 1, "Eb": 3, "Gb": 6, "Ab": 8, "Bb": 10})
MAJOR_SCALE = [0, 2, 4, 5, 7, 9, 11]
MINOR_SCALE = [0, 2, 3, 5, 7, 8, 10]
BORROWED_MAJOR = [3, 8, 10]
BORROWED_MINOR = [4, 11]

_budget = {"cost": 0.0, "calls": 0}
_rows_cache: list[dict[str, Any]] | None = None


@dataclass
class LiveDebateResult:
    session_dir: Path
    debate_log: dict[str, Any]
    arrangement_spec: dict[str, Any]
    baseline_spec: dict[str, Any]
    cost_usd: float


def _load_openai_key() -> str | None:
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"]
    secret = Path.home() / ".secrets" / "openai_api_key"
    if secret.exists():
        key = secret.read_text().strip()
        if key:
            os.environ["OPENAI_API_KEY"] = key
            return key
    return None


def debate_prerequisites() -> dict[str, Any]:
    key = _load_openai_key()
    csv_ok = (REPO_ROOT / "artifacts" / "pop909_sample.csv").exists()
    styles_ok = (REPO_ROOT / "artifacts" / "style_profiles.json").exists()
    return {
        "openai_api_key": bool(key),
        "pop909_csv": csv_ok,
        "style_profiles": styles_ok,
        "model": DEFAULT_MODEL,
        "ready": bool(key) and csv_ok and styles_ok,
        "note": (
            "Live debate uses CSV-based retrieval (no features.parquet). "
            f"Model: {DEFAULT_MODEL}. Results saved to demo/sessions/."
        ),
    }


def _load_rows() -> list[dict[str, Any]]:
    global _rows_cache
    if _rows_cache is not None:
        return _rows_cache
    path = REPO_ROOT / "artifacts" / "pop909_sample.csv"
    with open(path, encoding="utf-8", newline="") as handle:
        _rows_cache = list(csv.DictReader(handle))
    return _rows_cache


def _chord_preview(song_id: str, max_tokens: int = 8) -> list[dict[str, Any]]:
    try:
        from arrangement_pipeline.pop909 import default_paths, parse_chord_file

        _, chord_path, _ = default_paths(REPO_ROOT, song_id)
        segs = parse_chord_file(chord_path)
        preview = []
        for seg in segs[:max_tokens]:
            preview.append({"start": seg.start, "end": seg.end, "chord": seg.symbol})
        return preview
    except Exception:
        return []


def _row_to_target(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "song_id": row["song_id"],
        "key": row["key"],
        "mode": row["mode"],
        "tempo": float(row["tempo"]),
        "num_bars": int(row["num_bars"]),
        "duration": float(row["duration"]),
        "note_density": 12.0,
        "chord_progression_preview": _chord_preview(row["song_id"]),
    }


def retrieve_similar_csv(row_idx: int, k: int = 3) -> list[dict[str, Any]]:
    rows = _load_rows()
    q = rows[row_idx]
    q_tempo = float(q["tempo"])
    scored: list[tuple[float, dict[str, Any]]] = []
    for i, row in enumerate(rows):
        if i == row_idx:
            continue
        score = 1.0 / (1.0 + abs(float(row["tempo"]) - q_tempo))
        if row["key"] == q["key"]:
            score += 0.25
        if row["mode"] == q["mode"]:
            score += 0.15
        scored.append((score, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {
            "song_id": r["song_id"],
            "score": float(s),
            "key": r["key"],
            "mode": r["mode"],
            "tempo": float(r["tempo"]),
            "note_density": 12.0,
            "chord_progression_preview": _chord_preview(r["song_id"]),
        }
        for s, r in scored[:k]
    ]


def retrieve_style_refs_csv(target_style: str, k: int = 3) -> dict[str, Any]:
    profiles = load_style_profiles()
    if target_style not in profiles:
        raise ValueError(f"Unknown style: {target_style}")
    prof = profiles[target_style]
    lo, hi = prof["tempo_range_bpm"]
    mid = (lo + hi) / 2.0
    rows = _load_rows()
    ranked = sorted(rows, key=lambda r: abs(float(r["tempo"]) - mid))
    refs = []
    tempos, ndens = [], []
    for row in ranked[:k]:
        refs.append({
            "song_id": row["song_id"],
            "similarity": 1.0 - abs(float(row["tempo"]) - mid) / max(hi - lo, 1),
            "key": row["key"],
            "mode": row["mode"],
            "tempo": float(row["tempo"]),
            "note_density": 12.0,
            "chord_progression_preview": _chord_preview(row["song_id"]),
        })
        tempos.append(float(row["tempo"]))
        ndens.append(12.0)
    return {
        "target_style": target_style,
        "clap_text_prompt": prof.get("clap_text_prompt", ""),
        "reference_pieces": refs,
        "aggregated_style_features": {
            "mean_tempo_of_refs": float(np.mean(tempos)) if tempos else mid,
            "tempo_std_of_refs": float(np.std(tempos)) if tempos else 0.0,
            "mean_note_density_of_refs": float(np.mean(ndens)) if ndens else 12.0,
            "preferred_chord_extensions": prof.get("preferred_chord_extensions", []),
            "rhythm_pattern_options": prof.get("rhythm_pattern_options", []),
            "voicing_style_options": prof.get("voicing_style_options", []),
            "tempo_range_bpm": prof.get("tempo_range_bpm", []),
            "texture_density_range": prof.get("texture_density_range", []),
            "instrumentation_options": prof.get("instrumentation_options", []),
        },
    }


class _LLM:
    def __init__(self, model: str, name: str, client: Any):
        self.model = model
        self.name = name
        self.client = client
        self.cost = 0.0
        self.calls = 0

    def chat_json(self, system: str, user: str, temperature: float = 0.5) -> dict:
        if _budget["cost"] > COST_BUDGET_USD:
            raise RuntimeError(f"Debate cost budget exceeded (${COST_BUDGET_USD})")
        pricing = {"in": 0.15, "out": 0.60}
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        usage = resp.usage
        cost = (
            usage.prompt_tokens * pricing["in"] / 1_000_000
            + usage.completion_tokens * pricing["out"] / 1_000_000
        )
        self.cost += cost
        _budget["cost"] += cost
        _budget["calls"] += 1
        self.calls += 1
        return json.loads(resp.choices[0].message.content)


class _Embed:
    def __init__(self, client: Any, model: str = "text-embedding-3-small"):
        self.client = client
        self.model = model

    def embed(self, text: str) -> np.ndarray:
        resp = self.client.embeddings.create(model=self.model, input=text)
        emb = np.array(resp.data[0].embedding, dtype=np.float32)
        return emb / (np.linalg.norm(emb) + 1e-9)


def _chord_in_key(chord: str, key: str, mode: str) -> bool:
    if not chord or chord == "N":
        return True
    m = re.match(r"^([A-Ga-g][#b]?)", chord.strip())
    if not m:
        return True
    root = m.group(1).capitalize()
    pc = NAME_TO_PC.get(root.replace("b", "b"))
    kpc = NAME_TO_PC.get(key.capitalize())
    if pc is None or kpc is None:
        return True
    rel = (pc - kpc) % 12
    if mode == "major":
        return rel in set(MAJOR_SCALE + BORROWED_MAJOR)
    return rel in set(MINOR_SCALE + BORROWED_MINOR)


def hard_rule_validate(
    spec: dict, input_key: str, input_mode: str, input_tempo: float, target_style: str
) -> dict:
    profiles = load_style_profiles()
    prof = profiles.get(target_style, {})
    violations, warnings = [], []
    t = spec.get("transformations", {})
    for entry in t.get("chord_progression", []):
        if not _chord_in_key(entry.get("chord", ""), input_key, input_mode):
            violations.append({"rule": "chord_in_key", "detail": entry.get("chord")})
    tempo = t.get("tempo_bpm")
    if tempo is not None:
        lo, hi = input_tempo * 0.8, input_tempo * 1.2
        if not (lo <= float(tempo) <= hi):
            violations.append({"rule": "tempo_bound", "detail": str(tempo)})
    rp = t.get("rhythm_pattern")
    if rp and rp not in prof.get("rhythm_pattern_options", []):
        violations.append({"rule": "rhythm_pattern_enum", "detail": rp})
    vs = t.get("voicing_style")
    if vs and vs not in prof.get("voicing_style_options", []):
        violations.append({"rule": "voicing_style_enum", "detail": vs})
    return {"passed": not violations, "violations": violations, "warnings": warnings}


def _hard_match(p1: dict, p2: dict) -> float:
    a, b = p1.get("proposals", {}), p2.get("proposals", {})
    matched = 0
    for field in CRITICAL_SPEC_FIELDS:
        va, vb = a.get(field), b.get(field)
        if field == "chord_progression":
            ta = [(x.get("bar"), x.get("chord")) for x in (va or [])]
            tb = [(x.get("bar"), x.get("chord")) for x in (vb or [])]
            if ta == tb:
                matched += 1
        elif field == "tempo_bpm":
            if va is not None and vb is not None and abs(float(va) - float(vb)) <= 2:
                matched += 1
        elif va == vb and va is not None:
            matched += 1
    return matched / len(CRITICAL_SPEC_FIELDS)


def _convergence(prop_t, prop_s, prev_t, prev_s, embed: _Embed) -> dict:
    e_t = embed.embed(json.dumps(prop_t.get("proposals", {}), sort_keys=True))
    e_s = embed.embed(json.dumps(prop_s.get("proposals", {}), sort_keys=True))
    sim_inter = float(np.dot(e_t, e_s))
    sim_intra_t = None
    sim_intra_s = None
    if prev_t:
        e_tp = embed.embed(json.dumps(prev_t.get("proposals", {}), sort_keys=True))
        sim_intra_t = float(np.dot(e_t, e_tp))
    if prev_s:
        e_sp = embed.embed(json.dumps(prev_s.get("proposals", {}), sort_keys=True))
        sim_intra_s = float(np.dot(e_s, e_sp))
    return {
        "sim_inter": sim_inter,
        "sim_intra_tradition": sim_intra_t,
        "sim_intra_style": sim_intra_s,
        "hard_match_ratio": _hard_match(prop_t, prop_s),
    }


def _converged(m: dict) -> bool:
    if m["sim_inter"] < CONV_THRESHOLDS["sim_inter_min"]:
        return False
    if m["sim_intra_tradition"] is None or m["sim_intra_style"] is None:
        return False
    if min(m["sim_intra_tradition"], m["sim_intra_style"]) < CONV_THRESHOLDS["sim_intra_min"]:
        return False
    return m["hard_match_ratio"] >= CONV_THRESHOLDS["hard_match_min"]


def _stalled(history: list[dict]) -> bool:
    if len(history) < 2:
        return False
    a, b = history[-1], history[-2]
    return (
        abs(a["sim_inter"] - b["sim_inter"]) < CONV_THRESHOLDS["stall_delta_max"]
        and abs(a["hard_match_ratio"] - b["hard_match_ratio"])
        < CONV_THRESHOLDS["stall_delta_max"]
    )


def run_debate(
    user_query: dict,
    retrieval_a: dict,
    retrieval_b: dict,
    input_key: str,
    input_mode: str,
    input_tempo: float,
    target_style: str,
    llms: dict[str, _LLM],
    embed: _Embed,
    max_rounds: int = MAX_ROUNDS_DEFAULT,
    on_status: Callable[[str], None] | None = None,
) -> dict:
    def status(msg: str) -> None:
        if on_status:
            on_status(msg)

    TRADITION_SYS = f"You are Tradition Guardian. {REASONING_CONSTRAINTS}\nJSON: {PROPOSAL_SCHEMA}"
    STYLE_SYS = f"You are Style Translator. {REASONING_CONSTRAINTS}\nJSON: {PROPOSAL_SCHEMA}"
    VALIDATOR_SYS = f"""You are Music Theory Validator. {REASONING_CONSTRAINTS}
Return JSON with verdict_per_aspect, global_concerns, ready_for_synthesis."""
    ANALYST_SYS = f"Pre-debate analyst. {REASONING_CONSTRAINTS}\nJSON: {ANALYSIS_SCHEMA}"

    log: dict[str, Any] = {
        "user_query": user_query,
        "retrieval_a_summary": {
            "top_similar": [r["song_id"] for r in retrieval_a.get("comparable_pieces", [])],
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

    status("Step 0: Pre-debate analysis…")
    log["pre_analysis"]["tradition"] = llms["tradition"].chat_json(
        ANALYST_SYS,
        f"INPUT retrieval:\n{json.dumps(retrieval_a, ensure_ascii=False)}\n"
        f"Query:\n{json.dumps(user_query, ensure_ascii=False)}",
        0.3,
    )
    log["pre_analysis"]["style"] = llms["style"].chat_json(
        ANALYST_SYS,
        f"STYLE retrieval:\n{json.dumps(retrieval_b, ensure_ascii=False)}\n"
        f"Query:\n{json.dumps(user_query, ensure_ascii=False)}",
        0.5,
    )

    prev_t, prev_s = None, None
    history: list[dict] = []

    for r in range(1, max_rounds + 1):
        status(f"Round {r}: agents proposing…")
        other_t = {"style_translator": prev_s} if prev_s else None
        prop_t = llms["tradition"].chat_json(
            TRADITION_SYS,
            json.dumps(
                {
                    "query": user_query,
                    "retrieval_a": retrieval_a,
                    "analysis": log["pre_analysis"]["tradition"],
                    "round": r,
                    "other": other_t,
                },
                ensure_ascii=False,
            ),
            0.4,
        )
        other_s = {"tradition_guardian": prev_t} if prev_t else None
        prop_s = llms["style"].chat_json(
            STYLE_SYS,
            json.dumps(
                {
                    "query": user_query,
                    "retrieval_b": retrieval_b,
                    "analysis": log["pre_analysis"]["style"],
                    "round": r,
                    "other": other_s,
                },
                ensure_ascii=False,
            ),
            0.7,
        )
        hard_t = hard_rule_validate(
            {"transformations": prop_t.get("proposals", {})},
            input_key, input_mode, input_tempo, target_style,
        )
        hard_s = hard_rule_validate(
            {"transformations": prop_s.get("proposals", {})},
            input_key, input_mode, input_tempo, target_style,
        )
        status(f"Round {r}: validator reviewing…")
        validator = llms["validator"].chat_json(
            VALIDATOR_SYS,
            json.dumps(
                {
                    "query": user_query,
                    "tradition": prop_t,
                    "style": prop_s,
                    "hard_rules": {"tradition": hard_t, "style": hard_s},
                    "round": r,
                },
                ensure_ascii=False,
            ),
            0.3,
        )
        metrics = _convergence(prop_t, prop_s, prev_t, prev_s, embed)
        history.append(metrics)
        log["rounds"].append({
            "round": r,
            "tradition_guardian": prop_t,
            "style_translator": prop_s,
            "hard_rule_tradition": hard_t,
            "hard_rule_style": hard_s,
            "validator": validator,
            "metrics": metrics,
        })
        log["rounds_used"] = r
        log["final_metrics"] = metrics

        if _converged(metrics):
            log["termination_status"] = "converged"
            status(f"Converged at round {r}")
            break
        if r >= 2 and _stalled(history):
            log["termination_status"] = "stalled"
            status(f"Stalled at round {r}")
            break
        prev_t, prev_s = prop_t, prop_s

    if log["termination_status"] is None:
        log["termination_status"] = "max_rounds_reached"
        status("Max rounds reached")

    return log


def synthesize_spec(
    debate_log: dict,
    song_id: str,
    target_style: str,
    input_key: str,
    input_mode: str,
    num_bars: int,
    llm: _LLM,
) -> dict:
    meta = {
        "input_song_id": song_id,
        "target_style": target_style,
        "system_version": "demo_live_debate",
        "timestamp": datetime.datetime.utcnow().isoformat(timespec="seconds"),
        "termination_status": debate_log["termination_status"],
        "rounds_used": debate_log["rounds_used"],
    }
    system = f"""Synthesizer: merge debate into one arrangement_spec JSON.
{REASONING_CONSTRAINTS}
Schema: metadata, preserved (key, num_bars), transformations, natural_language_summary."""
    user = json.dumps({
        "debate_log": {
            "pre_analysis": debate_log["pre_analysis"],
            "rounds": debate_log["rounds"],
            "final_metrics": debate_log["final_metrics"],
            "termination_status": debate_log["termination_status"],
        },
        "metadata": meta,
        "input_key": input_key,
        "input_mode": input_mode,
        "num_bars": num_bars,
    }, ensure_ascii=False)
    return llm.chat_json(system, user, 0.4)


def run_baseline_spec(
    user_query: dict,
    retrieval_a: dict,
    retrieval_b: dict,
    song_id: str,
    target_style: str,
    input_key: str,
    input_mode: str,
    input_tempo: float,
    num_bars: int,
    llm: _LLM,
) -> dict:
    system = f"""Single-agent baseline. One arrangement_spec JSON. {REASONING_CONSTRAINTS}"""
    user = json.dumps({
        "query": user_query,
        "retrieval_a": retrieval_a,
        "retrieval_b": retrieval_b,
        "song_id": song_id,
        "target_style": target_style,
        "key": input_key,
        "mode": input_mode,
        "tempo": input_tempo,
        "num_bars": num_bars,
    }, ensure_ascii=False)
    spec = llm.chat_json(system, user, 0.5)
    spec.setdefault("metadata", {})
    spec["metadata"].update({
        "input_song_id": song_id,
        "target_style": target_style,
        "termination_status": "single_call_baseline",
        "rounds_used": 0,
        "system_version": "demo_live_baseline",
    })
    return spec


def run_live_debate(
    row_idx: int,
    target_style: str,
    *,
    max_rounds: int = MAX_ROUNDS_DEFAULT,
    include_baseline: bool = True,
    on_status: Callable[[str], None] | None = None,
) -> LiveDebateResult:
    prereq = debate_prerequisites()
    if not prereq["ready"]:
        raise RuntimeError(
            "Live debate not ready. Need OPENAI_API_KEY + artifacts/pop909_sample.csv "
            "+ artifacts/style_profiles.json"
        )

    from openai import OpenAI

    client = OpenAI()
    llms = {
        "tradition": _LLM(DEFAULT_MODEL, "TraditionGuardian", client),
        "style": _LLM(DEFAULT_MODEL, "StyleTranslator", client),
        "validator": _LLM(DEFAULT_MODEL, "Validator", client),
        "synth": _LLM(DEFAULT_MODEL, "Synthesizer", client),
        "baseline": _LLM(DEFAULT_MODEL, "Baseline", client),
    }
    embed = _Embed(client)

    rows = _load_rows()
    if row_idx < 0 or row_idx >= len(rows):
        raise ValueError(f"row_idx {row_idx} out of range")
    row = rows[row_idx]
    song_id = row["song_id"]
    input_key, input_mode = row["key"], row["mode"]
    input_tempo = float(row["tempo"])
    num_bars = int(row["num_bars"])

    user_query = {
        "input_song_id": song_id,
        "target_style": target_style,
        "instruction": (
            f"Re-arrange '{song_id}' in {target_style} style. "
            "Preserve melody identity. Produce arrangement specification."
        ),
    }
    retrieval_a = {
        "target": _row_to_target(row),
        "comparable_pieces": retrieve_similar_csv(row_idx, k=3),
    }
    retrieval_b = retrieve_style_refs_csv(target_style, k=3)

    debate_log = run_debate(
        user_query, retrieval_a, retrieval_b,
        input_key, input_mode, input_tempo, target_style,
        llms, embed, max_rounds=max_rounds, on_status=on_status,
    )

    if on_status:
        on_status("Synthesizing arrangement_spec…")
    arrangement_spec = synthesize_spec(
        debate_log, song_id, target_style, input_key, input_mode, num_bars, llms["synth"],
    )

    baseline_spec: dict[str, Any] = {}
    if include_baseline:
        if on_status:
            on_status("Running single-agent baseline…")
        baseline_spec = run_baseline_spec(
            user_query, retrieval_a, retrieval_b,
            song_id, target_style, input_key, input_mode, input_tempo, num_bars,
            llms["baseline"],
        )

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = SESSIONS_DIR / f"{ts}_{song_id}_{target_style.replace(' ', '_')}"
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "debate_log.json").write_text(
        json.dumps(debate_log, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (session_dir / "arrangement_spec.json").write_text(
        json.dumps(arrangement_spec, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    if baseline_spec:
        (session_dir / "baseline_spec.json").write_text(
            json.dumps(baseline_spec, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    (session_dir / "cost_summary.json").write_text(
        json.dumps({"total_cost_usd": _budget["cost"], "calls": _budget["calls"]}, indent=2),
        encoding="utf-8",
    )

    return LiveDebateResult(
        session_dir=session_dir,
        debate_log=debate_log,
        arrangement_spec=arrangement_spec,
        baseline_spec=baseline_spec,
        cost_usd=_budget["cost"],
    )
