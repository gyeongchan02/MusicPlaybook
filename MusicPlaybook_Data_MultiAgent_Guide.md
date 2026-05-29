# MusicPlaybook: Data & Multi-Agent Debate 구현 가이드

본 문서는 팀 6 프로젝트 MusicPlaybook의 **Data & Retrieval** 영역과 **Multi-Agent Debate** 영역을 담당하는 한경찬·정예준이 이 문서만 보고 처음부터 끝까지 구현할 수 있도록 모든 결정 사항을 정리한 명세이다. 최종 발표는 2026년 6월 10일이며, 그 전까지의 모든 산출물 책임은 본 문서가 정의하는 두 영역에 한정된다.

본 문서를 다른 영역(Audio Rendering / Evaluation / Presentation) 담당자가 참고할 경우, 특히 §5의 출력 스키마(audio rendering 인터페이스)와 §7의 multi-agent 정당화 narrative(evaluation·presentation 협업)가 직접 인용된다.

---

## 1. 프로젝트 컨텍스트 정리

### 1.1 우리가 만드는 것

사용자가 입력한 곡(MIDI)을 사전 정의된 target style 중 하나로 재편곡하는 시스템. 핵심 차별점은 단일 LLM의 black-box 생성이 아니라, **여러 agent가 명시적 토론(debate)을 거쳐 구조화된 편곡 스펙(JSON)을 산출**한다는 점이다. 산출된 스펙은 audio rendering 단계로 인계되어 실제 들을 수 있는 결과물이 된다.

### 1.2 우리(Data + Multi-Agent 팀)가 책임지는 범위

| 책임 | 내용 |
|---|---|
| Data Layer | POP909 데이터셋 준비, feature extraction, CLAP 임베딩 인덱싱 |
| Retrieval Layer | 입력곡 유사 곡 검색, target style 참조곡 검색 |
| Debate Layer | 3-agent 토론 시스템, 수렴 판정, 미수렴 방어 |
| Synthesis Layer | 토론 결과를 단일 arrangement spec으로 통합 |
| Single-Agent Baseline | 비교 평가를 위한 minimal 1-call wrapper |
| 산출물 | `arrangement_spec.json` (audio 팀 인계), `debate_log.json` (평가팀 인계) |

### 1.3 우리가 책임지지 않는 범위

| 영역 | 담당 |
|---|---|
| MIDI/wav 변환, 음악 생성, 실제 audio rendering | Audio Rendering 팀 (황새연) |
| 정량/정성 평가 수행, 결과 분석 | Evaluation 팀 (박소연, 최현제) |
| 발표 자료 제작 | Presentation 팀 (박소연, 최현제) |

단, 우리는 §7의 multi-agent 정당화 narrative와 §6의 baseline 결과 페어를 evaluation·presentation 팀에 **인계**할 책임이 있다. "우리가 평가하지 않는다"가 "근거를 제공하지 않는다"는 아니다.

### 1.4 핵심 제약

- 파인튜닝 금지. 모든 LLM 사용은 inference-time (prompting + RAG).
- 외부 음악 생성 모델(Suno, MusicLM 등)에 대한 의존성은 audio 팀 영역이며, 본 시스템 출력은 그러한 모델에 인계 가능한 형태여야 한다.
- API 비용 한도는 팀 공통 자원이며, debate 1회당 평균 LLM 호출 횟수를 §4.5에서 추적한다.

---

## 2. 핵심 결정 사항 (요약 표)

본 문서 전반에 걸쳐 확정된 모든 결정을 한 곳에 모은 색인이다. 각 항목의 상세 근거는 해당 절을 참조한다.

| 항목 | 결정 | 근거 |
|---|---|---|
| 데이터셋 | POP909 (909곡 중 100곡 샘플) | §3.1 |
| Query 유형 | 1종 고정: `Re-arrange in {target_style} style` | §4.1 |
| Target styles | 4종: `lo-fi chill`, `upbeat jazz`, `cinematic ballad`, `bossa nova` | §4.1 |
| Preserve scope | 고정: melody, key, bar structure | §4.2 |
| Transform scope | 고정: chord voicing/sub, rhythm, tempo(±20%), texture, instrumentation | §4.2 |
| Agent 수 | 3개 (Tradition Guardian / Style Translator / Music Theory Validator) | §4.3 |
| LLM backbone | Heterogeneous: GPT(Tradition) + Claude(Style) + GPT(Validator) | §4.4 |
| 최대 라운드 | 5 (수렴 시 조기 종료) | §4.5 |
| 수렴 판정 | 3-metric 결합 (embedding sim + disagreement count + spec hard match) | §4.6 |
| 미수렴 방어 | Validator fallback + Dual-output mode + 종료 상태 명시 | §4.7 |
| Retrieval | Symbolic hybrid (chord/rhythm) + CLAP embedding의 가중 결합 | §3.4 |
| 인덱스 저장 | numpy + pandas (VectorDB 미사용, 909 규모) | §3.4 |
| Output 메인 | `arrangement_spec.json` (구조화) | §5 |
| Output 보조 | `debate_log.md` + `debate_log.json` | §5 |
| Single-agent baseline | 동일 입력·모델·스키마, 1-call wrapper | §6 |
| HITL 구현 | 본 MVP에서는 미구현, "architecture-ready"로 발표에 명시 | §10 |
| Audio rendering 인계 형식 | `arrangement_spec.json` + 인계 시점은 incremental | §8 |

---

## 3. Data & Retrieval Layer

### 3.1 데이터셋 — POP909

#### 3.1.1 다운로드

```bash
git clone https://github.com/music-x-lab/POP909-Dataset.git
```

키 불필요, 약 100MB. 라이선스는 학술 사용 가능.

#### 3.1.2 폴더 구조

```
POP909/
├── 001/
│   ├── 001.mid              # 3-track MIDI: MELODY / BRIDGE / PIANO
│   ├── beat_audio.txt       # beat grid (audio-aligned)
│   ├── beat_midi.txt        # beat grid (midi-aligned)
│   ├── chord_audio.txt      # chord annotations (audio-aligned)
│   ├── chord_midi.txt       # chord annotations (midi-aligned)
│   ├── key_audio.txt        # key
│   └── versions/            # alternative arrangements (사용 안 함)
├── 002/
└── ...909/
```

#### 3.1.3 본 프로젝트에 POP909가 적합한 이유

1. **MIDI가 melody / accompaniment 트랙으로 사전 분리** — preserve/transform 분리를 데이터 구조 차원에서 강제할 수 있다.
2. **Chord/key annotation이 시간 단위로 정확** — 추가 추정 불필요.
3. **인간 전문가의 편곡이 정답으로 존재** — evaluation의 reference로 활용 가능.

#### 3.1.4 샘플링 정책

909곡 전부 처리하지 않는다. 다음 기준으로 100곡 샘플링:

- `4/4` 박자만 (대다수가 4/4이며, 다른 박자는 시스템 일반화 부담)
- 곡 길이 60초 이상 240초 이하
- Major key와 minor key를 균형 있게 (50:50)
- 무작위 시드 고정 (`random_seed=42`)

결과: `pop909_sample.csv` (100 rows × metadata columns).

---

### 3.2 Feature Extraction

#### 3.2.1 추출 feature 표

| Feature | Type | Dim | 추출 도구 | 용도 |
|---|---|---|---|---|
| `key` | scalar (str) | 1 | `key_audio.txt` 파싱 | metadata, filter |
| `mode` | scalar (str) | 1 | key에서 derive (`major`/`minor`) | metadata |
| `tempo` | scalar (float) | 1 | `pretty_midi.get_tempo_changes()` | metadata |
| `num_bars` | scalar (int) | 1 | `beat_midi.txt` 파싱 | structure |
| `chord_histogram` | vector | 24 (12 major + 12 minor) | `chord_midi.txt` 정규화 | similarity |
| `pitch_class_dist` | vector | 12 | `pretty_midi`로 MELODY 트랙 분석 | similarity |
| `rhythm_pattern` | vector | 16 (16분음표 onset grid) | `pretty_midi`로 PIANO 트랙 분석 | similarity |
| `note_density` | scalar | 1 | PIANO 트랙 노트 수 / num_bars | similarity |
| `clap_embedding` | vector | 512 | LAION-CLAP, MIDI→wav 렌더링 후 | similarity (audio-domain) |

#### 3.2.2 추출 순서

```
1. POP909/XXX/key_audio.txt → key, mode
2. POP909/XXX/XXX.mid → pretty_midi 로드 → tempo, num_bars, pitch_class_dist, rhythm_pattern, note_density
3. POP909/XXX/chord_midi.txt → chord_histogram
4. POP909/XXX/XXX.mid → FluidSynth로 wav 렌더링 (44.1kHz, 30초 발췌)
5. 4번 wav → LAION-CLAP → clap_embedding
```

#### 3.2.3 저장 형식

- `features.parquet`: scalar/vector metadata (chord histogram, pitch class dist, rhythm pattern 포함)
- `clap_embeddings.npy`: shape `(100, 512)` numpy array
- `song_index.csv`: song_id ↔ array index 매핑

두 파일을 메모리에 로드한 채로 retrieval 함수가 동작한다. 909 규모에서는 brute-force 행렬곱이 가장 빠르다.

---

### 3.3 CLAP 임베딩

#### 3.3.1 라이브러리

```
pip install laion-clap pyfluidsynth pretty_midi
```

FluidSynth는 시스템 패키지(`apt install fluidsynth`)와 사운드폰트(`FluidR3_GM.sf2`, MuseScore 등에서 무료 배포)가 필요하다.

#### 3.3.2 임베딩 추출 절차

```
[Phase A: 사전 인덱싱, 1회 실행 — 약 30분~1시간]
1. 100개 .mid 파일을 30초 wav로 일괄 렌더링
2. CLAP_Module 로드 (체크포인트는 라이브러리에서 자동 다운로드)
3. wav 100개를 배치로 임베딩 → (100, 512) numpy array
4. clap_embeddings.npy로 저장
```

```
[Phase B: 입력곡 처리, retrieval 시점마다]
5. 입력 MIDI를 wav로 동일 방식 렌더링
6. CLAP 임베딩 추출 (1개, 512-dim)
7. 100개와 cosine similarity 계산 → top-K 반환
```

#### 3.3.3 텍스트 query CLAP의 활용

CLAP은 텍스트-오디오 cross-modal이다. 따라서 다음 두 방식이 모두 가능:

- **audio-to-audio**: 입력 MIDI(wav 변환) vs POP909 인덱스. 입력곡과 비슷한 곡을 retrieve.
- **text-to-audio**: `"upbeat jazz piano"` 같은 텍스트 → CLAP 텍스트 임베딩 → POP909 인덱스. **target style에 가까운 참조곡을 retrieve.**

후자는 `style_profiles.json`(§4.2.4)의 `clap_text_prompt` 필드를 텍스트 query로 사용해 구현한다.

---

### 3.4 Retrieval 함수 정의

두 종류의 retrieval이 필요하다.

#### 3.4.1 Retrieval A — 입력곡 features

**목적**: 입력곡을 시스템에 표현 가능한 형태로 변환하고, 선택적으로 비슷한 참조곡 K개를 함께 반환.

**입력**: 입력 MIDI 파일 경로, 데이터셋 인덱스.

**출력**:
```
{
  "target": {
    "song_id": ...,
    "key": ..., "tempo": ..., "num_bars": ...,
    "chord_progression": [...],    # 마디별 코드
    "melody_summary": {...},        # pitch class dist, contour 통계
    "structural_info": {...}        # 섹션 구조
  },
  "comparable_pieces": [
    {"song_id": ..., "similarity": 0.87, "scores": {...}},
    ...
  ]
}
```

**유사도 계산 (hybrid)**:
```
score = 0.4 * cos(clap_embedding_target, clap_embedding_candidate)
      + 0.3 * cos(chord_histogram_target, chord_histogram_candidate)
      + 0.2 * cos(rhythm_pattern_target, rhythm_pattern_candidate)
      + 0.1 * key_match_bonus
```

가중치는 50곡 ground-truth로 grid search 후 고정. 발표에서는 단순 cosine이 아닌 **multi-channel hybrid**로 어필.

#### 3.4.2 Retrieval B — Target style 참조곡

**목적**: target_style에 부합하는 POP909 곡 5개를 retrieve. 이 곡들은 Style Translator agent의 evidence가 된다.

**입력**: `target_style` (string, 4종 중 하나).

**처리**:
1. `style_profiles.json[target_style]["clap_text_prompt"]`를 가져옴
2. CLAP 텍스트 임베딩 추출
3. `clap_embeddings.npy`와 cosine similarity → top-5

**출력**:
```
{
  "target_style": "lo-fi chill",
  "clap_text_prompt": "lo-fi hip-hop chill beats, mellow piano, low tempo",
  "reference_pieces": [
    {"song_id": ..., "similarity": 0.74,
     "chord_progression": [...], "tempo": ...,
     "rhythm_pattern_summary": "..."},
    ...
  ],
  "aggregated_style_features": {
    "common_chord_extensions": ["maj9", "min11", ...],
    "typical_tempo_range": [70, 90],
    "rhythm_signature": "..."
  }
}
```

`aggregated_style_features`는 5곡의 통계량 (예: 빈출 코드 extension, 평균 tempo)로, agent prompt에 prior로 주입된다.

#### 3.4.3 인덱스 저장소 결정

**VectorDB(FAISS, Chroma, Pinecone) 미사용.** 100~909 규모에서 numpy 행렬곱이 압도적으로 빠르며, 의존성을 줄이는 게 디버깅·재현에 유리하다. 발표에서는 "**현 규모에서는 brute-force가 최적, VectorDB는 dataset scaling 시 도입할 expansion**"으로 명시 (중간발표 PDF p.18의 Next Expansion 라인과 일치).

---

### 3.5 Data Layer 산출물 체크리스트

다음 파일들이 모두 존재하고 정상 로드되면 Data Layer 완료:

- [ ] `pop909_sample.csv` — 100곡 메타 (song_id, key, tempo, num_bars, ...)
- [ ] `features.parquet` — symbolic features (chord histogram, rhythm pattern, ...)
- [ ] `clap_embeddings.npy` — `(100, 512)` numpy array
- [ ] `song_index.csv` — song_id ↔ array index
- [ ] `style_profiles.json` — 4 styles의 text prompt + prior
- [ ] `retrieval_a.py`, `retrieval_b.py` — 두 함수 구현
- [ ] `tests/` — 각 함수에 대한 unit test 1개씩 (입력 1개, 정상 출력 확인)

---

## 4. Multi-Agent Debate Layer

### 4.1 Query 정의 — 단일 유형으로 고정

사용자 입력은 다음 두 변수만 받는다:

```
{
  "input_song_id": "POP909_042",
  "target_style": "lo-fi chill"
}
```

`target_style`은 다음 4종에 한정:

| target_style | 직관적 설명 | CLAP text prompt 예시 |
|---|---|---|
| `lo-fi chill` | 차분한 로파이 힙합 비트 | `"lo-fi hip-hop chill beats, mellow piano, low tempo"` |
| `upbeat jazz` | 경쾌한 재즈 트리오 | `"upbeat jazz piano trio, swing rhythm, walking bass"` |
| `cinematic ballad` | 영화 OST 발라드 | `"cinematic piano ballad, orchestral strings, emotional"` |
| `bossa nova` | 보사노바 | `"bossa nova, brazilian guitar, soft latin rhythm"` |

다른 query 유형(작곡가 변경, 악기만 변경, 코드만 변경 등)은 본 MVP에서 지원하지 않는다. 발표 demo에서는 1~2개 곡 × 2~3개 style의 케이스를 보여준다.

#### 4.1.1 왜 query 유형을 하나로 고정하는가

- **평가 가능성**: 16개 조합(2^4) 또는 다중 query 유형은 정성평가(수업 학생 구글폼)에서 응답률 확보 불가.
- **Agent 구조 일관성**: query 유형이 늘어나면 agent role/criteria도 늘어나야 하며, 시스템 복잡도가 폭증.
- **Multi-agent의 본질적 강점 부각**: style 변환은 코드·리듬·텍스처·악기를 동시 조율하므로 agent 간 협상이 자연스럽게 발생.

---

### 4.2 Preserve / Transform Scope

모든 query에 대해 고정 적용한다. query 유형이 1개이므로 scope도 1개로 충분.

#### 4.2.1 Preserve (시스템이 코드 차원에서 강제)

- **MELODY 트랙** — 입력 MIDI의 MELODY 트랙은 그대로 보존된다. agent들은 melody를 수정하라고 제안할 수 없다 (스키마 차원에서 차단).
- **Key** — 조옮김 금지. 입력곡의 key를 그대로 유지.
- **Num bars / Section structure** — 곡 길이와 섹션 구조 보존.

#### 4.2.2 Transform 자유 영역 (agent들이 토론)

- 코드 voicing (어떻게 쌓을지, 자리바꿈)
- 코드 substitution (다른 코드로 치환, 단 key 안에서)
- 코드 extension (7th, 9th, 11th, 13th 추가)
- 리듬 패턴 (`style_profiles.json`의 enum 중 선택)
- 텍스처 밀도 (0.0~1.0)
- 악기 구성 (`style_profiles.json`의 enum 중 선택)
- 템포 변화 (입력 tempo의 ±20% 이내)

#### 4.2.3 회색지대 (실제 토론 대상)

토론의 본질은 transform 자유 영역 안에서의 **구체적 선택**이다:

- "bar 5의 Am을 Am7으로 갈까 Am9로 갈까?"
- "rhythm은 `lofi_swung_16th` vs `lofi_straight_8th`?"
- "voicing density는 0.4가 좋을까 0.6이 좋을까?"

#### 4.2.4 `style_profiles.json`

각 style의 prior knowledge를 외부 JSON으로 분리한다. agent system prompt가 이걸 참조.

```json
{
  "lo-fi chill": {
    "clap_text_prompt": "lo-fi hip-hop chill beats, mellow piano, low tempo",
    "tempo_range_bpm": [70, 90],
    "preferred_chord_extensions": ["maj7", "maj9", "min7", "min11"],
    "rhythm_pattern_options": ["lofi_swung_16th", "lofi_straight_8th"],
    "voicing_style_options": ["spread_with_9ths", "drop2_voicing"],
    "texture_density_range": [0.3, 0.5],
    "instrumentation_options": [
      {"lead": "rhodes_electric_piano", "bass": "upright_bass",
       "percussion": "lofi_brushed_kit", "ambient": "vinyl_crackle"}
    ]
  },
  "upbeat jazz": { ... },
  ...
}
```

이 prior가 명확할수록 agent 토론 scope가 좁아져 결과가 안정적이다.

---

### 4.3 Agent 정의 — 3-agent 구조

#### 4.3.1 Agent 역할

| Agent | 역할 | 입력 | 출력 책임 |
|---|---|---|---|
| **Tradition Guardian** | 입력곡의 정체성 보존. "이 변경이 원곡을 해치지 않는가" 판단. | Retrieval A (입력곡 + 유사곡) | 보존 우선 제안 + 다른 agent 제안에 대한 risk 평가 |
| **Style Translator** | Target style을 곡에 입힘. "어떻게 더 {style}답게 들리게 할까" 제안. | Retrieval B (target style 참조곡) + style_profiles | Style transformation 제안 |
| **Music Theory Validator** | 음악 이론 위반 검출. "이 코드가 키 안에 있나, 멜로디와 충돌하지 않나" 검증. | 위 두 agent의 출력 + hard rule 함수 | 위반 발생 시 reject + 사유 |

#### 4.3.2 Agent 수가 3개인 이유

- 2개(Tradition + Style)면 양자 대립만 발생하며, 누가 양보할지 판단할 메커니즘이 없다.
- 4개 이상은 토론이 산만해지고 LLM 호출 비용 증가.
- **Validator를 별도 agent로 두는 것은 Constitutional AI 패턴 (self-critique)을 multi-agent에 분산 적용한 것**이다. 음악 이론 검증은 hard rule(Python 함수)과 soft rule(LLM 판단) 모두 적용 가능하므로 별도 agent가 적합.

#### 4.3.3 Validator의 hard rule (Python 함수, LLM 아님)

다음 항목은 LLM이 아니라 결정적 Python 함수로 검증:

- 제안된 모든 코드가 input key의 diatonic 또는 well-known borrowed chord 내에 있는가
- 제안된 chord substitution이 그 마디의 melody note와 dissonant cluster를 만들지 않는가 (m2, M7 등의 노골적 충돌만 검출)
- tempo가 입력 tempo ±20% 범위 내에 있는가
- `style_profiles.json`의 enum 외 값이 출현하지 않는가

Hard rule 위반은 LLM 판단 없이 reject. Soft rule(스타일 적합성, 텍스처 균형 등)은 LLM이 판단.

---

### 4.4 LLM Backbone — Heterogeneous

#### 4.4.1 Backbone 할당

| Agent | Backbone | 근거 |
|---|---|---|
| Tradition Guardian | GPT-4o (또는 GPT-5 계열) | OpenAI 모델은 보수적·안전 성향이 강해 보존 역할에 적합 |
| Style Translator | Claude Sonnet 4 (또는 최신) | Anthropic 모델은 창의적 변형 제안에서 다른 편향을 가짐 |
| Music Theory Validator | GPT-4o (또는 가능하면 다른 backbone) | 결정 일관성이 중요하므로 모델 변경에 보수적 |

#### 4.4.2 왜 heterogeneous인가

동일 backbone의 2-3개 페르소나는 본질적으로 같은 분포에서 샘플링하므로 echo chamber가 발생한다. Liang et al. 2023 (arXiv:2305.19118, "Encouraging Divergent Thinking in Large Language Models through Multi-Agent Debate")이 이 문제를 정면으로 제기했으며, 후속 연구들이 multi-vendor backbone 도입을 권한다.

본 시스템에서 heterogeneous backbone은 1줄 코드 변경(client 인스턴스 교체)이지만 발표 임팩트가 크다. **중간발표 코드는 GPT 페르소나 2개였는데, 이 한 줄 변경만으로 "fundamentally different priors"가 토론에 들어온다.**

#### 4.4.3 비용 관리

- 개발 중에는 cheaper tier (예: gpt-4o-mini, claude haiku) 사용
- demo 1~2개 케이스만 본 tier로 실행
- baseline은 multi-agent와 동일 model로 fair comparison

---

### 4.5 Debate 진행 절차

#### 4.5.1 단계별 흐름

```
Step 0: Pre-debate analysis
    - Tradition Guardian: Retrieval A를 분석해 "보존 후보" JSON 작성 (1 LLM call)
    - Style Translator: Retrieval B + style_profiles를 분석해 "변환 후보" JSON 작성 (1 LLM call)
    
Step 1: Round 1
    - Tradition Guardian: 자기 분석만 보고 proposal 작성 (1 call)
    - Style Translator: 자기 분석만 보고 proposal 작성 (1 call)
    - Validator: 두 proposal에 hard rule + soft rule 적용 (Python + 1 call)

Step 2: Round 2~N
    - Tradition Guardian: 자기 분석 + Style Translator 직전 proposal + Validator 피드백 (1 call)
    - Style Translator: 자기 분석 + Tradition Guardian 직전 proposal + Validator 피드백 (1 call)
    - Validator: 갱신된 proposal에 룰 적용 (Python + 1 call)
    
    각 라운드 종료 시 convergence check (§4.6).
    converged 또는 N == MAX_ROUNDS(5) 또는 stalled면 종료.

Step 3: Synthesis
    - 최종 합의 proposal을 arrangement_spec.json으로 통합 (1 call)
```

#### 4.5.2 LLM 호출 횟수

| 시나리오 | Pre-debate | Round당 | Synthesis | 총 |
|---|---|---|---|---|
| 2 rounds (수렴 빠름) | 2 | 3 | 1 | 9 |
| 3 rounds (일반) | 2 | 3 | 1 | 12 |
| 5 rounds (최대) | 2 | 3 | 1 | 18 |

한 번의 demo run당 평균 12회 호출 가정. 4 styles × 곡 5개 × 2회(stability) = 40 runs → 약 480 calls 예상.

#### 4.5.3 Round 1 vs Round 2+ 차이

- **Round 1**: 두 agent가 서로의 출력을 못 봄. **상호 오염 없는 initial position** 확보. 각자 자기 evidence에서만 도출.
- **Round 2+**: 직전 라운드의 상대 proposal과 validator 피드백을 받음. 반박·동의·수정 가능.

이 분리는 중간발표 PDF p.10의 "Round 2 reacts to the other's draft" 구조를 유지한 것이다.

---

### 4.6 수렴 판정 — 3-metric 결합

#### 4.6.1 세 가지 메트릭

**Metric 1: Inter-agent embedding similarity**

라운드 N에서 두 agent의 proposal JSON을 문자열 직렬화 → OpenAI embedding API (`text-embedding-3-small`) → cosine similarity.

```
sim_inter = cos(emb(tradition_proposal_N), emb(style_proposal_N))
```

이 값이 높을수록 두 agent가 서로 같은 결론에 동의하고 있음을 의미.

**Metric 2: Intra-agent stability**

라운드 N과 N-1에서 같은 agent의 proposal 임베딩 cosine similarity. 변화가 적을수록 의견이 안정됨.

```
sim_intra_tradition = cos(emb(tradition_proposal_N), emb(tradition_proposal_{N-1}))
sim_intra_style    = cos(emb(style_proposal_N),     emb(style_proposal_{N-1}))
```

**Metric 3: Hard spec match**

`arrangement_spec.json`의 필수 필드(chord progression, rhythm pattern, tempo, voicing style)에 대해 두 agent의 제안이 **literal하게 동일한 값**을 가지는 비율.

```
hard_match_ratio = (필드 중 일치 개수) / (필수 필드 총 개수)
```

#### 4.6.2 수렴 정의

다음을 모두 만족 시 `converged`:

```
sim_inter > 0.92
AND
min(sim_intra_tradition, sim_intra_style) > 0.95
AND
hard_match_ratio > 0.80
```

임계값은 50개 demo run에서 실험적으로 튜닝. `evaluation/threshold_tuning.ipynb`에 결과 기록.

#### 4.6.3 종료 상태 분류

| 상태 | 조건 | 후속 처리 |
|---|---|---|
| `converged` | 위 세 조건 모두 만족 | Synthesis로 진행 |
| `stalled` | 2라운드 연속 metric이 거의 변하지 않으나 수렴 조건은 미달 | 미수렴 방어 모드 (§4.7) |
| `max_rounds_reached` | 5라운드 도달 | 미수렴 방어 모드 |

종료 상태는 `debate_log.json`의 `termination_status` 필드에 기록된다.

---

### 4.7 미수렴 방어 (Non-Convergence Handling)

#### 4.7.1 발표 메시지 (정답이 없는 문제 차별점)

본 시스템은 정답이 있는 reasoning task에 multi-agent debate를 적용한 Du et al. 2023(arXiv:2305.14325)의 후속이지만, **음악 편곡은 정답이 없는 창작 task**다. 따라서 "수렴 = 성공, 미수렴 = 실패"의 dichotomy를 채택하지 않는다. 미수렴은 **두 가지 합리적 대안이 공존하는 정상 상태**로 간주.

이것이 본 프로젝트의 학술적 차별점이며, 발표 슬라이드 한 장으로 명시한다.

#### 4.7.2 방어 메커니즘 — 4 layer

**Layer 1: Validator fallback rule**

Hard rule을 통과한 두 제안이 충돌하면, Validator가 명시적 룰로 결정:
- "음악 이론적으로 둘 다 valid → target_style에 더 가까운 쪽 (Style Translator) 채택"
- "둘 중 한쪽이 melody와 약한 충돌 → 충돌 없는 쪽 채택"
- "어느 쪽도 결정 불가 → Layer 2로 이관"

**Layer 2: Dual-output mode**

진짜로 양쪽이 동등하게 valid하다면, `arrangement_spec.json`에 두 가지 spec을 둘 다 출력. user에게 선택권을 줌.

```json
{
  "primary_spec": { ... },
  "alternative_spec": { ... },
  "divergence_points": [
    {
      "aspect": "rhythm_pattern",
      "primary": "lofi_swung_16th",
      "alternative": "lofi_straight_8th",
      "rationale": "Both are within lo-fi style conventions; preference depends on user taste."
    }
  ]
}
```

이건 single-agent로는 만들 수 없는 multi-agent만의 부가가치다. 발표에서 강하게 어필.

**Layer 3: Termination metadata 노출**

```json
{
  "termination_status": "stalled",
  "rounds_used": 4,
  "final_metrics": {
    "sim_inter": 0.85, "sim_intra_tradition": 0.94, "sim_intra_style": 0.93,
    "hard_match_ratio": 0.65
  },
  "remaining_disagreements": [ ... ]
}
```

투명성. "수렴 못 했음"을 숨기지 않음.

**Layer 4: Evaluation 비교**

Evaluation 팀이 수렴/미수렴 케이스를 분리해 baseline 대비 품질을 측정. 미수렴 케이스도 single-agent 대비 평균 점수가 높다면, multi-agent의 robust value를 정량 증명.

#### 4.7.3 "모든 debate가 수렴하는가?"에 대한 발표 답변 (한 페이지)

```
Q: Does every debate converge?

A: No, and that's by design.

1. Convergence is MEASURED via 3 metrics (inter-agent, intra-agent, hard-match).
2. Non-convergence triggers DUAL-OUTPUT mode — two valid arrangements are surfaced
   rather than forced into one.
3. Termination status is EXPOSED in metadata.
4. Both convergent and non-convergent runs are EVALUATED against single-agent baseline.

For creative open-ended tasks, divergence is not a bug — it is information.
```

---

### 4.8 Multi-Agent Layer 산출물 체크리스트

- [ ] `agents/tradition_guardian.py` — 시스템 프롬프트 + 호출 함수
- [ ] `agents/style_translator.py` — 동일
- [ ] `agents/music_theory_validator.py` — 시스템 프롬프트 + hard rule Python 함수
- [ ] `debate_orchestrator.py` — round loop, convergence check, fallback dispatch
- [ ] `synthesizer.py` — 최종 spec 통합
- [ ] `convergence.py` — 3-metric 계산
- [ ] `tests/test_debate_e2e.py` — 한 개 곡으로 end-to-end 실행 후 spec 출력 확인
- [ ] `debate_outputs/run_<timestamp>.json` — 매 run마다 자동 저장

---

## 5. Output 형식 — Arrangement Spec

본 절은 **audio rendering 팀과의 인터페이스 계약**이다. 본 스키마가 합의되면 두 팀이 병렬로 작업 가능하다.

### 5.1 메인 산출물 `arrangement_spec.json`

```json
{
  "metadata": {
    "input_song_id": "POP909_042",
    "target_style": "lo-fi chill",
    "system_version": "multi_agent_v1",
    "timestamp": "2026-06-05T14:32:11",
    "termination_status": "converged",
    "rounds_used": 3
  },
  "preserved": {
    "melody_source": "input.MELODY_track",
    "key": "C major",
    "num_bars": 32,
    "section_structure": [
      {"name": "verse",   "start_bar": 1,  "end_bar": 8},
      {"name": "chorus",  "start_bar": 9,  "end_bar": 16},
      {"name": "verse",   "start_bar": 17, "end_bar": 24},
      {"name": "chorus",  "start_bar": 25, "end_bar": 32}
    ]
  },
  "transformations": {
    "chord_progression": [
      {"bar": 1, "chord": "Cmaj9"},
      {"bar": 2, "chord": "Am11"},
      {"bar": 3, "chord": "Fmaj7"},
      {"bar": 4, "chord": "G7sus4"}
      // ...32 bars
    ],
    "rhythm_pattern": "lofi_swung_16th",
    "tempo_bpm": 78,
    "voicing_style": "spread_with_9ths",
    "texture_density": 0.4,
    "instrumentation": {
      "lead":       "rhodes_electric_piano",
      "bass":       "upright_bass",
      "percussion": "lofi_brushed_kit",
      "ambient":    "vinyl_crackle"
    }
  },
  "natural_language_summary": "A 32-bar lo-fi chill arrangement. The original C major melody is preserved over a relaxed swung-16th rhythm at 78 BPM. Chords are voiced with 9th extensions on a Rhodes electric piano, supported by upright bass and brushed percussion, with subtle vinyl crackle ambience."
}
```

#### 5.1.1 필드 강제 사항

- `transformations`의 모든 필드는 `style_profiles.json`의 enum 또는 수치 범위 내. agent가 자유 산문을 출력 못 함.
- `natural_language_summary`는 정확히 한 단락 (3~5 문장). audio 팀이 Suno/Gemini 등 prompt-based 모델 사용 시 그대로 인계 가능.
- `metadata.termination_status`가 `converged` 또는 `stalled` 또는 `max_rounds_reached`.

#### 5.1.2 Dual-output 시 변형

미수렴 시 `alternative_spec`이 추가되며, `divergence_points`로 차이점 명시 (§4.7.2).

### 5.2 보조 산출물

#### 5.2.1 `debate_log.json` (Evaluation 팀에 인계)

전체 토론 트레이스. 모든 라운드의 각 agent proposal, validator 피드백, convergence metric 시계열 포함. 평가팀의 "토론 투명성" 분석과 demo의 "이런 disagreement가 있었다" 큐레이션에 사용.

#### 5.2.2 `debate_log.md` (사람 읽기용)

`debate_log.json`을 markdown으로 렌더. 발표 demo 슬라이드의 "토론 예시" 캡쳐에 활용.

### 5.3 audio rendering 팀이 받는 것, 안 받는 것

| 받음 | 안 받음 |
|---|---|
| `arrangement_spec.json` | `debate_log.json` (평가팀용) |
| 원본 입력 MIDI 파일 경로 | retrieval 결과 raw JSON |

---

## 6. Single-Agent Baseline

### 6.1 목적

"Multi-agent가 single-agent보다 낫다"를 정량 증명하기 위한 비교군. 발표 슬라이드와 evaluation 보고서에서 직접 인용된다.

### 6.2 구현 원칙

- **동일 입력**: Retrieval A + B를 모두 합쳐서 단일 prompt에 전달
- **동일 출력 스키마**: `arrangement_spec.json` 동일 형식
- **동일 모델**: multi-agent의 backbone 중 하나(Tradition Guardian의 backbone) 사용
- **단 1회 LLM call**: 토론 없음, prompt 한 번에 완성된 spec 생성
- **동일 hard rule validator**: baseline 출력도 §4.3.3의 hard rule을 통과해야 함 (불공정한 비교 방지)

### 6.3 차별 금지 사항

baseline에 prompt engineering 트릭(chain-of-thought 강화, few-shot 예시 다수 등)을 얹지 않는다. 비교가 "multi-agent vs prompt engineering"이 되면 우리 contribution이 흐려진다.

발표에 명시할 한 줄: *"Same retrieval, same model, same output schema, same validator — only the debate structure differs."*

### 6.4 산출물

- `baseline/single_agent.py` — 1-call wrapper
- `baseline_outputs/run_<timestamp>.json` — multi-agent와 동일 구조 spec
- evaluation 팀에 multi-agent pair와 함께 인계

---

## 7. Multi-Agent 정당화 Narrative

본 절은 **Presentation 팀과 Evaluation 팀에 인계**할 narrative 자산이다. 발표에서 "왜 multi-agent여야 하는가" 슬라이드의 근거가 된다.

### 7.1 학술적 grounding

| 인용 | 활용 |
|---|---|
| Du et al. 2023, arXiv:2305.14325 | Base multi-agent debate architecture |
| Liang et al. 2023, arXiv:2305.19118 | Echo chamber 문제 제기, heterogeneous backbone 정당화 |
| Madaan et al. 2023, arXiv:2303.17651 (Self-Refine) | Validator의 self-critique 패턴 근거 |
| Yao et al. 2023, arXiv:2305.10601 (Tree of Thoughts) | Dual-output mode의 가지치기 사고 근거 |
| Wang et al. 2020, arXiv:2008.07142 | POP909 데이터셋 |
| Wu et al. 2023, arXiv:2211.06687 | LAION-CLAP |

발표 자료 작성 전 Google Scholar에서 각 인용을 1회 재확인할 것.

### 7.2 본 프로젝트의 차별점 (4가지)

1. **도메인 — 음악 편곡이라는 창작 task에 multi-agent debate 적용**
   - 선행 연구는 모두 텍스트 reasoning task (수학, 진위판단, QA). 음악 도메인 적용은 거의 없음.

2. **정답 없는 문제에서의 debate 재해석**
   - Du et al.은 "수렴 = 정답에 도달"이지만, 본 프로젝트는 "수렴 = 합의 + 미수렴 = 풍부함"으로 재해석.
   - 미수렴 케이스를 dual-output으로 surface하는 메커니즘은 정답 없는 task에 특화된 contribution.

3. **Scope-conditional debate**
   - Preserve/transform scope를 사전 정의하고 그 안에서만 토론. 일반적 multi-agent debate에 없는 음악 도메인 특화 design.

4. **Hard music-theory validator**
   - LLM critic 위에 Python 함수로 짠 hard rule 레이어. 결정적 검증과 확률적 비판의 조합.

### 7.3 발표 슬라이드 구성안

```
Slide N: "Why Multi-Agent for Music Arrangement?"

[좌측]
Music arrangement is multi-objective:
  - Preserve identity (originality)
  - Achieve style fit (target aesthetic)
  - Satisfy music theory (validity)
  
Single agent collapses these into one objective → trade-offs hidden.

[우측]
Our 3-agent design surfaces trade-offs:
  - Tradition Guardian: identity preservation
  - Style Translator:   style fit
  - Music Theory Validator: theory satisfaction
  
Disagreements are LOGGED and either RESOLVED or SURFACED as alternatives.

[하단]
Empirical comparison: see Evaluation slides (single vs multi-agent results)
```

### 7.4 중간발표 피드백 매핑

| 피드백 | 본 시스템의 대응 |
|---|---|
| "Why multi-agent better than single?" | §6 single-agent baseline 비교 |
| "How do you know debate works?" | §4.6 3-metric convergence + §4.7 transparency |
| "Why 2 rounds?" | §4.5 adaptive 1~5 rounds with convergence-based early stopping |
| "Can every debate end well?" | §4.7 dual-output mode for non-convergent cases |
| "Need actual audio output" | §5 spec.json → audio 팀 inceremental handoff |
| "Composer style agent justification" | §4.3.2 3-agent role justification + Liang et al. echo chamber 논거 |
| "Need diverse genres" | §4.1 POP909 + 4 target styles |

발표 슬라이드에 이 매핑을 직접 표시하면 "피드백을 어떻게 반영했는가" 슬라이드를 다 채울 수 있다.

---

## 8. Audio Rendering 팀과의 인계 절차

### 8.1 인계 형식

**메인 인계물**: `arrangement_spec.json` (§5.1)

**부차 인계물**:
- 원본 입력 MIDI 파일 경로 (POP909/XXX/XXX.mid)
- 입력 MIDI의 MELODY 트랙 추출본 (별도 .mid)

### 8.2 Incremental handoff 일정

황새연(audio rendering 팀)이 5/21 카톡에서 명시: "한꺼번에 보내주시기보다는 나오는 대로 한두 개씩 알려달라. agent가 끝나야 오디오 렌더링 시작 가능."

이를 반영해 다음과 같이 인계:

| 시점 | 인계 내용 |
|---|---|
| 5/31까지 | 시스템 1차 결과물 — 1 곡 × 1 style의 `arrangement_spec.json` 초안. 완성도 60%여도 무방. audio 팀이 렌더링 파이프라인 설계 시작. |
| 6/3까지 | 본 시스템(heterogeneous backbone + validator + convergence) 완성 후 demo 케이스 3~5개 spec |
| 6/6까지 | 최종 demo용 spec 확정 + dual-output 케이스 1개 이상 포함 |

### 8.3 스키마 합의 절차

본 문서 §5.1의 스키마를 audio 팀에 제시하고, 다음 항목 협의:

- `instrumentation`의 enum이 audio 팀의 사운드폰트/음원 라이브러리와 매칭되는가
- `rhythm_pattern`의 enum이 MIDI 패턴 또는 prompt 텍스트로 변환 가능한가
- `natural_language_summary`의 톤/길이가 외부 음악 생성 모델(Suno 등) prompt로 적합한가

이번 주(5월 마지막 주) 내 audio 팀과 30분 미팅(전화/카톡) 권장. 합의 후 본 문서 §5.1을 final로 lock.

---

## 9. 일정 (5/27 ~ 6/10)

### Week 1: 5/27 ~ 6/2

| 일자 | 작업 | 산출물 |
|---|---|---|
| 5/27~28 | POP909 clone, pretty_midi로 MIDI 파싱, 100곡 샘플링 | `pop909_sample.csv` |
| 5/28~29 | Symbolic feature 추출 (chord histogram, rhythm pattern, pitch class dist) | `features.parquet` |
| 5/29 | FluidSynth로 MIDI → wav 일괄 렌더링 | wav 파일 100개 |
| 5/30 | LAION-CLAP 임베딩 추출 + retrieval A/B 함수 구현 | `clap_embeddings.npy`, retrieval 함수 |
| 5/30 | **audio 팀에 spec 스키마 초안 공유, 합의** | 합의된 §5.1 스키마 |
| 5/31~6/1 | 3-agent debate 골격 구현 (pre-analysis, round loop, validator hard rule) | `debate_orchestrator.py` MVP |
| 6/1 | 첫 end-to-end demo — 1곡 × 1 style → spec.json | **audio 팀에 첫 spec 인계** |
| 6/2 | 완충일 | — |

### Week 2: 6/3 ~ 6/10

| 일자 | 작업 | 산출물 |
|---|---|---|
| 6/3 | Convergence 3-metric 구현 + heterogeneous backbone 적용 | `convergence.py`, Claude API 통합 |
| 6/3~4 | Dual-output mode 구현, validator soft rule LLM 통합 | 미수렴 방어 동작 확인 |
| 6/4 | Demo 케이스 3~5개 실행, **audio 팀에 batch 인계** | 5개 spec.json |
| 6/5 | Single-agent baseline 구현 + 동일 케이스 실행 | baseline 결과 5개 |
| 6/5 | **Evaluation 팀에 비교 페어 + debate_log 인계** | — |
| 6/6 | 발표용 demo 시나리오 큐레이션 — 토론 흥미로운 케이스 1~2개 선별 | demo 시나리오 |
| 6/7~8 | 발표 자료 협조 (§7의 narrative 자료 제공) | 슬라이드용 그림/표 |
| 6/9 | ppt 마감일, 리허설 | — |
| 6/10 | 최종 발표 | — |

---

## 10. Future Work / 가이드 외 확장 여지

본 절은 현 가이드 범위 밖이지만 발표 시 "추후 확장 가능성"으로 언급할 수 있는 기술적 옵션이다. 우선순위 표시: 🔴 임팩트 큼, 🟡 중간, 🟢 작음.

### 10.1 Retrieval Layer

- 🔴 **MERT (Music Encoder Representations from Transformers)** 도입 — CLAP은 audio-text cross-modal에 강하지만 music-specific representation은 MERT가 더 정교. m-a-p/MERT-v1-95M 등이 HuggingFace에 무료 공개.
- 🟡 **Symbolic music encoder** — MusicBERT(arXiv:2106.05630) 또는 PianoBART. MIDI 구조 자체에서 임베딩 추출 가능.
- 🟡 **Vector DB 도입** — 데이터셋이 5천 곡 이상으로 확장될 때 FAISS 또는 Chroma 도입. 현 909 규모에서는 불필요.
- 🟢 **Cross-encoder reranker** — top-K retrieval 후 작은 모델로 재순위. 정확도 향상 여지.

### 10.2 Multi-Agent Layer

- 🔴 **Adaptive agent spawning** — query 복잡도에 따라 agent 수 동적 결정. 단순 query는 2-agent, 복잡한 경우 4-agent.
- 🔴 **Critic agent 분리 강화** — Constitutional AI(Bai et al. 2022) 패턴 풀 적용. validator를 critic + revisor로 분리.
- 🟡 **Tree of Thoughts 적용** — 각 agent가 매 라운드 1개 proposal이 아닌 K개 후보 출력 → tree search로 가지치기.
- 🟡 **Reflection loop** — Madaan et al. 2023 self-refine을 라운드 내부에 추가. agent가 자기 proposal에 self-critique 후 재생성.
- 🟢 **Agent memory** — 과거 debate 결과를 저장해 후속 debate에서 참조. 같은 곡에 대한 multiple style 변환 시 일관성 향상.

### 10.3 Audio rendering 우회 옵션

audio 팀 영역이지만 음악 생성 모델 인터페이스로 참고 가능:

- 🔴 **Suno API** — 자연어 prompt로 풀곡 생성. `natural_language_summary` 그대로 인계 가능. 단, 멜로디 보존이 어려움.
- 🟡 **Stable Audio Open** — Stability AI 오픈소스 음악 생성 모델. 자체 호스팅 가능, API 비용 없음.
- 🟡 **MIDI-DDSP** — symbolic → audio 변환 신경망. MIDI 보존하며 음색 변환.
- 🟡 **FluidSynth + 다양한 사운드폰트** — 단순하지만 결정적. `instrumentation` enum 그대로 매핑.

### 10.4 Evaluation 보조 (Evaluation 팀 영역)

- 🟡 **MIR objective metrics**: muspy 라이브러리의 pitch class entropy, groove consistency, KL divergence 등. POP909 ground-truth와 비교 가능.
- 🟡 **CLAP-based style fit score** — 생성된 audio의 CLAP 임베딩과 target_style의 텍스트 임베딩 cosine similarity. "더 jazz같은가"를 정량화.
- 🟢 **LLM judge** — GPT-4o에 두 spec을 보여주고 평가. baseline 평가 보조.

### 10.5 Human-in-the-loop

본 MVP에서는 미구현. 발표에 명시할 단락:

> "Our system outputs a structured, editable JSON specification rather than a black-box audio file. This design **naturally supports human-in-the-loop refinement**: users can modify any field (chord substitution, voicing, instrumentation) and re-trigger downstream rendering. While we do not implement a UI layer in this MVP, the architecture is HITL-ready by construction."

확장 시 구현 옵션:

- 🟡 **Streamlit UI** — `arrangement_spec.json`의 각 필드를 폼으로 노출, 수정 후 audio 팀 파이프라인 재호출. 본 MVP에 추가 가능한 가장 가벼운 옵션.
- 🔴 **Selective re-debate** — 사용자가 특정 필드만 "이건 다시 토론해 봐"로 표시 → 부분 재토론. 본격 구현은 별도 프로젝트 규모.

### 10.6 외부 무료 API / 데이터 확장

- **MusicNet (Princeton)** — 클래식 MIDI + audio. 추가 데이터셋.
- **Lakh MIDI Dataset (LMD)** — 17만 개 MIDI. 대규모 indexing 실험.
- **MetaMIDI Dataset** — 43만 개 MIDI. genre tag 풍부.
- **Last.fm Tag API** — 곡 메타데이터 (장르, mood). 무료, 키 발급 필요.
- **MusicBrainz** — 곡 메타데이터. 키 불필요.
- **AudioSet** — Google의 대규모 audio 분류 데이터. CLAP fine-tuning 시 활용 가능.

multi-turn 대화형 LLM 인터페이스에서의 grounding을 강화하고 싶다면:
- 사용자가 "이 곡과 비슷하지만 더 슬프게"라고 요청 시, Last.fm 태그 검색 → "sad" 태그 곡들의 chord/tempo 통계 → 본 시스템 prompt에 inject.
- Wikipedia API로 작곡가/장르 정보 텍스트 grounding.

본 MVP에서는 적용하지 않으나, multi-turn 확장 시 "scope의 자연어 정제" 단계로 통합 가능.

---

## 11. 책임 분배 제안 (한경찬 ↔ 정예준)

본 문서는 분배에 중립적이나, 자연스러운 경계를 다음과 같이 제안:

### 옵션 A — 영역 기반 분리

| 담당자 | 책임 영역 |
|---|---|
| 정예준 | §3 Data & Retrieval Layer 전부 (POP909 처리, CLAP, retrieval 함수) |
| 한경찬 | §4 Multi-Agent Debate Layer 전부 (agent, convergence, validator) + §6 baseline |

장점: 영역 경계가 명확, 인터페이스(§3.4의 retrieval 출력 → §4의 agent 입력)만 합의되면 병렬 개발 가능.

### 옵션 B — 깊이 기반 분리

| 담당자 | 책임 영역 |
|---|---|
| 정예준 | §3 + §4 의 "구현"(코드 작성) 위주 |
| 한경찬 | §4.6~4.7 (convergence, 미수렴 방어) + §7 narrative + §6 baseline + audio/evaluation 팀 협업 인터페이스 |

장점: 구현 vs 설계/협업의 분리. 중간발표 코드에 한경찬이 이미 기여한 구조(§4.3.3 hard rule, evidence_caveats)를 확장하는 흐름.

5/22 카톡에서 두 분이 합의한 "Data + Multi-Agent를 함께 분담"의 자연스러운 형태는 옵션 A에 가까우나, 5/13 한경찬의 "multi-agent debate에 관심"을 반영하면 옵션 B도 합리적. 두 분이 직접 협의해 선택.

---

## 12. 빠르게 시작하는 법 (Day 1 체크리스트)

본 문서를 처음 읽고 코딩을 시작하는 사람을 위한 첫날 task:

- [ ] POP909 git clone, 폴더 구조 직접 확인
- [ ] 임의 곡 1개의 .mid를 pretty_midi로 로드, 3 트랙 분리 확인
- [ ] 같은 곡의 `chord_midi.txt`, `key_audio.txt` 파싱해보고 코드 진행과 키 출력
- [ ] FluidSynth로 .mid → .wav 변환 1개 성공
- [ ] LAION-CLAP 설치 후 위 wav 1개에서 512-dim 임베딩 추출
- [ ] 본 문서 §5.1의 `arrangement_spec.json` 예시를 다시 정독 — 출력 목표를 머리에 박기
- [ ] 본 문서 §10을 훑어보고, 발표 임팩트로 추가할 만한 항목 1개 픽

여기까지 하면 Day 2부터는 batch 처리 + retrieval 함수 작성에 들어갈 수 있다.

---

## 부록 A: 용어 사전

- **Agent**: 특정 역할의 system prompt + LLM backbone + I/O 함수의 조합. 본 시스템은 3개.
- **Backbone**: agent의 기반 LLM 모델 (GPT, Claude 등).
- **Convergence**: 두 agent의 제안이 일정 임계값 이상 일치한 상태.
- **CLAP**: Contrastive Language-Audio Pretraining. 오디오와 텍스트를 같은 임베딩 공간에 매핑.
- **Debate**: 본 문서에서는 두 agent가 자기 제안을 라운드별로 갱신하며 상호 reaction하는 절차.
- **Hard rule**: 결정적 Python 함수로 검증되는 음악 이론 룰 (key membership, melody collision 등).
- **MIR**: Music Information Retrieval. 음악에서 정보 추출/검색하는 분야.
- **Preserve/Transform scope**: 편곡 시 보존할 요소와 변환할 요소의 사전 정의.
- **Soft rule**: LLM 판단으로 평가되는 스타일 적합성, 균형 등.
- **Spec**: `arrangement_spec.json`. 본 시스템의 메인 산출물.
- **Validator**: Music Theory Validator agent. hard rule + soft rule 적용.

---

본 문서는 living document다. 구현 중 결정 변경이 발생하면 §2 결정 표를 먼저 업데이트하고, 해당 절을 수정한다. 모든 변경은 git commit message에 변경 절 번호를 명시.
