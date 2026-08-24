# Operations Guide

## Daily operations

```bash
python -m agency status                     # jobs by state
curl -H "X-API-Key:$KEY" :8000/v1/system/status   # queue depth + provider health
curl -H "X-API-Key:$KEY" ":8000/v1/events?limit=50"
```

## Backup

```bash
# database (SQLite default)
python -m agency backup --target ./backups/agency-$(date +%F).db

# artifacts: sync the storage/data directories
tar czf artifacts-$(date +%F).tgz data/jobs data/uploads
```

PostgreSQL deployments: use `pg_dump` on schedule. Restore = stop services, restore DB file/dump, restore data dirs, start, hit `/health/ready`.

## Disaster recovery

RPO = last backup; RTO ≈ minutes.

1. Provision host with Python 3.12 + FFmpeg (or pull the image)
2. Restore `.env`, DB backup, `data/` directories
3. Start api+worker; verify `/health/live` and `/health/ready`
4. Requeue stranded jobs if any: stuck `running` rows auto-reclaim after heartbeat staleness (300s); force with:
   ```sql
   UPDATE jobs SET state='queued', heartbeat_at=NULL WHERE state IN ('running','retrying');
   ```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ffmpeg executable not found` | PATH missing | install FFmpeg; code also probes winget locations |
| Job stuck `running` | crashed worker | wait 300s for auto-reclaim or run the SQL above |
| 401 on all calls | wrong/missing key | set `X-API-Key`; rotate via `POST /v1/users/key` |
| 429 responses | rate limit | raise `AGENCY_RATE_LIMIT_PER_MIN` |
| QA fails loudness repeatedly | exotic source audio | check `/v1/jobs/{id}` findings; two-pass normalizer logs before/after values in task output |
| Edge TTS degraded to robotic voice | no network / blocked | expected fallback chain; reason recorded in narration task output |

## Performance notes (measured, test machine)

- E2E brief→delivery at 640×360/20s target: ~25–35 s wall-clock including three QA layers
- Dominant costs: zoompan scene renders and loudness analysis passes
- Scale-out: add worker processes; keep media dirs on shared volume/storage
