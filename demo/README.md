# MusicPlaybook Demo

POP909 또는 직접 업로드한 MIDI → Multi-agent debate 시각화 → `arranged.wav` 편곡까지 확인할 수 있는 Streamlit 데모입니다.

## 요구 사항

- Python 3.10+
- [FluidSynth](https://www.fluidsynth.org/) (WAV 렌더용)

```bash
brew install fluid-synth
```

- POP909 데이터: `data/POP909-Dataset/POP909/<id>/<id>.mid`
- Reference WAV (POP909 모드): `data/wav_renders/<song_id>.wav`

## 설치

리포지토리 루트에서:

```bash
cd /path/to/MusicPlaybook
pip install -r demo/requirements.txt
pip install -r arrangement_pipeline/requirements.txt
```

## 실행

```bash
streamlit run demo/app.py
```

브라우저에서 `http://localhost:8501` 이 열립니다.

## 사용 방법

### Input source: POP909 dataset

1. 사이드바에서 **POP909 song** + **Target style** 선택 (8개 스타일)
2. 토론 불러오기 (아래 중 하나)
   - **Run live debate** — OpenAI API key 필요 (실시간 multi-agent)
   - **Load cached debate** — `outputs/run_*/` 에 저장된 결과
   - **Upload debate_log.json** — JSON 업로드
3. **Debate** 탭: 에이전트 토론 시각화
4. **Specs** 탭: `arrangement_spec.json` / `baseline_spec.json`
5. **Audio** 탭: input WAV 재생 → **Generate arranged.wav**

### Input source: Custom upload

POP909가 아닌 **본인 MIDI**로 편곡할 때:

1. **Custom upload** 선택
2. **MIDI file** 업로드 (필수)
3. 선택: Reference WAV, `chord_midi.txt`
4. 멜로디 트랙 · 템포 · 스타일 설정
5. **Prepare custom input** → **Generate arranged.wav**

> Custom 모드는 debate 없이 스타일 프로필 기반 자동 spec으로 바로 편곡합니다.

## Live debate (선택)

실시간 multi-agent 토론을 쓰려면 OpenAI API key가 필요합니다.

**방법 A — 환경 변수**

```bash
export OPENAI_API_KEY="sk-..."
streamlit run demo/app.py
```

**방법 B — 파일**

```bash
mkdir -p ~/.secrets
echo "sk-..." > ~/.secrets/openai_api_key
chmod 600 ~/.secrets/openai_api_key
streamlit run demo/app.py
```

- 기본 모델: `gpt-4o-mini` (`DEBATE_MODEL` 환경변수로 변경 가능)
- 결과 저장: `demo/sessions/<timestamp>_<song>_<style>/`
- API key 없이도 **캐시 로드** / **Custom upload 편곡**은 사용 가능

## Target style (8개)

| 스타일 | WAV 렌더 |
|--------|----------|
| lo-fi chill | ✅ |
| upbeat jazz | ✅ |
| cinematic ballad | ✅ |
| bossa nova | ✅ |
| acoustic pop | ✅ |
| R&B soul | ✅ |
| funk groove | ✅ |
| gospel worship | ✅ |

정의 위치:

- 토론/데모: `artifacts/style_profiles.json`
- 렌더 엔진: `arrangement_pipeline/style_definitions.json`

## CLI로 편곡만 실행 (데모 없이)

```bash
python3.10 -m arrangement_pipeline.run \
  --spec outputs/run_20260528_173722_POP909_026_lo-fi_chill/arrangement_spec.json \
  --out-dir outputs/run_20260528_173722_POP909_026_lo-fi_chill/arranged_debate \
  -v
```

## 폴더 구조

```
demo/
  app.py              # Streamlit 메인 UI
  custom_input.py     # Custom MIDI 업로드 처리
  debate_live.py      # Live multi-agent debate
  debate_viz.py       # 토론 시각화 컴포넌트
  paths.py            # 경로·스타일 헬퍼
  render_service.py   # arrangement_pipeline 래퍼
  theme.py            # SNU 남색 테마
  sessions/           # live debate 결과 (git 제외)
  requirements.txt
  README.md
```

## 문제 해결

| 증상 | 해결 |
|------|------|
| 스타일이 4개만 보임 | Streamlit 재시작 (`Ctrl+C` 후 다시 실행) |
| Live debate 불가 | `OPENAI_API_KEY` 설정 확인 |
| WAV 렌더 실패 | `brew install fluid-synth` |
| POP909 MIDI 없음 | `data/POP909-Dataset` 클론 여부 확인 |
| Reference WAV 없음 | `01_data_retrieval.ipynb` §5 또는 Custom 모드에서 MIDI만 업로드 |

## GitHub에 push하기

리포지토리 루트에서:

```bash
cd /path/to/MusicPlaybook

# 스테이징 (코드 + README, WAV/MID 제외)
git add demo/ arrangement_pipeline/ artifacts/style_profiles.json .gitignore

git commit -m "$(cat <<'EOF'
Add Streamlit demo with README and expanded arrangement styles.
EOF
)"

# Author 확인 (Cursor co-author 없는지)
git log -1 --format=full

git push origin main
```

`origin` 에 push 권한이 없으면 본인 fork에 push 후 PR을 엽니다:

```bash
git remote add mine https://github.com/<본인아이디>/MusicPlaybook.git
git push -u mine main
```
