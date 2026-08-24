# PROJECT ARCHITECTURE MAP — v1.0.0 baseline audit

## Entrypoints
| Path | Role |
|---|---|
| `agency/__main__.py` | CLI: migrate / serve / worker / run / status / backup / agents |
| `agency/api/main.py` | FastAPI control plane (24 routes, v1 prefix) |
| `agency/worker.py` | durable queue consumer loop (claim→execute→heartbeat) |

## Orchestration & Workflow
| Component | Location | Notes |
|---|---|---|
| Master Orchestrator | `agency/workflow/engine.py::WorkflowEngine` | plan→delegate→verify→repair loop |
| Job/Task state machine | same | states: queued/running/retrying/paused/failed/cancelled/completed/awaiting_approval |
| Repair strategies | `engine._attempt_repair` | stage-retry vs pipeline-restart vs human escalation; bounded budgets |
| Stage handlers (20) | `agency/agents/stages.py` | intake…finalize; HANDLERS registry |
| Agent registry (35) | `agency/agents/registry.py` | stage owners + cross-cutting services |

## Capabilities (`agency/capabilities/`)
media.py (FFmpeg adapter), tts.py (provider chain), asr.py (transcriber iface),
captions.py (ASS/SRT), editing.py (EDL/silence-cut), graphics.py (Pillow engine), router.py (model routing).

## Data layer
`agency/db.py` (engine/session/migrations runner), `agency/models.py` (16 ORM models),
`agency/migrations/001_initial_schema.sql`, storage via `agency/storage.py::LocalObjectStore`.

## Security
`agency/security.py`: key hashing (SHA-256+HMAC compare), safe_join, upload sniffing,
SSRF guard, rate limiter. API middleware enforces auth/RBAC per route.

## Observability
`agency/observability.py`: JSON logs (request/job/task ids), audit(), emit_event(), record_cost().
Tables: events, audit_logs, costs.

## CI/CD & Deploy
`.github/workflows/ci.yml` (quality-gates → container-build-test → deploy-validation),
`deploy/Dockerfile` (non-root, healthcheck), `deploy/docker-compose.yml` (api+worker).

## Tests (51)
unit(13) · media-integration(9) · workflow(7) · api(9) · security(8) · e2e-production(2) · fixtures(conftest)
