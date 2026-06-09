"""
MusicPlaybook demo — POP909 or custom MIDI → arrangement → arranged.wav

Run from repo root:
    streamlit run demo/app.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from demo.custom_input import (
    CustomInputAssets,
    build_auto_spec,
    inspect_midi,
    list_midi_tracks,
    prepare_custom_assets,
)
from demo.debate_viz import render_debate_timeline, render_spec_json
from demo.paths import (
    ARTIFACTS_DIR,
    REPO_ROOT as ROOT,
    arranged_output_dir,
    find_cached_runs,
    load_json,
    load_songs,
    load_style_profiles,
    load_styles,
    pop909_midi_path,
    reference_wav_path,
    renderable_styles,
    run_artifacts,
    style_render_status,
)
from demo.debate_live import debate_prerequisites, run_live_debate
from demo.render_service import render_arrangement
from demo.theme import inject_snu_theme, snu_header

st.set_page_config(
    page_title="MusicPlaybook Demo",
    page_icon="🎹",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_snu_theme()


@st.cache_data
def cached_songs():
    return load_songs()


def _style_profiles_mtime() -> float:
    path = ARTIFACTS_DIR / "style_profiles.json"
    return path.stat().st_mtime if path.exists() else 0.0


@st.cache_data
def cached_styles(_mtime: float):
    """Reload when style_profiles.json changes (_mtime busts stale cache)."""
    return load_styles()


def init_session_state() -> None:
    defaults = {
        "run_dir": None,
        "debate_log": None,
        "arrangement_spec": None,
        "baseline_spec": None,
        "custom_assets": None,
        "custom_spec": None,
        "midi_inspection": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def load_run(run_dir: Path) -> None:
    artifacts = run_artifacts(run_dir)
    debate_path = artifacts["debate_log.json"]
    if debate_path is None:
        raise FileNotFoundError(f"No debate_log.json in {run_dir}")

    st.session_state.run_dir = run_dir
    st.session_state.debate_log = load_json(debate_path)
    spec_path = artifacts["arrangement_spec.json"]
    base_path = artifacts["baseline_spec.json"]
    st.session_state.arrangement_spec = (
        load_json(spec_path) if spec_path else None
    )
    st.session_state.baseline_spec = load_json(base_path) if base_path else None


def load_live_result(result) -> None:
    st.session_state.run_dir = result.session_dir
    st.session_state.debate_log = result.debate_log
    st.session_state.arrangement_spec = result.arrangement_spec
    st.session_state.baseline_spec = result.baseline_spec or None


def style_selector(styles: list[str]) -> str:
    style_labels = {}
    for style in styles:
        ok, _ = style_render_status(style)
        style_labels[style] = f"{style} {'🎵' if ok else '💬'}"

    target_style = st.selectbox(
        "Target style",
        styles,
        format_func=lambda s: style_labels[s],
        help="🎵 = WAV 렌더 가능",
    )

    profile = load_style_profiles().get(target_style, {})
    tempo_range = profile.get("tempo_range_bpm", [])
    if tempo_range:
        st.caption(f"Tempo range: {tempo_range[0]}–{tempo_range[1]} BPM")

    can_render, missing = style_render_status(target_style)
    if can_render:
        st.success("WAV 렌더 가능")
    else:
        st.warning(f"렌더 미지원: {', '.join(missing[:2])}")

    return target_style


def sidebar_pop909() -> tuple[str, str]:
    songs = cached_songs()
    if not songs:
        st.error("pop909_sample.csv not found")
        st.stop()

    song_labels = {s.label: s.song_id for s in songs}
    selected_label = st.selectbox("POP909 song", list(song_labels.keys()))
    song_id = song_labels[selected_label]
    song = next(s for s in songs if s.song_id == song_id)

    st.markdown("---")
    target_style = style_selector(cached_styles(_style_profiles_mtime()))

    st.markdown("---")
    st.markdown(
        f"**Key:** {song.key} {song.mode}  \n"
        f"**Tempo:** {song.tempo:.0f} BPM  \n"
        f"**Bars:** {song.num_bars}"
    )
    st.caption(f"MIDI: {'✅' if pop909_midi_path(song_id) else '❌'}")
    st.caption(f"WAV: {'✅' if reference_wav_path(song_id) else '❌'}")

    st.markdown("---")
    st.subheader("Multi-agent debate")

    prereq = debate_prerequisites()
    max_rounds = st.slider("Debate rounds", 1, 3, 2, help="라운드마다 LLM 호출 (~1–3분)")

    if prereq["ready"]:
        st.caption(f"Live debate 가능 · model `{prereq['model']}`")
        if st.button("Run live debate", type="primary", use_container_width=True):
            status = st.status("Running multi-agent debate…", expanded=True)
            log_box = status.empty()

            def on_status(msg: str) -> None:
                log_box.write(f"• {msg}")

            try:
                result = run_live_debate(
                    song.row_idx,
                    target_style,
                    max_rounds=max_rounds,
                    on_status=on_status,
                )
                load_live_result(result)
                status.update(
                    label=f"Debate complete (${result.cost_usd:.3f})",
                    state="complete",
                )
                st.success(f"Saved → `demo/sessions/{result.session_dir.name}`")
                st.rerun()
            except Exception as exc:
                status.update(label="Debate failed", state="error")
                st.error(str(exc))
    else:
        missing = []
        if not prereq["openai_api_key"]:
            missing.append("OPENAI_API_KEY")
        if not prereq["pop909_csv"]:
            missing.append("artifacts/pop909_sample.csv")
        st.warning(f"Live debate 불가: {', '.join(missing)}")
        st.caption("아래에서 캐시 로드 또는 JSON 업로드를 사용하세요.")

    st.markdown("**또는** 기존 결과 불러오기")
    runs = find_cached_runs(song_id=song_id, target_style=target_style)
    if runs:
        run_labels = {r.label: r.run_dir for r in runs}
        picked = st.selectbox("Cached run (outputs/)", list(run_labels.keys()))
        if st.button("Load cached debate", use_container_width=True):
            load_run(run_labels[picked])
            st.success("Loaded")
    else:
        st.caption("outputs/에 캐시된 토론 없음")

    uploaded = st.file_uploader(
        "Upload debate_log.json",
        type=["json"],
        help="토론만 업로드 시 spec은 별도 업로드 필요",
    )
    if uploaded is not None:
        st.session_state.debate_log = json.loads(uploaded.getvalue().decode("utf-8"))
        st.session_state.run_dir = None
        st.session_state.arrangement_spec = None
        st.session_state.baseline_spec = None

    up_spec = st.file_uploader("Upload arrangement_spec.json", type=["json"], key="up_spec_side")
    if up_spec:
        st.session_state.arrangement_spec = json.loads(up_spec.getvalue().decode("utf-8"))

    return song_id, target_style


def sidebar_custom() -> str:
    st.subheader("Upload files")
    midi_up = st.file_uploader("MIDI file *", type=["mid", "midi"], key="custom_midi")
    wav_up = st.file_uploader(
        "Reference WAV (optional)",
        type=["wav", "mp3"],
        help="없으면 업로드 MIDI로 30초 reference clip을 자동 생성합니다.",
        key="custom_wav",
    )
    chord_up = st.file_uploader(
        "chord_midi.txt (optional)",
        type=["txt"],
        help="POP909 형식: start end chord (예: 0.0 2.0 G:maj). 없으면 기본 코드로 채웁니다.",
        key="custom_chord",
    )

    melody_track_index: int | None = None
    source_tempo: float | None = None
    num_bars: int | None = None

    if midi_up is not None:
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as tmp:
            tmp.write(midi_up.getvalue())
            tmp_path = Path(tmp.name)
        try:
            tracks = list_midi_tracks(tmp_path)
            melody_track_index = st.selectbox(
                "Melody track",
                range(len(tracks)),
                format_func=lambda i: tracks[i],
            )
            inspection = inspect_midi(tmp_path, melody_track_index)
            st.session_state.midi_inspection = inspection

            c1, c2, c3 = st.columns(3)
            c1.metric("Tempo (est.)", f"{inspection.source_tempo_bpm:.0f}")
            c2.metric("Bars (est.)", inspection.num_bars)
            c3.metric("Notes", inspection.note_count)

            source_tempo = st.number_input(
                "Source tempo (BPM)",
                min_value=40.0,
                max_value=220.0,
                value=float(inspection.source_tempo_bpm),
                step=1.0,
            )
            num_bars = st.number_input(
                "Bars to arrange",
                min_value=1,
                max_value=256,
                value=int(inspection.num_bars),
                step=1,
            )
        finally:
            tmp_path.unlink(missing_ok=True)

    st.markdown("---")
    target_style = style_selector(cached_styles(_style_profiles_mtime()))

    profile = load_style_profiles().get(target_style, {})
    density_range = profile.get("texture_density_range", [0.4, 0.6])
    texture_density = st.slider(
        "Texture density",
        float(density_range[0]),
        float(density_range[1]),
        (density_range[0] + density_range[1]) / 2,
        0.05,
    )

    c_key, c_mode = st.columns(2)
    with c_key:
        key = st.selectbox("Key", ["C", "G", "D", "A", "E", "F", "Bb", "Eb", "Ab"])
    with c_mode:
        mode = st.selectbox("Mode", ["major", "minor"])

    default_chord = st.text_input(
        "Default chord (no chord file)",
        value="N",
        help="코드 파일 없을 때 모든 마디에 적용 (예: G:sus2, C:maj7)",
    )

    tempo_lo, tempo_hi = profile.get("tempo_range_bpm", [80, 100])
    target_tempo = st.slider(
        "Arrangement tempo (BPM)",
        float(tempo_lo),
        float(tempo_hi),
        float(max(tempo_lo, min(tempo_hi, source_tempo or tempo_lo))),
        1.0,
    )

    rhythm_opts = profile.get("rhythm_pattern_options", [])
    voicing_opts = profile.get("voicing_style_options", [])
    rhythm = (
        st.selectbox("Rhythm pattern", rhythm_opts) if rhythm_opts else None
    )
    voicing = (
        st.selectbox("Voicing style", voicing_opts) if voicing_opts else None
    )

    if st.button("Prepare custom input", type="primary", use_container_width=True):
        if midi_up is None:
            st.error("MIDI 파일을 업로드해 주세요.")
        else:
            try:
                assets = prepare_custom_assets(
                    midi_bytes=midi_up.getvalue(),
                    midi_filename=midi_up.name,
                    wav_bytes=wav_up.getvalue() if wav_up else None,
                    chord_bytes=chord_up.getvalue() if chord_up else None,
                    melody_track_index=melody_track_index,
                    source_tempo_bpm=source_tempo,
                    num_bars=num_bars,
                    default_chord=default_chord.strip() or "N",
                )
                spec = build_auto_spec(
                    song_id=assets.song_id,
                    target_style=target_style,
                    source_tempo_bpm=assets.source_tempo_bpm,
                    num_bars=assets.num_bars,
                    key=key,
                    mode=mode,
                    default_chord=default_chord.strip() or "N",
                    texture_density=texture_density,
                    target_tempo_bpm=target_tempo,
                    rhythm_pattern=rhythm,
                    voicing_style=voicing,
                )
                st.session_state.custom_assets = assets
                st.session_state.custom_spec = spec
                st.session_state.arrangement_spec = spec
                st.session_state.debate_log = None
                st.session_state.baseline_spec = None
                st.session_state.run_dir = None
                st.success(f"Ready: `{assets.work_dir.name}`")
            except Exception as exc:
                st.error(f"준비 실패: {exc}")

    return target_style


def section_custom_audio(target_style: str) -> None:
    assets: CustomInputAssets | None = st.session_state.custom_assets
    spec = st.session_state.custom_spec

    if assets is None or spec is None:
        st.info(
            "MIDI를 업로드하고 **Prepare custom input**을 누르면 "
            "자동으로 arrangement spec이 생성됩니다."
        )
        return

    st.subheader("Your input")
    col_in, col_spec = st.columns(2)
    with col_in:
        st.markdown("**Reference audio**")
        st.audio(str(assets.reference_wav))
        st.caption(f"MIDI: `{assets.normalized_midi.name}` · track {assets.melody_track_index}")
        st.caption(
            f"{assets.source_tempo_bpm:.0f} BPM · {assets.num_bars} bars · "
            f"`{assets.work_dir.relative_to(ROOT)}`"
        )
    with col_spec:
        render_spec_json(spec, "Auto-generated arrangement_spec")

    st.divider()
    st.subheader("Arranged output")

    can_render, missing = style_render_status(target_style)
    if not can_render:
        st.warning(f"렌더 미지원: {', '.join(missing)}")
        return

    out_dir = assets.work_dir / "arranged"
    existing = out_dir / "arranged.wav"

    if st.button("Generate arranged.wav", type="primary", key="custom_render"):
        with st.spinner("Rendering…"):
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".json", delete=False, encoding="utf-8"
                ) as tmp:
                    json.dump(spec, tmp, ensure_ascii=False, indent=2)
                    spec_path = Path(tmp.name)
                render_arrangement(
                    spec_path=spec_path,
                    out_dir=out_dir,
                    reference_wav=assets.reference_wav,
                    source_midi=assets.normalized_midi,
                    chord_annotation=assets.chord_file,
                    beat_annotation=assets.beat_file,
                    source_tempo_bpm=assets.source_tempo_bpm,
                )
                spec_path.unlink(missing_ok=True)
                st.success("Done!")
                st.rerun()
            except Exception as exc:
                st.error(f"Render failed: {exc}")

    if existing.exists():
        st.audio(str(existing))
        st.download_button(
            "Download arranged.wav",
            existing.read_bytes(),
            file_name="arranged.wav",
            mime="audio/wav",
        )
        midi_dl = out_dir / "arranged.mid"
        if midi_dl.exists():
            st.download_button(
                "Download arranged.mid",
                midi_dl.read_bytes(),
                file_name="arranged.mid",
                mime="audio/midi",
            )


def section_pop909_audio(song_id: str, target_style: str) -> None:
    st.subheader("Input audio")
    ref_wav = reference_wav_path(song_id)
    if ref_wav:
        st.audio(str(ref_wav))
        st.caption(f"`{ref_wav.relative_to(ROOT)}`")
    else:
        st.warning("Reference WAV not found.")

    st.divider()
    st.subheader("Arranged output")
    run_dir = st.session_state.run_dir
    debate_spec = st.session_state.arrangement_spec
    baseline_spec = st.session_state.baseline_spec

    if debate_spec is None and baseline_spec is None:
        st.info("캐시된 토론을 로드하거나 spec JSON을 업로드하세요.")
        col_u1, col_u2 = st.columns(2)
        with col_u1:
            up = st.file_uploader("arrangement_spec.json", type=["json"], key="up_debate")
            if up:
                debate_spec = json.loads(up.getvalue().decode("utf-8"))
        with col_u2:
            upb = st.file_uploader("baseline_spec.json", type=["json"], key="up_base")
            if upb:
                baseline_spec = json.loads(upb.getvalue().decode("utf-8"))

    can_render, missing = style_render_status(target_style)
    if not can_render:
        st.warning(f"렌더 미지원: {', '.join(missing)}")
        return
    if not ref_wav or not pop909_midi_path(song_id):
        st.error("MIDI 또는 reference WAV가 없습니다.")
        return

    for title, spec, variant_key in (
        ("Multi-agent (debate)", debate_spec, "debate"),
        ("Single-agent (baseline)", baseline_spec, "baseline"),
    ):
        if spec is None:
            continue
        st.markdown(f"#### {title}")
        out_dir = (
            arranged_output_dir(run_dir, variant_key)
            if run_dir
            else ROOT / "outputs" / "demo_live" / song_id / variant_key
        )
        existing = out_dir / "arranged.wav"
        if st.button(f"Generate — {title}", key=f"render_{variant_key}"):
            with st.spinner("Rendering…"):
                try:
                    with tempfile.NamedTemporaryFile(
                        mode="w", suffix=".json", delete=False, encoding="utf-8"
                    ) as tmp:
                        json.dump(spec, tmp, ensure_ascii=False, indent=2)
                        p = Path(tmp.name)
                    render_arrangement(p, out_dir, reference_wav=ref_wav)
                    p.unlink(missing_ok=True)
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
        if existing.exists():
            st.audio(str(existing))


def main() -> None:
    init_session_state()

    snu_header(
        "MusicPlaybook Arrangement Demo",
        "POP909 또는 직접 업로드 MIDI → Multi-agent debate → arranged.wav",
    )

    input_mode = st.sidebar.radio(
        "Input source",
        ["POP909 dataset", "Custom upload"],
        index=0,
    )

    if input_mode == "POP909 dataset":
        song_id, target_style = sidebar_pop909()
        is_custom = False
    else:
        target_style = sidebar_custom()
        song_id = ""
        is_custom = True

    if is_custom:
        tab_arrange, tab_specs = st.tabs(["Arrange", "Spec JSON"])
        with tab_arrange:
            st.markdown(
                "### Custom upload\n"
                "Multi-agent debate 없이 **스타일 프로필 기반 자동 spec**으로 바로 편곡합니다."
            )
            section_custom_audio(target_style)
        with tab_specs:
            if st.session_state.custom_spec:
                render_spec_json(st.session_state.custom_spec, "arrangement_spec.json")
                st.download_button(
                    "Download spec JSON",
                    json.dumps(st.session_state.custom_spec, ensure_ascii=False, indent=2),
                    file_name="arrangement_spec.json",
                    mime="application/json",
                )
            else:
                st.info("Prepare custom input를 먼저 실행하세요.")
    else:
        tab_debate, tab_specs, tab_audio = st.tabs(["Debate", "Specs", "Audio"])
        with tab_debate:
            if st.session_state.debate_log:
                render_debate_timeline(st.session_state.debate_log)
            else:
                st.info(
                    "사이드바 **Run live debate** (OPENAI_API_KEY) 또는 "
                    "캐시 로드 / debate_log.json 업로드"
                )
                demo_runs = find_cached_runs(song_id="POP909_026", target_style="lo-fi chill")
                if demo_runs and st.button("Quick load POP909_026 demo"):
                    load_run(demo_runs[0].run_dir)
                    st.rerun()
        with tab_specs:
            if st.session_state.arrangement_spec:
                render_spec_json(st.session_state.arrangement_spec, "arrangement_spec (debate)")
            if st.session_state.baseline_spec:
                render_spec_json(st.session_state.baseline_spec, "baseline_spec")
        with tab_audio:
            section_pop909_audio(song_id, target_style)


if __name__ == "__main__":
    main()
