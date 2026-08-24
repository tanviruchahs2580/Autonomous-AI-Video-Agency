# OPERATIONS RUNBOOK

## Daily checks (5 min)
1. `curl -H "X-API-Key:$KEY" https://host/health/ready` → expect `{"status":"ready"}`
2. `GET /v1/system/status` → queue depths sane; edge-tts/comfyui health as expected
3. `GET /v1/metrics` scraped by Prometheus; no firing alerts from ALERTING_RUNBOOK list

## Common procedures

### Scale workers
Increase `worker` replicas (compose) or launch more `python -m agency worker`. Jobs auto-distribute; nothing else required.

### Requeue stranded jobs
Stale `running` rows auto-reclaim after 300 s without heartbeat. Immediate action:
```sql
UPDATE jobs SET state='queued', heartbeat_at=NULL WHERE id IN (...);
```

### Approve stuck deliveries
`GET /v1/jobs?state=awaiting_approval` → review → `POST /v1/approvals/{job}/decision {"decision":"approved"}`.

### Free disk space
Dry-run first:
```bash
python -m agency cleanup --older-than-days 14            # report
python -m agency cleanup --older-than-days 14 --apply --include-orphans
```
Master renders/thumbnails/captions are retained kinds; only intermediates purge. Audited.

### Rotate a compromised key
`DELETE /v1/users/{email}/key` then `POST /v1/users/key` — old key dies instantly (401 on next call).

### Add a tenant
`POST /v1/tenants {"name","admin_email"}` → returns tenant admin key once.

### Attach budget guardrails
`POST /v1/budgets {"daily_limit_usd":50,"max_cost_per_job_usd":2}` — job creation returns **402 budget_exceeded** when projected spend would breach limits.

### Webhook debugging
Deliveries retry with exponential backoff (max 5) then go dead-letter; inspect via delivery rows
(webhook_deliveries) and replay by re-dispatching the event. Signature header: `X-Agency-Signature` (HMAC-SHA256 of raw body with the shown-once secret).

### Backup
Nightly: `python -m agency backup --target backups/$(date +%F).db` **plus** artifacts tar; or run `scripts/dr_drill.py` monthly to prove restore (see DISASTER_RECOVERY_REPORT.md).

## Troubleshooting quick table
| Symptom | Likely cause | Action |
|---|---|---|
| 401 everywhere | rotated/expired key | re-issue |
| 429 bursts | rate limit | raise AGENCY_RATE_LIMIT_PER_MIN or back off client |
| Job stuck queued | all workers down | start worker(s) |
| ffmpeg not found | PATH | install FFmpeg; winget location auto-probed |
| Loudness QA flapping | exotic source audio | inspect qa findings; two-pass normalizer logs before/after values |
| Robotic narration | network blocked for edge-tts | expected fallback chain; reason recorded in task output |
