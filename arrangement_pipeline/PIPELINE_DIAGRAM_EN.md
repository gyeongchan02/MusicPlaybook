# Arrangement Pipeline — Diagrams (English, for PPT)

Copy diagrams into [mermaid.live](https://mermaid.live) → Export PNG → Insert into Google Slides.

---

## 1. High-level (one slide)

```mermaid
flowchart LR
  subgraph DEBATE["Multi-Agent Debate (upstream)"]
    D["02_multi_agent_debate"]
    SPEC["arrangement_spec.json"]
    D --> SPEC
  end

  subgraph PIPELINE["Arrangement Pipeline (my implementation)"]
    direction TB
    IN["Sole input:\narrangement_spec.json"]
    POP["POP909 assets\n(.mid, chord_midi, beat_midi)"]
    MID["arranged.mid\n(MELODY + accompaniment)"]
    WAV["arranged.wav\n(FluidSynth)"]
    IN --> GEN["Generate MIDI"]
    POP --> GEN
    GEN --> MID
    MID --> REN["Render audio"]
    REN --> WAV
  end

  SPEC --> IN

  style DEBATE fill:#f5f5f5,stroke:#999
  style PIPELINE fill:#e8f4fc,stroke:#1a73e8
  style SPEC fill:#fff3cd,stroke:#f9a825
  style WAV fill:#e6f4ea,stroke:#34a853
```

---

## 2. Primary responsibilities (one slide)

```mermaid
flowchart TB
  SPEC(["arrangement_spec.json\n(debate-generated spec)"])

  SPEC --> R1["① Sole input\nRead transformations"]
  R1 --> R2["② Preserve melody\nPOP909 MELODY track"]
  R1 --> R3["③ Generate accompaniment\nPer spec: rhythm, voicing, chords"]
  R2 --> MID["arranged.mid"]
  R3 --> MID
  MID --> R4["④ Render WAV\nFluidSynth + 30s clip"]
  R4 --> WAV(["arranged.wav"])

  POP[("POP909 026.mid\nchord_midi.txt\nbeat_midi.txt")] -.-> R2
  POP -.-> R3
  STYLE[("style_definitions.json")] -.-> R3

  style SPEC fill:#fff3cd
  style WAV fill:#e6f4ea
  style R2 fill:#fce8e6
  style R3 fill:#e8f0fe
  style R4 fill:#e6f4ea
```

---

## 3. Internal modules (technical slide)

```mermaid
flowchart TB
  subgraph INPUTS["Inputs"]
    S["arrangement_spec.json"]
    M["026.mid"]
    C["chord_midi.txt"]
    B["beat_midi.txt"]
    CSV["pop909_sample.csv\n(source BPM)"]
    REF["wav_renders/POP909_026.wav\n(length reference)"]
  end

  subgraph CORE["arrangement_pipeline/"]
    SL["spec_loader.py"]
    P["pipeline.py"]
    T["timing.py\nbeat grid + tempo map"]
    CH["chords.py\npychord / Harte"]
    ACC["accompaniment.py\nbass · Rhodes · drums"]
    ST["style_definitions.json"]
    FS["fluidsynth_render.py"]
  end

  subgraph OUTPUTS["Outputs"]
    MID["arranged.mid"]
    WAV["arranged.wav"]
  end

  S --> SL --> P
  M --> P
  C --> P
  B --> T --> P
  CSV --> T
  ST --> ACC
  SL --> ACC
  CH --> ACC
  P --> ACC
  P --> MID
  MID --> FS
  REF --> FS
  FS --> WAV

  P --> |"copy MELODY only"| MID
```

---

## 4. MIDI track layout (optional slide)

```mermaid
flowchart LR
  subgraph SOURCE["POP909 source MIDI"]
    ML["MELODY"]
    BR["BRIDGE ✗ removed"]
    PI["PIANO ✗ removed"]
  end

  subgraph OUT["arranged.mid"]
    ML2["MELODY ✓ preserved"]
    RH["rhodes_comp\n(from spec)"]
    BA["upright_bass\n(from spec)"]
    DR["drums\n(from spec)"]
  end

  ML --> ML2
  SPEC2["arrangement_spec.json"] --> RH
  SPEC2 --> BA
  SPEC2 --> DR
```

---

## 5. Caption text for PPT (copy-paste)

**Title:** Arrangement Pipeline Overview

**Subtitle:** From debate specification to playable audio

**Bullets:**
- **Input:** `arrangement_spec.json` only (from Multi-Agent Debate)
- **Preserve:** Original MELODY from POP909 MIDI
- **Generate:** Accompaniment MIDI (Rhodes, upright bass, drums) per spec
- **Render:** `arranged.wav` via FluidSynth (30s, aligned with CLAP reference clip)

**Not used for rendering:** `debate_log.json`, `natural_language_summary`
