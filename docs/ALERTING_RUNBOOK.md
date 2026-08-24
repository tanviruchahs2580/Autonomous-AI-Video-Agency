# ALERTING RUNBOOK

Suggested Alertmanager rules over `/v1/metrics` + DB probes. Severity: page (P1) / ticket (P2/P3).

| # | Alert | Expression (sketch) | Severity | First response |
|---|---|---|---|---|
| 1 | API down | `up{job="agency-api"} == 0` for 1m | P1 | Check container/health endpoints; see OPERATIONS_RUNBOOK §T1 |
| 2 | High 5xx | `rate(agency_api_requests_total{status=~"5.."}[5m]) / rate(agency_api_requests_total[5m]) > 0.05` | P1 | Inspect logs via request_id; recent deploys → ROLLBACK_RUNBOOK |
| 3 | Queue backlog | `agency_queue_depth{state="queued"} > 100 for 10m` | P2 | Scale workers; check worker logs for crash loops |
| 4 | Stuck running | `agency_queue_depth{state="running"} > workers*2 for 15m` | P2 | Heartbeat staleness auto-reclaims at 300 s; verify workers alive |
| 5 | Worker failure | worker process count < expected (proc exporter) | P1 | Restart workers; jobs auto-reclaim |
| 6 | Repeated failures | `increase(agency_jobs_total{state="failed"}[30m]) > 5` | P2 | Triage failure_class in tasks table; provider health via `/v1/system/status` |
| 7 | Approval backlog | `agency_queue_depth{state="awaiting_approval"} > 20 for 1h` | P3 | Ping approvers; decisions resume jobs automatically |
| 8 | DB unreachable | `/health/ready` non-200 or DB probe fails | P1 | DATABASE_PRODUCTION_GUIDE §incident |
| 9 | Disk pressure | node filesystem >85% on data volume | P2 | Run `python -m agency cleanup --older-than-days N --apply --include-orphans` |
| 10 | Provider outage | `/v1/system/status` provider unhealthy sustained 10m | P3 | Router falls back automatically; confirm fallback_reason in narration task output |
| 11 | Abnormal repair rate | `increase(repairs rows)[1h] > 20` (SQL) | P3 | Inspect repairs.plan_json patterns; usually upstream asset quality |
| 12 | Security events | burst of `auth.denied` in audit_logs (SQL) | P2 | Rotate keys if needed; review source IPs |

Escalation chain: on-call SRE → platform owner. All P1s require an incident entry (INCIDENT_RESPONSE.md).
