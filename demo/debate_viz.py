"""Streamlit components for multi-agent debate visualization."""

from __future__ import annotations

import json
from typing import Any

import streamlit as st

AGENT_STYLES = {
    "tradition": {"label": "Tradition Guardian", "emoji": "🏛️", "color": "#083A7A"},
    "style": {"label": "Style Translator", "emoji": "🎧", "color": "#0C4DA2"},
    "validator": {"label": "Music Theory Validator", "emoji": "⚖️", "color": "#B8975A"},
}


def _proposal_summary(proposals: dict[str, Any]) -> dict[str, Any]:
    chords = proposals.get("chord_progression") or []
    preview = [
        f"bar {item.get('bar')}: {item.get('chord')}"
        for item in chords[:6]
    ]
    return {
        "tempo_bpm": proposals.get("tempo_bpm"),
        "rhythm_pattern": proposals.get("rhythm_pattern"),
        "voicing_style": proposals.get("voicing_style"),
        "texture_density": proposals.get("texture_density"),
        "instrumentation": proposals.get("instrumentation"),
        "chord_preview": preview,
        "chord_bars": len(chords),
    }


def _hard_rule_badge(passed: bool) -> str:
    return "✅ passed" if passed else "❌ failed"


def _agreement_badge(agreement: str) -> str:
    mapping = {
        "agree": "🟢 agree",
        "disagree": "🔴 disagree",
        "partial": "🟡 partial",
    }
    return mapping.get(agreement, agreement)


def render_retrieval_summary(debate_log: dict[str, Any]) -> None:
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Retrieval A — similar pieces**")
        similar = debate_log.get("retrieval_a_summary", {}).get("top_similar", [])
        if similar:
            st.write(", ".join(similar))
        else:
            st.caption("No summary available")
    with col_b:
        st.markdown("**Retrieval B — style references**")
        refs = debate_log.get("retrieval_b_summary", {}).get("references", [])
        if refs:
            st.write(", ".join(refs))
        else:
            st.caption("No summary available")


def render_pre_analysis(debate_log: dict[str, Any]) -> None:
    pre = debate_log.get("pre_analysis", {})
    if not pre:
        st.info("Pre-debate analysis not found in this log.")
        return

    col_t, col_s = st.columns(2)
    for col, key, agent_key in (
        (col_t, "tradition", "tradition"),
        (col_s, "style", "style"),
    ):
        block = pre.get(key, {})
        meta = AGENT_STYLES[agent_key]
        with col:
            st.markdown(
                f"### {meta['emoji']} {meta['label']}"
            )
            st.markdown(block.get("summary", "_No summary_"))
            traits = block.get("musical_traits", [])
            if traits:
                with st.expander("Musical traits", expanded=False):
                    for trait in traits:
                        st.markdown(f"**{trait.get('trait', 'Trait')}**")
                        st.caption(trait.get("evidence", ""))
            implications = block.get("implications_for_arrangement", [])
            if implications:
                with st.expander("Arrangement implications", expanded=False):
                    for item in implications:
                        st.markdown(f"- {item}")


def render_termination_banner(debate_log: dict[str, Any]) -> None:
    status = debate_log.get("termination_status", "unknown")
    rounds = debate_log.get("rounds_used", len(debate_log.get("rounds", [])))
    metrics = debate_log.get("final_metrics", {})

    status_labels = {
        "converged": ("✅ Converged", "success"),
        "stalled": ("⏸️ Stalled (no further improvement)", "warning"),
        "max_rounds_reached": ("🔁 Max rounds reached", "info"),
    }
    label, level = status_labels.get(status, (status, "info"))
    getattr(st, level)(f"**{label}** — {rounds} round(s)")

    if metrics:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Inter-agent similarity", f"{metrics.get('sim_inter', 0):.3f}")
        m2.metric("Tradition stability", f"{metrics.get('sim_intra_tradition', 0):.3f}")
        m3.metric("Style stability", f"{metrics.get('sim_intra_style', 0):.3f}")
        m4.metric("Hard-field match", f"{metrics.get('hard_match_ratio', 0):.2%}")


def render_agent_proposal(
    agent_key: str,
    agent_data: dict[str, Any],
    hard_rule: dict[str, Any] | None = None,
) -> None:
    meta = AGENT_STYLES[agent_key]
    st.markdown(f"#### {meta['emoji']} {meta['label']}")
    if hard_rule is not None:
        st.caption(f"Hard rules: {_hard_rule_badge(hard_rule.get('passed', False))}")
        for violation in hard_rule.get("violations", []):
            st.error(f"{violation.get('rule')}: {violation.get('detail')}")

    observations = agent_data.get("key_observations", [])
    if observations:
        st.markdown("**Observations**")
        for obs in observations:
            st.markdown(f"- {obs}")

    proposals = agent_data.get("proposals", {})
    summary = _proposal_summary(proposals)
    st.markdown("**Proposal**")
    st.json(summary)

    for field in ("reservations", "disagreements"):
        items = agent_data.get(field, [])
        if items:
            st.markdown(f"**{field.title()}**")
            for item in items:
                st.markdown(f"- {item}")


def render_validator(validator: dict[str, Any]) -> None:
    meta = AGENT_STYLES["validator"]
    st.markdown(f"#### {meta['emoji']} {meta['label']}")

    ready = validator.get("ready_for_synthesis")
    if ready is not None:
        st.caption("Ready for synthesis: " + ("✅ yes" if ready else "⏳ not yet"))

    verdicts = validator.get("verdict_per_aspect", [])
    for verdict in verdicts:
        aspect = verdict.get("aspect", "aspect")
        agreement = verdict.get("agreement", "")
        recommendation = verdict.get("recommendation", "")
        with st.expander(
            f"{aspect} — {_agreement_badge(agreement)} → **{recommendation}**",
            expanded=False,
        ):
            st.markdown(f"**Tradition:** {verdict.get('tradition_position', '')}")
            st.markdown(f"**Style:** {verdict.get('style_position', '')}")
            st.markdown(f"**Reasoning:** {verdict.get('reasoning', '')}")

    concerns = validator.get("global_concerns", [])
    if concerns:
        st.markdown("**Global concerns**")
        for concern in concerns:
            st.markdown(f"- {concern}")


def render_round(round_data: dict[str, Any]) -> None:
    round_num = round_data.get("round", "?")
    metrics = round_data.get("metrics", {})

    title = f"Round {round_num}"
    if metrics:
        title += (
            f" · sim={metrics.get('sim_inter', 0):.3f}"
            f" · hard_match={metrics.get('hard_match_ratio', 0):.0%}"
        )

    with st.expander(title, expanded=(round_num == 1)):
        col_t, col_s = st.columns(2)
        with col_t:
            render_agent_proposal(
                "tradition",
                round_data.get("tradition_guardian", {}),
                round_data.get("hard_rule_tradition"),
            )
        with col_s:
            render_agent_proposal(
                "style",
                round_data.get("style_translator", {}),
                round_data.get("hard_rule_style"),
            )
        st.divider()
        render_validator(round_data.get("validator", {}))


def render_debate_timeline(debate_log: dict[str, Any]) -> None:
    st.subheader("Multi-Agent Debate")
    render_retrieval_summary(debate_log)
    st.divider()
    st.markdown("### Step 0 — Pre-debate analysis")
    render_pre_analysis(debate_log)
    st.divider()
    render_termination_banner(debate_log)
    st.divider()
    st.markdown("### Debate rounds")
    for round_data in debate_log.get("rounds", []):
        render_round(round_data)


def render_spec_json(spec: dict[str, Any], title: str) -> None:
    st.markdown(f"### {title}")
    transform = spec.get("transformations")
    if transform is None and "primary_spec" in spec:
        transform = spec["primary_spec"].get("transformations")
    if transform:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Tempo", f"{transform.get('tempo_bpm', '?')} BPM")
        c2.metric("Rhythm", transform.get("rhythm_pattern", "?"))
        c3.metric("Voicing", transform.get("voicing_style", "?"))
        c4.metric("Density", transform.get("texture_density", "?"))
    with st.expander("Full JSON", expanded=False):
        st.code(json.dumps(spec, ensure_ascii=False, indent=2), language="json")
