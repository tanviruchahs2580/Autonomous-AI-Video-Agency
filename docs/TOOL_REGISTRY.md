# Tool Registry

Machine-readable registry per the capability-first selection policy. Decisions: ADOPT / ADAPT / WRAP / ISOLATE / PROTOTYPE ONLY / REPLACE / REJECT.

```yaml
- name: ffmpeg
  repository: https://github.com/FFmpeg/FFmpeg
  version: "9.0 (gyan full build verified on Windows; apt build in CI)"
  license: LGPL-2.1+ (GPL build components used locally, not redistributed)
  capabilities: [media-backbone, probe, render, encode, mux, loudness-normalize, silence-detect-cut, scene-detect, concat, filter-graph]
  runtime: CLI subprocess, arg-list invocation only
  gpu_support: optional NVENC/QSV encoders (not required)
  api: CLI via agency.capabilities.media.run_ffmpeg/run_ffprobe
  integration_method: adapter module with typed errors (MediaError)
  quality: industry reference implementation
  performance: hardware-accelerated encode available; CPU baseline verified
  maintenance: extremely active upstream
  security: invoked without shell; inputs are server-controlled paths
  commercial_use: yes
  decision: ADOPT
  benchmark: full E2E render of 20s 640x360 video < 30s wall-clock on test machine
  notes: low-level backbone only; editing model lives above it

- name: pillow
  repository: https://github.com/python-pillow/Pillow
  version: ">=10.2,<12"
  license: MIT-CMU
  capabilities: [procedural-image-generation, title-cards, lower-thirds, thumbnails, palette-analysis]
  runtime: in-process python
  gpu_support: none needed
  api: agency.capabilities.graphics
  integration_method: direct library behind graphics capability interface
  quality: mature, ubiquitous
  performance: scene image ~50ms at 1920x1080
  maintenance: active
  security: no untrusted input decoding paths used for uploads beyond sniffing
  commercial_use: yes
  decision: ADOPT
  notes: deterministic brand-driven generative visuals with provenance

- name: edge-tts
  repository: https://github.com/rany2/edge-tts
  version: ">=6.1"
  license: GPL-3.0 (runtime dependency, not distributed)
  capabilities: [neural-tts-narration, word-timings]
  runtime: python + Microsoft online service
  api: TTSProvider adapter (agency.capabilities.tts.EdgeTTSProvider)
  quality: natural neural voices
  reliability: network-dependent — runtime downgrade to synth-local recorded in job output
  commercial_use: subject to Microsoft service terms; configure accordingly
  decision: ADAPT (wrapped provider with automatic fallback)
  notes: never a hard dependency; offline deployments unaffected

- name: synth-local-tts
  repository: internal (agency/capabilities/tts.py)
  version: "1.0"
  license: project MIT
  capabilities: [offline-deterministic-narration, word-level-timings]
  runtime: numpy synthesis, zero network
  quality: robotic by design — guaranteed availability fallback
  commercial_use: fully clear (generated in-house)
  decision: ADOPT
  notes: makes CI and air-gapped production deterministic; timings authoritative for captions/sync

- name: faster-whisper
  repository: https://github.com/SYSTRAN/faster-whisper
  license: MIT
  capabilities: [asr, word-timestamps]
  decision: PROTOTYPE ONLY / OPTIONAL ADAPTER
  notes: import-guarded Transcriber implementation provided; not default because our narration is self-generated (timeline-authoritative transcriber is exact by construction). Enable for external-footage transcription.

- name: sqlalchemy
  repository: https://github.com/sqlalchemy/sqlalchemy
  license: MIT
  capabilities: [orm, migrations-runner, multi-dialect]
  decision: ADOPT
  notes: SQLite dev/default; PostgreSQL production path via DSN

- name: fastapi + uvicorn
  license: MIT
  decision: ADOPT
  notes: control plane; pydantic validation; TestClient-based API tests

- name: numpy
  license: BSD-3
  decision: ADOPT
  notes: audio DSP (music bed, speech-shaped synthesis), timing math

- name: opencut
  repository: https://github.com/OpenCut-app/OpenCut
  license: AGPL-3.0
  decision: REJECT (for this system's current scope)
  notes: web NLE UI product; architecture reviewed for timeline concepts but embedding an AGPL web editor adds surface area without pipeline benefit; our EDL model covers required operations

- name: auto-editor
  repository: https://github.com/WyattBlue/auto-editor
  license: MIT? (verify before redistribution)
  capabilities: [silence-removal]
  decision: WRAP-CONCEPT (implemented natively)
  notes: word-gap based cut logic implemented in-repo (editing.apply_silence_cut) because narration word timings give more precise cuts than audio-energy detection; avoids extra runtime dependency

- name: moviepy
  license: MIT
  decision: REJECT
  notes: overlaps FFmpeg; adds Python-side rendering overhead and historical API instability vs direct filtergraph control we already implement

- name: remotion
  license: source-available (company license for orgs)
  decision: REJECT (current scope)
  notes: excellent programmatic graphics but requires Node runtime + licensing review; Pillow procedural engine satisfies current motion-graphics needs with zero license risk

- name: comfyui
  repository: https://github.com/comfyanonymous/ComfyUI
  license: GPL-3.0
  capabilities: [gpu-image-generation-workflows, video-workflows]
  decision: ISOLATE (optional service via HTTP adapter point)
  notes: router health-checks AGENCY_COMFYUI_URL; workflow JSON templates are versioned artifacts when enabled; not required for default pipeline

- name: ruff/mypy/bandit/pytest/pip-audit
  decision: ADOPT
  notes: CI quality gates
```

## Selection policy reminders

1. Requirement is permanent, tool is replaceable — all tools sit behind interfaces.
2. No tool adopted without license verification above.
3. Popularity was not a selection criterion; capability fit and operational reliability were.
