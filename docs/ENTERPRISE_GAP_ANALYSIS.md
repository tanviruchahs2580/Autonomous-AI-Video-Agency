# ENTERPRISE GAP ANALYSIS — v1.0.0 → Enterprise bar

Legend: BLOCKING = gate for enterprise deployment · HARDEN = improve now · ENV-BLOCKED = needs external resource

## Findings

| # | Area | Gap in v1.0.0 | Class | Action this release |
|---|---|---|---|---|
| 1 | **Multi-tenancy** | `org_id` columns exist but NO enforcement anywhere — any valid key reads all data | **BLOCKING** | Full tenant scoping on every query + cross-tenant attack tests |
| 2 | RBAC | 4 coarse roles | HARDEN | 8-role matrix incl. auditor/service; revocation+expiry |
| 3 | Webhooks | absent | HARDEN | HMAC-signed delivery, retries, DLQ, history API |
| 4 | Metrics | logs only | HARDEN | Prometheus-format `/v1/metrics`, request/stage/job counters |
| 5 | Cost governance | costs recorded, no limits | HARDEN | budgets table + pre-job enforcement |
| 6 | Upload depth | magic-byte only | HARDEN | ffprobe duration/resolution/codec allowlist caps |
| 7 | AI input | API strings unsanitized | HARDEN | sanitize at boundary; LLM output constrained to script JSON |
| 8 | Migration rollback | upgrade only | HARDEN | paired down-migrations + tested cycle |
| 9 | Artifact lifecycle | unbounded growth | HARDEN | retention cleanup CLI w/ orphan report, audited |
| 10 | **PostgreSQL portability** | DDL uses SQLite-only `strftime()` defaults | **BLOCKING for prod DB** | portable DDL (ORM-supplied timestamps); dialect-neutral migrations |
| 11 | S3 storage | local only | PARTIAL | S3ObjectStore adapter (optional dep) + MinIO staging profile; live exec ENV-BLOCKED |
| 12 | Live PostgreSQL run | no server in env | ENV-BLOCKED | staging compose + guide + static validation script |
| 13 | GPU | none | ENV-BLOCKED | documented; CPU fallback verified |
| 14 | Chaos testing | recovery logic unit-tested only | HARDEN | real worker-kill integration test |
| 15 | Load/stress/soak evidence | none | HARDEN | executed scripts with real numbers from this host |
| 16 | DR drill | backup cmd existed, restore never drilled | HARDEN | executed drill, measured RPO/RTO |
| 17 | Supply chain | pip-audit only | HARDEN | gitleaks + Trivy image scan + Syft SBOM in CI |
| 18 | Container hardening | non-root ok | HARDEN | cap_drop, no-new-privileges, read-only rootfs, resource limits |
| 19 | Clean-clone proof | implied | HARDEN | fresh clone E2E executed |
| 20 | Rollback proof | tags exist | HARDEN | v1.0.0 checkout revalidated + migration down/up cycle |

## Verdict driving this release
Items 1 and 10 are hard blockers removed in v1.1.0. Everything code-verifiable is implemented
and executed here; genuinely external executions are labeled ENVIRONMENT BLOCKED with exact
requirements (see FINAL report §25).
