# Changelog

# Changelog

## 1.1.0 — Enterprise hardening release

### Security & multi-tenancy (BLOCKING gates closed)
- True tenant isolation: every projects/jobs/assets/artifacts/deliverables/costs/events/audit query is
  tenant-scoped; foreign-tenant access returns 404 (no enumeration). `POST /v1/tenants` onboarding.
- Cross-tenant attack matrix test (40 checks) + permission-attack tests.
- Expanded RBAC: owner/admin/producer/editor/reviewer/client/auditor/service_account (+legacy aliases);
  API key revocation and expiry enforced per-request; key issuance audited.
- Webhook SSRF guard at creation; https enforcement in production env.

### Reliability
- **Resume-after-restart fix**: stage outputs fully persisted; engine rebuilds pipeline context from
  task history (chaos-tested by killing a live worker mid-render).
- Migration rollback: paired down-scripts + tested upgrade→downgrade→upgrade cycle.
- SQLite WAL + 30 s busy timeout; PostgreSQL-ready dialect-neutral DDL (strftime defaults removed).

### Platform
- HMAC-signed webhooks with retry/backoff/dead-letter + delivery history; milestone events
  (job.created/started/completed/failed/repaired, approval.required).
- Prometheus-format `/v1/metrics` (request counters/latency histogram, job counters, queue-depth gauges).
- Budget governance: tenant/project caps with pre-job 402 budget_exceeded enforcement + overrun events.
- Artifact lifecycle CLI (`python -m agency cleanup`) with retention, orphan report, audit logging.
- Upload hardening: ffprobe validation (duration/resolution/codec allowlists) beyond magic-byte sniffing.
- Secure headers on every response; optional CORS origins config.
- S3-compatible object store adapter (`agency/s3_storage.py`, optional boto3) with signed URLs.

### AI/content quality fixes surfaced by scale testing
- Script word-budget enforcer now accounts for hook/CTA; short-form composer variant (<10 s briefs).
- Research stage derives objective-theme points even when key_points are supplied.
- Concept-coverage gate is duration-proportional and skips when a brief has <3 scorable keywords.

### Validation executed (evidence in docs/evidence/)
- 64 automated tests passing locally; CI green on GitHub Actions runners.
- Load: 300 API req @30× concurrency (p50 17.9 ms / p95 165 ms / 0 5xx); 24-job batch across 6 worker
  processes → 22 completed / 2 escalated-to-approval, ≈26 jobs/min on 8 vCPU.
- Soak: 63 jobs / 3 min, zero failures, RSS growth 0.1 %.
- DR drill PASSED (RTO 0.087 s, RPO 0.113 s, SHA-256 integrity match) incl. WAL-safe restore procedure.
- Enterprise simulation: 10 tenants / 100 jobs / 0 violations / 15/15 renders.
- Chaos: real worker SIGKILL mid-render → stale-reclaim → completion with playable artifact.
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
