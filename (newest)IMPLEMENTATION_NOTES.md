# MusicPlaybook — Data & Multi-Agent Debate 구현 설명

본 문서는 `01_data_retrieval.ipynb` 와 `02_multi_agent_debate.ipynb` 두 노트북의 설계 결정과 구현 디테일을 정리합니다. **가이드 문서(MusicPlaybook_Data_MultiAgent_Guide.md)에서 결정된 사항을 코드로 옮긴 결과물**이며, 구현 단계에서 결정한 세부 사항이나 가이드와 다르게 간 부분만 본 문서가 새로 추가합니다.

---

## 0. 파일 구성

```
musicplaybook/
├── 01_data_retrieval.ipynb       # Data + Retrieval 전체 파이프라인
├── 02_multi_agent_debate.ipynb   # Multi-Agent Debate + Synthesis + Baseline
├── IMPLEMENTATION_NOTES.md       # (this file)
├── artifacts/                    # 01 노트북이 생성, 02 노트북이 소비
│   ├── pop909_sample.csv
│   ├── features.parquet
│   ├── clap_embeddings.npy
│   ├── song_index.csv
│   ├── style_profiles.json
│   ├── style_text_embeddings.npy
│   └── style_text_index.json
├── assets/                       # 01 노트북의 EDA 시각화 png
└── outputs/                      # 02 노트북의 데모 run 결과
    └── run_<timestamp>_<song>_<style>/
        ├── arrangement_spec.json     ← audio 팀 인계
        ├── baseline_spec.json        ← evaluation 팀 인계 (비교용)
        ├── debate_log.json           ← evaluation 팀 인계 (트레이스)
        ├── debate_log.md             ← presentation 팀 (demo 캡쳐용)
        └── cost_summary.json
```

---

## 1. 데이터셋 — POP909

### 1.1 출처 확인

- **논문**: Wang, Zhao, Jiang, Dong, Xiao, Zhou, Xia. *POP909: A Pop-song Dataset for Music Arrangement Generation*, ISMIR 2020. [arXiv:2008.07142](https://arxiv.org/abs/2008.07142)
- **저자 소속**: NYU Shanghai 음악 X-Lab 등.
- **GitHub**: `https://github.com/music-x-lab/POP909-Dataset`
- **라이선스**: 학술 연구 사용 허용 (논문 본문 명시).

### 1.2 용량 / 내용

- 압축 전 약 100 MB, git clone 시점 기준.
- **909곡 모두 MIDI(.mid) 포함**. 오디오(wav/mp3)는 **포함되지 않음** (저작권상 원곡 audio 배포 불가).
- 곡당 다음 파일들이 함께 들어있다:
  - `XXX.mid` — 3 트랙 분리된 MIDI (MELODY / BRIDGE / PIANO)
  - `chord_midi.txt`, `chord_audio.txt` — Harte 표기 코드 어노테이션
  - `beat_midi.txt`, `beat_audio.txt` — beat grid
  - `key_audio.txt` — key + mode

→ "audio가 필요한가?"에 대한 답은 **CLAP 임베딩을 만들기 위해 우리가 직접 wav로 렌더링**합니다. POP909 자체에는 wav가 없으니, **FluidSynth + General MIDI 사운드폰트**로 30초 wav를 생성한 뒤 임베딩을 추출합니다 (01 노트북 §5).

### 1.3 다운로드 코드

```bash
git clone --depth 1 https://github.com/music-x-lab/POP909-Dataset.git data/POP909-Dataset
```

01 노트북 §1.1 셀이 이를 자동 실행합니다.

---

## 2. 사용자 질문에 대한 답변 (요약)

발표 준비 중 논의된 핵심 질문들. 각 항목에 대한 상세 구현은 §3, §4에 있음.

| # | 질문 | 결론 |
|---|---|---|
| Q1 | 모든 debate가 다 수렴하나? | **수렴 강제 X, by design.** 3-metric 판정(`sim_inter`, `sim_intra`, `hard_match`)으로 `converged` / `stalled` / `max_rounds_reached` 3가지 종료 상태 분류. 미수렴 시 dual-output (primary + alternative). "정답 없는 창작 task"에 맞춘 reframing이 학술적 차별점. |
| Q2 | 파이프라인이 충분한가? | **MVP/데모로는 충분.** 입력→Retrieval→3-agent debate→Synthesis→spec.json 전 과정 동작. Hard rule(Python) + soft rule(Validator) 분리. Single-agent baseline 동봉으로 공정 비교 가능. 한계: threshold 튜닝, melody-clash는 spec-only 검출, section structure 단일. |
| Q3 | spec + 원본 MIDI로 실제 편곡 가능한가? | **Yes.** 두 경로 동시 제공 — (A) 구조화 필드(`chord_progression`, `tempo_bpm`, `voicing_style` 등) → MIDI 직접 조작 / (B) `natural_language_summary` → Suno·MusicLM 등 prompt-based 생성 모델. 오디오팀은 `arrangement_spec.json`만 받으면 됨. |
| Q4 | HITL은 어디에 들어가나? | **MVP엔 미구현, but architecture-ready.** 가장 자연스러운 진입점은 **dual-output 사용자 선택** — primary vs alternative 둘 다 들려준 뒤 사용자가 고름. "no-correct-answer" 내러티브와 가장 잘 맞음. 그 외 Synthesizer 직전 선택, 선택적 재토론, Streamlit spec 편집 등 4가지 후보. |
| Q5 | Multi-agent가 지금 기술적으로 prompting뿐인가? Grounding 같은 건 구현 안 된 거지? | **현재 구현은 prompting + retrieval 컨텍스트 + JSON 스키마 강제까지.** RAG처럼 외부 지식베이스에 접근하지는 않음 (벡터 검색은 곡 풀 내부에서만). 진정한 grounding(예: 음악 이론 KB, voice-leading rule engine과 LLM 결합)은 미구현 — 가이드 §7의 future work에 해당. 다만 **Validator의 hard-rule(Python)** 부분은 LLM 외부의 결정론적 규칙 검증이라는 점에서 light grounding으로 볼 여지는 있음. |

각 질문의 상세 근거 / 코드 위치는 §3 (01 노트북) 및 §4 (02 노트북)을 참조.

---

## 3. 01 노트북 (`01_data_retrieval.ipynb`) — 구현 디테일

### 3.0 셀 구성 한눈에 보기

총 47셀 (마크다운 12 + 코드 35). 위에서 아래로 순차 실행하면 끝.

| 섹션 | 셀 범위 | 무엇을 하는가 | 결과물 |
|---|---|---|---|
| §0 Setup | 1~4 | 라이브러리 + FluidSynth + soundfont 설치, 시드 고정 | 환경 준비 |
| §1 POP909 다운로드 | 5~7 | git clone `music-x-lab/POP909-Dataset` | 909곡 MIDI + 메타데이터 (~100MB) |
| §2 100곡 샘플링 | 8~11 | 4/4, 60~240s, 장조/단조 50:50 균형, seed=42 | `pop909_sample.csv` |
| §3 Feature 추출 | 12~17 | chord histogram(24d), pitch class(12d), rhythm 16-grid, note density, chord progression | `features.parquet` |
| §4 EDA | 18~22 | 5종 시각화 (tempo/key/chord/duration/density) | `assets/*.png` |
| §5 MIDI → wav | 23~27 | FluidSynth 30초 발췌 렌더링 (44.1kHz mono) | 100곡 wav |
| §6 CLAP 임베딩 | 28~31 | LAION-CLAP HTSAT-base, 512차원 audio embedding | `clap_embeddings.npy` |
| §7 Retrieval A (하이브리드) | 32~37 | 4채널 가중합 score (CLAP 0.4 + chord 0.3 + rhythm 0.2 + key 0.1) | `retrieve_similar()` 함수 |
| §8 Retrieval B (텍스트→오디오) | 38~41 | 4가지 스타일 텍스트 프롬프트 → CLAP text encoder | `style_profiles.json`, `style_text_embeddings.npy` |
| §9 Artifact 저장 | 42~47 | 02 노트북이 읽을 7개 파일을 `artifacts/`에 저장 | (다음 노트북의 입력) |

**핵심**: 01은 무거운 작업(다운로드, 임베딩 계산)을 한 번만 돌리고 디스크에 저장하는 역할. 02는 `artifacts/`만 있으면 01을 재실행할 필요 없음.

### 3.1 의존성과 환경 가정

- Colab 또는 로컬 Linux. Python 3.10+.
- 핵심 라이브러리: `pretty_midi`, `librosa`, `soundfile`, `laion-clap`, `torch`, `pyarrow`.
- 시스템 패키지: `fluidsynth` (MIDI → wav 렌더링 시 필요).
- CLAP 체크포인트(`630k-best.pt`, ~600MB)는 라이브러리가 자동 다운로드.

### 3.2 100곡 샘플링 정책 (가이드 §3.1.4)

| 필터 | 값 |
|---|---|
| 박자 | 4/4 only |
| 길이 | 60s ≤ duration ≤ 240s |
| 모드 | major 50 + minor 50 |
| 시드 | 42 |

`quick_midi_meta()` 함수가 909곡 전체를 빠르게 스캔(약 30초). 그 다음 필터 적용 후 balanced sampling.

### 3.3 트랙 매칭 (가이드 §3.2)

POP909는 instruments[0]=MELODY, [1]=BRIDGE, [2]=PIANO가 통상이지만 곡마다 미세하게 다릅니다. `resolve_tracks()`가 **이름 기반 우선, 인덱스 fallback** 정책으로 매칭합니다.

### 3.4 Feature Extraction

| Feature | Dim | 추출 위치 |
|---|---|---|
| `chord_histogram` | 24 (12 maj + 12 min) | `parse_chord_file()` — chord_midi.txt의 Harte 토큰을 정규화하고 시간 가중치로 누적 |
| `pitch_class_dist` | 12 | `melody_pitch_class_dist()` — MELODY 트랙의 note duration 가중 |
| `rhythm_pattern` | 16 | `rhythm_pattern_16()` — PIANO 트랙의 16분음표 grid 위 onset 평균 |
| `note_density` | 1 | PIANO 노트 수 / num_bars |

전부 numpy 벡터로 통합되어 batch cosine 계산이 가능.

### 3.5 EDA (§4)

5종 시각화:
1. Tempo 분포 (major vs minor)
2. Duration 분포
3. Mean melody pitch-class distribution (n=100)
4. Mean rhythm 16-step grid
5. Mean chord histogram (sorted)
6. 예시 곡 1개의 piano roll

전부 `assets/` 폴더에 PNG로 저장 — 발표 슬라이드에 그대로 삽입 가능.

### 3.6 MIDI → wav 렌더링 (§5)

- 사운드폰트 자동 탐색: `/usr/share/sounds/sf2/FluidR3_GM.sf2` 등 표준 위치
- 사운드폰트 없으면 `pretty_midi.synthesize()` (sine wave) fallback — CLAP 임베딩 품질이 다소 떨어지지만 retrieval 성능 유지
- 30초 / 44.1kHz / mono / peak-normalize -1dBFS

### 3.7 CLAP 임베딩 (§6)

- LAION-CLAP `HTSAT-base`, `enable_fusion=False`, 기본 체크포인트
- audio-to-audio (Retrieval A의 CLAP 채널) + text-to-audio (Retrieval B 전체) 둘 다 활용
- 모든 임베딩은 L2-normalize → cosine 유사도가 그대로 내적

### 3.8 Hybrid Retrieval (§7)

가이드 §3.4.1의 가중치를 그대로 사용:

```
score = 0.4 * cos(clap)
      + 0.3 * cos(chord_histogram)
      + 0.2 * cos(rhythm_pattern)
      + 0.1 * key_match_bonus
```

`retrieve_similar()`가 query_idx(인덱스에 이미 있는 곡) 또는 query_clap/chord/rhythm/key를 받아 top-K 반환. exclude_self 옵션으로 self-match 제거.

### 3.9 CLAP-text Retrieval (§8)

4종 target style 각각의 `clap_text_prompt`를 미리 임베딩해서 `style_text_embeddings.npy`에 저장. `retrieve_style_refs()`가 top-K 참조곡 + style profile prior를 함께 반환 → Style Translator agent의 evidence.

### 3.10 Retrieval A vs B — 어느 검색이 어느 agent로 가는가

02 노트북에서 토론을 시작하기 전에 두 검색이 **각각 다른 agent의 evidence**로 들어간다. 한 agent가 모든 검색 결과를 다 보는 것이 아니라 **역할에 맞는 정보만** 받는 구조:

| Retrieval | 입력 | 출력 | 소비자 (02 노트북의 어느 agent) | 목적 |
|---|---|---|---|---|
| **Retrieval A (하이브리드)** | 쿼리 곡 idx | Top-5 유사 POP909 곡 (음악적 특징이 비슷한 곡들) | **Tradition Guardian** | 원곡의 음악적 정체성(키, 코드, 리듬, 음색)을 파악하기 위한 reference. "이 곡과 비슷한 다른 팝송들은 어떤 화성/리듬을 쓰는가" |
| **Retrieval B (텍스트→오디오)** | target style 텍스트 | Top-5 해당 스타일의 reference 곡 + style profile prior | **Style Translator** | 타겟 스타일(lo-fi/jazz/cinematic/bossa)이 어떤 음색/리듬/voicing을 갖는지 파악. "lo-fi chill로 가려면 어떤 화성과 instrumentation을 써야 하는가" |
| (검색 결과 없음) | — | — | **Music Theory Validator** | Validator는 검색 정보를 받지 않고, 다른 두 agent의 proposal만 보고 음악 이론적 일관성 검증 |

이 **검색 분담**이 multi-agent의 핵심 설계. 한 agent에 모든 정보를 주면 single-agent와 다를 게 없어지기 때문에, 의도적으로 정보를 비대칭하게 분배함:

- Guardian은 "원곡 쪽 reference"만 봐서 보존 입장을 자연스럽게 취하게 됨
- Translator는 "타겟 스타일 쪽 reference"만 봐서 변환 입장을 자연스럽게 취하게 됨
- Validator는 한쪽 reference에 끌리지 않도록 검색을 안 줌

가이드 §4.3.1의 "역할 분리 + 정보 분리" 원칙. 발표에서 강조할 포인트.

---

## 4. 02 노트북 (`02_multi_agent_debate.ipynb`) — 구현 디테일

### 4.0 셀 구성 한눈에 보기

총 37셀 (마크다운 13 + 코드 24). 01의 `artifacts/`만 있으면 바로 실행 가능.

| 섹션 | 셀 범위 | 무엇을 하는가 |
|---|---|---|
| §0 OpenAI 키 로딩 | 1~3 | 환경변수 → Colab Secrets → 수동 입력 3단 fallback |
| §1 Artifacts 로드 | 4~6 | 01의 7개 파일 읽어서 메모리에 올림 |
| §2 Retrieval 함수 재정의 | 7~9 | `retrieve_similar()`, `retrieve_by_style_text()` (01과 동일, 노트북간 import 의존성 제거) |
| §3 LLMClient + 이종 백본 | 10~13 | 비용 추적 wrapper + 5개 agent 인스턴스화 (모델별로) |
| §4 Hard-rule Validator | 14~16 | Python 결정론적 검증 (key/tempo/enum) |
| §5 3 Agent + Pre-debate Analyst | 17~20 | 3개 agent의 system prompt 정의 + pre-analysis 함수 |
| §6 수렴 판정 3-metric | 21~23 | `sim_inter` / `sim_intra` / `hard_match` 계산 |
| §7 `run_debate()` 오케스트레이터 | 24~26 | Pre-analysis → 1~5 라운드 → 종료 |
| §8 `synthesize()` 분기 | 27~29 | converged → 단일 spec / 미수렴 → dual-output |
| §9 Single-agent Baseline | 30~32 | 공정 비교용 (동일 모델·스키마, 1회 LLM 호출, 트릭 없음) |
| §10 데모 실행 | 33~37 | 곡 1개 × 스타일 1개 → multi + baseline 동시 실행, `outputs/` 저장 |

### 4.0.1 Agent 구성 (이 노트북의 주연들)

3명의 토론자 + 1명의 종합자 + 1명의 비교 baseline. 모두 `LLMClient` 인스턴스로 §3 셀에서 만들어짐:

| Agent | Model | 역할 한 줄 | 검색 evidence | system prompt 핵심 |
|---|---|---|---|---|
| **Tradition Guardian** | `gpt-4o-mini` | 원곡 보존 | Retrieval A (유사 POP909 곡) | "PRESERVE original identity. Reject changes that erase the original." |
| **Style Translator** | `gpt-4o` | 타겟 스타일로 변환 | Retrieval B (target style reference) | "TRANSFORM into target style. Be bold." |
| **Music Theory Validator** | `gpt-3.5-turbo` | 이론 일관성 검증 | (검색 없음) | "Check chord-melody compatibility, voice leading. Side with whoever has better theory." |
| **Synthesizer** | `gpt-4o-mini` | 토론 결과 통합 → spec.json | (전체 라운드 히스토리) | "Produce a single arrangement_spec.json (or dual-output if not converged)." |
| **Baseline** | `gpt-4o-mini` | 단일 agent 비교군 | Retrieval A + B 모두 합쳐서 1회만 받음 | "Direct generation, no multi-step reasoning." |

**왜 모델을 분산했나**: 가이드는 GPT + Claude의 멀티 vendor를 권장했지만 우리에겐 OpenAI 키 1개라는 제약 → 같은 family 내에서 **세대(gpt-4o ↔ gpt-3.5-turbo ↔ gpt-4o-mini) 차이로 echo chamber 완화**. Claude 키 발급 시 `LLMClient(model="claude-...")` 1줄로 확장 가능.

### 4.0.2 토론은 총 몇 턴 진행하나?

**최소 1라운드 ~ 최대 5라운드.** 사전 단계 포함하면 다음 구조:

```
[Pre-debate Analysis]   ← Tradition Guardian, Style Translator 각자 1번
                          (Validator는 pre-analysis 없음)
        ↓
[Round 1]               ← T, S, V 각각 1번씩 발언 (총 3 LLM calls)
        ↓
[수렴 체크]              ← Round 1은 비교 대상이 없어서 skip
        ↓
[Round 2]               ← T, S, V 각각 1번. 이번엔 직전 라운드 + Validator 피드백 봄
        ↓
[수렴 체크]              ← sim_inter / sim_intra / hard_match 측정
        ↓
        ...최대 Round 5까지
        ↓
[Synthesizer]           ← 토론 종료 후 1번 호출, 최종 spec 생성
```

**종료 조건 3가지**:
- `converged`: 3-metric 모두 임계값 통과 → 단일 spec
- `stalled`: 2라운드 연속 metric 변화 < 0.02 → dual-output
- `max_rounds_reached`: 5라운드 도달 → dual-output

**LLM 호출 횟수 예상**:

| 시나리오 | Pre-analysis | Per round | Synthesizer | Baseline | 총 |
|---|---|---|---|---|---|
| 2라운드 수렴 | 2 (T+S) | 3 × 2 = 6 | 1 | 1 | **10 LLM + 2 embed** |
| 3라운드 일반 | 2 | 9 | 1 | 1 | **13 LLM + 4 embed** |
| 5라운드 최대 | 2 | 15 | 1 | 1 | **19 LLM + 8 embed** |

평균 약 12 LLM calls, 4o-mini 위주이므로 **1 run당 약 $0.05~0.20**.

### 4.0.3 Demo Cell 및 쿼리

§10 (셀 33~37)에 demo가 들어있음. **하드코딩된 단일 쿼리**:

```python
song_idx     = 0              # POP909 100곡 샘플 중 0번 곡 (편곡 대상)
target_style = "lo-fi chill"  # 4가지 스타일 중 첫 번째
```

이 쿼리로:
1. `run_debate(song_idx=0, target_style="lo-fi chill", max_rounds=5)` 호출 → multi-agent 토론 실행
2. `synthesize(...)` → 최종 spec 생성
3. `run_baseline(song_idx=0, target_style="lo-fi chill")` → baseline spec 생성
4. `outputs/run_<timestamp>_song0_lofichill/`에 5개 파일 저장:
   - `arrangement_spec.json` (또는 dual인 경우 primary/alternative)
   - `baseline_spec.json`
   - `debate_log.json` (전체 라운드 raw 로그)
   - `debate_log.md` (사람이 읽기 쉬운 마크다운, 발표 캡쳐용)
   - `cost_summary.json` (모델별 token/비용)

**다른 곡 / 다른 스타일로 돌리려면**: 셀 33의 `song_idx`, `target_style` 두 변수만 바꿔서 재실행. 가능한 `target_style` 값은 `style_profiles.json`에 정의된 4개 — `"lo-fi chill"`, `"upbeat jazz"`, `"cinematic ballad"`, `"bossa nova"`.

### 4.1 Heterogeneous Backbone — 핵심 차별점

가이드 §4.4는 GPT + Claude의 진정한 multi-vendor를 권장하지만, 우리에게 발급된 키가 OpenAI 1개라는 제약이 있습니다. 다음과 같이 **모델 세대를 분산**합니다:

| Agent | Model |
|---|---|
| Tradition Guardian | `gpt-4o-mini` |
| Style Translator   | `gpt-4o` |
| Music Theory Validator | `gpt-3.5-turbo` |
| Synthesizer        | `gpt-4o-mini` |
| Baseline           | `gpt-4o-mini` |

**왜 이렇게 매핑했는가**:
- `gpt-4o` (Style Translator) — 가장 강력한 모델을 가장 창의적 역할에 부여. 토큰 비용이 비싸므로 1개 agent에만 사용.
- `gpt-4o-mini` (Tradition Guardian) — 보수적 보존 역할이라 대형 모델이 굳이 필요하지 않음. 비용 절감.
- `gpt-3.5-turbo` (Validator) — 결정 일관성이 중요한 역할이므로 더 단순한 모델이 오히려 안정적. 검증 task는 작은 모델로도 충분.
- Synthesizer / Baseline은 동일 모델(`gpt-4o-mini`)로 공정 비교 보장.

이 매핑은 가이드 §4.4.2의 "echo chamber 완화" 효과를 부분적으로 얻습니다. 진정한 multi-vendor가 아니지만, **단일 모델 단일 prompting**의 중간발표 대비 분명한 진전입니다. Claude 키가 발급되면 `LLMClient(model="claude-sonnet-4-...")` 한 줄 변경으로 확장 가능 — 이 점이 architecture-level 차별점.

### 4.2 비용 추적

`LLMClient` 인스턴스마다:
- `calls`, `tokens_in`, `tokens_out`, `cost` 누적
- 전역 `_global_budget_state` 에서 모든 client의 합 추적
- `COST_BUDGET_USD = 5.00` (하드 캡, 초과 시 호출 차단)
- `WARN_AT_USD = 1.00` (경고 임계)

가격은 `MODEL_PRICING` 딕셔너리에 2026-05 기준으로 명시. 가격 변동 시 이 딕셔너리만 수정.

### 4.3 Hard-rule Validator (§4)

LLM 아닌 결정적 Python 함수:

| 규칙 | 함수 |
|---|---|
| chord-in-key (diatonic + borrowed) | `chord_in_key()` |
| tempo ±20% 범위 | `tempo_within_bounds()` |
| enum 위반 (rhythm_pattern / voicing_style) | `enum_check()` |
| melody clash | (현재 spec-only 검출; 향후 melody MIDI 추가 시 강화) |

`hard_rule_validate()`가 위 4종을 통합 호출하고 `{passed, violations, warnings}` 형태로 결과 반환. **Violation 시 LLM 판단 없이 reject** (가이드 §4.3.3).

### 4.4 3-Agent System Prompts (§5)

각 agent는 동일한 base 구조의 system prompt를 가집니다:

```
YOUR ROLE — strictly only this:
  - (역할 설명)

NOT YOUR JOB:
  - (다른 agent의 영역 명시 — 침범 방지)

WHEN PROPOSING:
  - (구체적 가이드라인)

REASONING_CONSTRAINTS (전 agent 공통):
  - 1. Don't assert features not in retrieved evidence
  - 2. chord_progression_preview is only the opening
  - 3. Separate retrieval from creative recommendation
  - 4. STAY IN YOUR LANE

OUTPUT FORMAT — STRICT JSON ONLY:
  (PROPOSAL_SCHEMA)
```

이 구조가 가이드 §4.3.1 의 "역할 분리" + 중간발표의 "NOT its job" 명시를 그대로 코드로 옮긴 것.

### 4.5 Round 1 vs Round 2+ (§7)

- **Round 1**: 두 agent가 서로의 출력을 못 봄 → 상호 오염 없는 initial position
- **Round 2+**: 직전 라운드의 상대 proposal + Validator 피드백을 받음 → 반박/동의/수정 가능

이는 중간발표 PDF p.10의 "Round 2 reacts to the other's draft" 구조를 유지하면서 Validator를 추가한 형태.

### 4.6 Convergence 3-Metric (§6)

```python
sim_inter > 0.92                    # 두 agent가 같은 결론에 도달
AND min(sim_intra_T, sim_intra_S) > 0.95   # 각자 의견이 안정
AND hard_match_ratio > 0.80         # 핵심 spec 필드 80% 이상 literal 일치
```

`compute_convergence()` 함수가 OpenAI `text-embedding-3-small` (저비용)로 proposal JSON을 임베딩 → cosine 유사도 계산. 임베딩 비용은 LLM 대비 무시할 수준 ($0.02/M tokens).

### 4.7 미수렴 방어 — Dual-Output (§8)

종료 상태가 `stalled` 또는 `max_rounds_reached`이면 Synthesizer에 다른 system prompt(`SYNTH_DUAL_SYSTEM`)를 전달:

- `primary_spec` — Validator 추천을 따른 spec
- `alternative_spec` — 다른 agent의 선택을 따른 spec
- `divergence_points` — 차이점 enumeration

이는 가이드 §4.7.2의 Layer 2 메커니즘 그대로.

### 4.8 Single-Agent Baseline (§9)

가이드 §6 차별 금지 사항 준수:
- 동일 입력 (Retrieval A + B 모두를 단일 prompt에 합쳐 전달)
- 동일 모델 (`gpt-4o-mini`, Tradition Guardian과 동일)
- 동일 스키마 (`SYNTH_SCHEMA` 그대로)
- 동일 hard rule 검증 (출력 후에도 hard_rule_validate 통과 요구)
- prompt engineering 트릭 금지 (CoT 강화, few-shot 추가 등)

평가팀이 multi-agent vs baseline pair를 받아 정성/정량 비교.

### 4.9 LLM 호출 횟수 (예상)

| 시나리오 | Pre-analysis | Per round | Synthesizer | Baseline | 총 |
|---|---|---|---|---|---|
| 2 rounds 수렴 | 2 (T+S) | 3 (T+S+V) × 2 = 6 | 1 | 1 | **10 LLM + 2 embed** |
| 3 rounds 일반 | 2 | 9 | 1 | 1 | **13 LLM + 4 embed** |
| 5 rounds 최대 | 2 | 15 | 1 | 1 | **19 LLM + 8 embed** |

평균 약 12 LLM calls + 4 embedding calls. 4o-mini 위주이므로 1 run당 **약 $0.05~0.20**. demo 5 케이스 + baseline 5 케이스 = $0.5~2.0 안에 끝남.

### 4.10 산출물 스키마

`arrangement_spec.json` — audio 팀 인계, 가이드 §5.1 의 스키마 그대로:

```json
{
  "metadata": { "input_song_id", "target_style", "system_version",
                "timestamp", "termination_status", "rounds_used" },
  "preserved": { "melody_source", "key", "num_bars", "section_structure" },
  "transformations": { "chord_progression", "rhythm_pattern", "tempo_bpm",
                       "voicing_style", "texture_density", "instrumentation" },
  "natural_language_summary": "3-5 sentence paragraph"
}
```

Dual-output 시:
```json
{
  "metadata", "preserved",
  "primary_spec":     { "transformations", "natural_language_summary" },
  "alternative_spec": { "transformations", "natural_language_summary" },
  "divergence_points": [ {aspect, primary, alternative, rationale}, ... ]
}
```

---

## 5. 실행 순서

### Day 0 (1회 실행)

```
# Colab 또는 로컬에서
1. 01_data_retrieval.ipynb 를 열고 위에서 아래로 전부 실행
   - POP909 clone (한 번)
   - 100곡 샘플링
   - feature 추출
   - EDA 시각화
   - 100곡 wav 렌더링 (~5-10분)
   - CLAP 임베딩 추출 (~3분 GPU / ~15분 CPU)
   - artifacts/ 폴더에 모든 산출물 저장
```

소요 시간: GPU 약 20분, CPU 약 40분. **이후 02 노트북은 artifacts만 읽으므로 빠름.**

### 매 실험마다

```
2. 02_multi_agent_debate.ipynb 열기
   - §10.1 에서 demo_idx, demo_target_style 변경
   - 위에서 아래로 실행
   - outputs/run_<timestamp>_<song>_<style>/ 에 결과 저장
```

소요 시간: 한 번 데모 약 1-3분 (API latency 포함), 비용 $0.05~0.20.

### Demo / 평가 데이터 수집

5/31~6/6 사이에 demo 시나리오 5~10개를 추려 batch 실행. `run_evaluation_batch.py` 같은 스크립트로 자동화 가능 (현 노트북 구조 그대로 loop만 추가).

---

## 6. 가이드 대비 결정 변경 사항

본 노트북에서 가이드와 다르게 결정한 부분만 기록합니다.

| 가이드 | 본 노트북 | 이유 |
|---|---|---|
| Backbone: GPT-4o + Claude Sonnet + GPT-4o | GPT-4o + GPT-4o-mini + GPT-3.5-turbo | OpenAI 키만 발급됨. Claude 사용 시 1줄 변경으로 확장 가능. |
| `text-embedding-3-small` for convergence | 동일 사용 | 가이드 그대로 |
| Threshold 50-run grid search | 디폴트 값 사용 (튜닝은 발표 직전) | 발표까지 충분한 시간 확보 후 §4.6.2 임계값을 50-run으로 튜닝 |
| Validator의 melody clash hard rule | spec-only 검증으로 약화, warning만 | 멜로디 MIDI 객체를 spec과 함께 전달하는 인터페이스 추가 필요. v2에서 구현. |
| 4-agent 확장 가능성 | 본 MVP는 3-agent 고정 | 가이드도 3-agent 권장. 4-agent는 Future Work. |

---

## 7. 알려진 한계 & 향후 작업

### 알려진 한계

1. **CLAP의 MIDI→wav 의존성** — POP909의 audio가 없어 직접 렌더링한 wav의 음색이 General MIDI 표준에 한정됨. 진짜 audio라면 더 정확한 임베딩 가능.
2. **chord_progression 8 마디 고정** — agent 출력이 opening 8 bars만. 전체 곡 (예: 32 bars)에 적용은 Synthesizer가 패턴 반복으로 처리. 곡 구조 인지 편곡은 v2.
3. **Validator 신뢰 한계** — 작은 모델(gpt-3.5-turbo)이므로 복잡한 음악 이론 판단에서 가끔 실수. Hard rule이 1차 안전망 역할.
4. **임계값 튜닝 미완** — 50-run grid search가 발표 직전 작업으로 남아 있음.

### 향후 작업 (가이드 §10 참고)

- 🔴 MERT (music-specific representation) 도입 — CLAP보다 음악 의미 표현이 정교
- 🔴 Claude key 확보 시 진정한 multi-vendor backbone
- 🔴 HITL UI (Streamlit) — dual-output user choice가 가장 자연스러운 진입점
- 🟡 Adaptive agent spawning — query 복잡도에 따라 agent 수 동적 결정
- 🟡 Selective re-debate — 특정 필드만 다시 토론

---

## 8. 산출물 체크리스트 (가이드 §3.5 + §4.8)

### Data Layer

- [x] `pop909_sample.csv` — 100곡 메타
- [x] `features.parquet` — symbolic features 전체
- [x] `clap_embeddings.npy` — (100, 512) audio embeddings
- [x] `song_index.csv` — row_idx ↔ song_id ↔ midi_path
- [x] `style_profiles.json` — 4 target style prior
- [x] `style_text_embeddings.npy` — (4, 512) text embeddings
- [x] `style_text_index.json` — style_name ↔ row_idx
- [x] `retrieve_similar()` / `retrieve_style_refs()` 함수
- [x] EDA 시각화 5종

### Multi-Agent Layer

- [x] `LLMClient` — heterogeneous backbone, cost tracking
- [x] `hard_rule_validate()` — Python 결정적 검증
- [x] 3 agent prompts + 호출 함수 (Tradition / Style / Validator)
- [x] Pre-debate analysts (1 call per side, before round 1)
- [x] `run_debate()` orchestrator — 1~5 rounds, convergence check
- [x] `compute_convergence()` — 3-metric
- [x] `synthesize()` — converged + dual-output 분기
- [x] `run_baseline()` — single-agent 공정 비교
- [x] End-to-end demo run + 산출물 저장

**Data & Multi-Agent Layer 완료.** 📦

---

본 문서는 living document. 구현 변경 시 §6 (결정 변경 사항) 표를 우선 업데이트.
