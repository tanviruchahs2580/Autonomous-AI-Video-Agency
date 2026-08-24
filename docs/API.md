# API Reference

Base URL: `http://localhost:8000`. All `/v1/*` endpoints require header `X-API-Key`.
Errors are structured: `{"error": {"code": "...", "detail": "..."}}`. Every response carries `X-Request-ID`.

Roles: `viewer`(read) `editor`(read+write) `approver`(+approve) `admin`(all). Rate limit default 120 req/min per client.

## Health

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health/live` | none | liveness |
| GET | `/health/ready` | none | readiness incl. DB check |

## Projects

| Method | Path | Role | Notes |
|---|---|---|---|
| POST | `/v1/projects` | write | body `{name, brief}`; brief validated by pydantic |
| GET | `/v1/projects` | read | paginated `?page=&size=` |
| GET | `/v1/projects/{id}` | read | includes brief, spec, jobs |
| DELETE | `/v1/projects/{id}` | write | 409 if active jobs exist |

## Jobs

| Method | Path | Role | Notes |
|---|---|---|---|
| POST | `/v1/projects/{id}/jobs` | write | `{idempotency_key?}` — duplicate key returns existing job (`deduplicated: true`) |
| GET | `/v1/jobs/{id}` | read | full trace: tasks, repairs, QA reports, cost |
| GET | `/v1/jobs?state=` | read | paginated list |
| POST | `/v1/jobs/{id}/cancel` | write | 409 on terminal states |
| POST | `/v1/jobs/{id}/run` | write | inline execution (dev/small jobs); workers normally claim queued jobs |

## Approvals

```http
POST /v1/approvals/{job_id}/decision
{"decision": "approved" | "rejected", "note": "..."}
```
Role `approver`+. Approve requeues an `awaiting_approval` job; rejection fails it.

## Assets & artifacts

| Method | Path | Role | Notes |
|---|---|---|---|
| POST | `/v1/projects/{id}/assets` | write | multipart upload, `license_state` query param required for commercial use; magic-byte sniffed, extension allow-list, size cap |
| GET | `/v1/artifacts/{id}/download` | read | artifact stream |
| GET | `/v1/deliverables?project_id=` | read | delivery manifests |
| GET | `/v1/deliverables/{id}/download` | read | MP4 stream (path-validated) |

## Observability & FinOps

| Method | Path | Description |
|---|---|---|
| GET | `/v1/events?job_id=&limit=` | event stream (newest first) |
| GET | `/v1/costs?project_id=` | totals + breakdown by category/provider |
| GET | `/v1/system/status` | provider health, queue depth by state, version |

## Idempotency

Job creation accepts `idempotency_key`; retries with the same key return the original job instead of creating duplicates (unique constraint enforced at DB level).

## Example lifecycle

```bash
KEY="X-API-Key: $AGENCY_API_KEY"
PID=$(curl -H "$KEY" -H "Content-Type: application/json" \
  -d @examples/brief_product_launch.json http://localhost:8000/v1/projects | jq -r .id)
# note: /v1/projects expects {"name": "...", "brief": {...}} wrapper
JID=$(curl -H "$KEY" -H "Content-Type: application/json" \
  -d '{"idempotency_key":"run-1"}' http://localhost:8000/v1/projects/$PID/jobs | jq -r .id)
curl -H "$KEY" -X POST http://localhost:8000/v1/jobs/$JID/run
curl -H "$KEY" http://localhost:8000/v1/jobs/$JID | jq .state,.result
```
