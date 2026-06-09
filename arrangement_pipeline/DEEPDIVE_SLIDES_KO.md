# [Team2] deepdive : 황사연 — Google Slides 붙여넣기용

> **만드는 법:** 팀원 deck([Oh](https://docs.google.com/presentation/d/1UXvMDwndeLoSNBcoEh5I-EpyFvIkQSvwVCTKm2rxC8c/) / [Hwang J.](https://docs.google.com/presentation/d/1fcjNNsV8Nk1FUVlZurVCnSmPqykkupUxG9PjItkEoho/)) **디자인만 복제** → 아래 순서대로 슬라이드 교체  
> 각 슬라이드 = 제목 1줄 + 본문 3~5줄만 (deepdive 형식)

---

# ═══ SECTION 0 — OPENING ═══

---

## Slide 01 | 표지 (섹션 없음)

**[Team2] deepdive : 황사연**

Arrangement Pipeline  
MusicPlaybook · 2026-1 Proj4DS Team 6

`github.com/gyeongchan02/MusicPlaybook`

`[레이아웃]` 팀원 표지와 동일 — 이름만 변경

---

## Slide 02 | 목차

**Contents**

1. Project Overview  
2. My Role & Scope  
3. Problem & Requirements  
4. System Design  
5. Implementation  
6. Demo & Results  
7. Issues & Takeaways  

`[레이아웃]` 팀원 목차 슬라이드 형식 그대로

---

## Slide 03 | 섹션 디바이더

**01**  
**Project Overview**

`[레이아웃]` 큰 숫자 + 섹션명만 (팀원 section slide)

---

## Slide 04 | 프로젝트 한 줄 (팀 공통)

**MusicPlaybook**

POP909 팝송 + Multi-Agent Debate → **편곡 스펙(JSON)** → (내 파트) **오디오**

- 01: 데이터·검색·CLAP  
- 02: 3-Agent debate → `arrangement_spec.json`  
- **Audio: spec → MIDI/WAV** ← 오늘 발표  

`[레이아웃]` 팀 전체 맥락 1장 — 다른 팀원 deepdive에도 있는 팀 소개 슬라이드

---

# ═══ SECTION 1 — MY ROLE ═══

---

## Slide 05 | 섹션 디바이더

**02**  
**My Role & Scope**

---

## Slide 06 | 담당 범위

**What I own**

| In scope | Out of scope |
|----------|----------------|
| `arrangement_pipeline/` 구현 | Multi-Agent / LLM debate |
| `arrangement_spec` → MIDI/WAV | CLAP·Retrieval (01) |
| POP909 beat/chord 정합 | Evaluation 지표 |

**Input:** `arrangement_spec.json` + POP909 `026.mid`  
**Output:** `arranged.mid`, `arranged.wav` (30s)

---

## Slide 07 | 팀 산출물 관계

**What I use / don't use**

```
02 Debate ──► arrangement_spec.json ──► [My Pipeline] ──► arranged.wav
              debate_log.json  ✗
              baseline_spec.json  (비교 실험 시만)
```

`[레이아웃]` 가운데 다이어그램 — 팀원이 쓰는 화살표 스타일 복사

---

# ═══ SECTION 2 — PROBLEM ═══

---

## Slide 08 | 섹션 디바이더

**03**  
**Problem & Requirements**

---

## Slide 09 | Problem

**Why build this?**

- Debate 결과는 **JSON** — 데모·평가에 **들을 수 있는 음악** 필요  
- POP909: **MELODY 유지**, 기존 BRIDGE/PIANO **제거**  
- Spec 스타일: lo-fi (`lofi_swung_16th`, `spread_with_9ths`)  
- **모듈형:** 스타일 추가 시 JSON만 수정  

---

## Slide 10 | Requirements

**Implementation checklist**

1. Read POP909 MIDI  
2. Preserve MELODY  
3. Parse `G:sus2` … (pychord)  
4. Generate bass + Rhodes (+ drums)  
5. Export `arranged.mid`  
6. FluidSynth → `arranged.wav`  
7. Same length as `wav_renders/*.wav` (30s)  

---

# ═══ SECTION 3 — DESIGN ═══

---

## Slide 11 | 섹션 디바이더

**04**  
**System Design**

---

## Slide 12 | Architecture

**Pipeline overview**

```
spec_loader → pipeline.py
     ↓
pop909 (MIDI) + timing (beat) + chords (Harte)
     ↓
accompaniment (bass / rhodes / drums)
     ↓
fluidsynth_render → arranged.wav
```

`[그림]` 박스 5개 가로 — 팀원 architecture 슬라이드와 동일 스타일

---

## Slide 13 | Design decision

**Key decisions**

| Decision | Reason |
|----------|--------|
| Spec-only input | Debate와 audio **관심사 분리** |
| `style_definitions.json` | Python 수정 없이 스타일 확장 |
| `beat_midi.txt` + CSV BPM | 멜로디·반주 **그리드 통일** |
| 30s WAV trim | 01 노트북 CLAP 클립과 **길이 정합** |

---

## Slide 14 | Module map

**`arrangement_pipeline/`**

- `spec_loader.py` — JSON  
- `timing.py` — beat grid ★  
- `chords.py` — pychord  
- `accompaniment.py` — 반주 생성  
- `style_definitions.json` — 스타일 DB  
- `run.py` — CLI  

---

# ═══ SECTION 4 — IMPLEMENTATION ═══

---

## Slide 15 | 섹션 디바이더

**05**  
**Implementation**

---

## Slide 16 | Impl — Spec

**① Spec → transformations**

- Converged spec: top-level `transformations`  
- 사용: `tempo_bpm`, `rhythm_pattern`, `voicing_style`,  
  `texture_density`, `chord_progression[]`  
- 미사용: `natural_language_summary`, `debate_log`

`[그림]` `arrangement_spec.json` 일부 스크린샷 (transformations만)

---

## Slide 17 | Impl — Melody & Beat

**② Melody + timing (core fix)**

**Before:** `estimate_tempo()` ≈ 150 → 멜로디만 압축, 반주 t=0  
**After:**
- Source BPM = `pop909_sample.csv` (**80**)  
- Downbeat = `beat_midi` **3열 = 1.0**  
- 멜로디·반주 **같은 beat grid**

`[그림]` `beat_midi.txt` 3줄 + downbeat 간격 3.0s 메모

---

## Slide 18 | Impl — Accompaniment

**③ Accompaniment generation**

- `lofi_swung_16th`: kick/snare/hat + swung 16th comp  
- `spread_with_9ths`: Rhodes voicing + 9th  
- `texture_density 0.45`: comp 밀도  

Tracks: **MELODY** | **rhodes_comp** | **upright_bass** | **drums**

---

## Slide 19 | Impl — Render

**④ FluidSynth render**

```bash
python3.10 -m arrangement_pipeline.run \
  --spec .../arrangement_spec.json \
  --out-dir .../arranged -v
```

- MIDI 전체 길이 저장  
- WAV = 앞 **30초** (reference `POP909_026.wav`와 동일 frames)

`[그림]` 터미널 `-v` 출력 캡처

---

# ═══ SECTION 5 — DEMO ═══

---

## Slide 20 | 섹션 디바이더

**06**  
**Demo & Results**

---

## Slide 21 | Demo case

**Demo run**

`outputs/run_20260528_173722_POP909_026_lo-fi_chill/`

- Song: POP909_026 · Style: lo-fi chill  
- Spec tempo: **76 BPM** (source 80)  
- `arranged.mid` / `arranged.wav`

---

## Slide 22 | Listen

**What to check**

1. 멜로디 윤곽 유지  
2. 반주 그루브가 **박자에 맞는지**  
3. 화성 변화 (G:sus2 → A:min → D:maj …)

`[그림/음원]` `arranged.wav` waveform 또는 발표 시 재생

---

## Slide 23 | Results table

**Outputs**

| Artifact | Role |
|----------|------|
| `arranged.mid` | DAW·추가 편집 |
| `arranged.wav` | 청취·CLAP 길이 맞춤 데모 |
| GitHub `arrangement_pipeline/` | 재현 가능 코드 |

---

# ═══ SECTION 6 — WRAP-UP ═══

---

## Slide 24 | 섹션 디바이더

**07**  
**Issues & Takeaways**

---

## Slide 25 | Issues solved

**Debugging history**

| Issue | Fix |
|-------|-----|
| WAV 안 바뀜 | `transformations`만 반영 |
| 엇박자 | beat 3열 + 메타 BPM |
| 1.5s “마디” | downbeat 파싱 수정 |
| WAV 길이 | 30s trim to `wav_renders` |

---

## Slide 26 | Limitations

**Still open**

- vinyl_crackle 미구현  
- pickup(1.125s) vs 화성 시작(4.125s)  
- full-length WAV 옵션 없음  

---

## Slide 27 | Takeaway

**3 takeaways**

1. **Spec → playable audio** 브릿지 완성  
2. **Beat-aligned** MIDI generation  
3. **JSON-driven** style engine  

---

## Slide 28 | End

**Thank you**

Q & A

황사연 · Arrangement Pipeline  
github.com/gyeongchan02/MusicPlaybook

---

# 부록 — 팀원 deck과 맞추는 체크리스트

- [ ] 파일명: `[Team2] deepdive : 황사연`  
- [ ] **총 28슬라이드** (섹션 디바이더 7개 포함) — 팀원이 25~30장이면 이 구성과 비슷  
- [ ] 섹션 슬라이드(03,05,08…) 배경·폰트 **팀 템플릿 복사**  
- [ ] Implementation 4장(16~19)에 **스크린샷 필수**  
- [ ] 발표 8분: Section 4·5에 4분 할당  

**팀원 slide 1장 스크린샷** 주시면 섹션 제목·장 수를 1:1로 다시 맞춰 드립니다.
