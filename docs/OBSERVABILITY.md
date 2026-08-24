# OBSERVABILITY

## Logs
Structured JSON to stdout via `agency.observability.configure_logging`. Fields: ts, level, logger,
message, request_id, job_id, task_id (+exception when present). Every HTTP response carries `X-Request-ID`;
middleware stamps it onto request state and correlates auth denials into the audit trail.

## Metrics
`GET /v1/metrics` returns Prometheus text format (auth: any valid key):
- `agency_api_requests_total{method,path,status}` — per-route counters
- `agency_api_request_latency_seconds_{count,sum,bucket}` — request histogram
- `agency_jobs_total{state}` — terminal transitions observed by executors
- `agency_queue_depth{state}` — live gauge across queued/running/retrying/awaiting_approval/failed/completed
- stage/task durations land in `events` + task rows for histogram-style analysis

## Tracing / correlation
Correlation chain: `X-Request-ID` → job.created event/audit row → job_id → task seq → artifacts →
QA reports → deliverable. `GET /v1/events?job_id=` replays a job's full lifecycle;
`GET /v1/jobs/{id}` embeds tasks, repairs, QA reports and cost in one trace document.

## Audit log
Append-only `audit_logs` (tenant-scoped) records: auth denials, project/job creation & deletion,
key issuance/revocation, uploads, webhook/budget admin actions, artifact/deliverable downloads,
approval decisions, cleanup runs. Query: `GET /v1/audit` (role auditor/admin/owner).

## Alerting hookpoints
Prometheus scrape of `/v1/metrics` plus the conditions enumerated in ALERTING_RUNBOOK.md
(queue depth gauges, jobs_total rates, 5xx counters) are sufficient for Alertmanager rules without
any in-process dependency.

## Worker observability
Workers emit structured events per stage transition (`task.done`, `task.failed`, `repair.*`,
`job.completed`) and heartbeat every ~5 s while running; stale heartbeats >300 s make jobs reclaimable.
