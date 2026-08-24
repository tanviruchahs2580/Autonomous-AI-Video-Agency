# Changelog

## 1.0.0 — Initial production release

### Core
- Durable DB-backed workflow engine: 20-stage production pipeline, job/task state machine,
  retries with backoff, classified repair strategies, repair budget, human escalation,
  stale-heartbeat recovery, idempotent job creation
- FastAPI control plane: key auth (SHA-256 hashed), RBAC (viewer/editor/approver/admin),
  rate limiting, structured errors, request IDs, pagination, uploads with magic-byte sniffing
- Migrations runner with tracked schema versions (SQLite default, PostgreSQL-ready)

### Capabilities
- FFmpeg adapter: probe, decode verification, zoompan scene renders, concat (copy+re-encode
  fallback), mux with sync gate, ASS burn-in, color grade, two-pass loudness normalization
  with verification pass, silence cut via word-gap analysis
- TTS provider chain: edge-tts (neural) with automatic runtime downgrade to deterministic
  offline synth; word-level timings authoritative downstream
- Procedural graphics engine (Pillow): scene images, title cards, lower thirds, thumbnails,
  palette analysis for brand QA
- Model router: quality/cost/latency scoring with provider health caching and fallbacks;
  optional OpenAI-compatible and ComfyUI adapters behind health checks
- Captions: cue grouping, ASS styling with safe zones, SRT sidecars, sync/readability validation

### QA & delivery
- Three QA layers (technical / creative / multimodal) with persisted scored reports
- Delivery variants, thumbnails, metadata manifests, provenance on every artifact
- FinOps cost entries per task/provider; audit log; event stream

### Quality
- 51 automated tests: unit, media integration on real fixtures (incl. corrupted media),
  workflow durability/recovery, API contract, security (SSRF/traversal/injection/RBAC/rate-limit),
  full E2E production run producing a verified playable MP4
- CI: ruff + mypy + bandit + pip-audit + tests, container build & smoke, compose validation
