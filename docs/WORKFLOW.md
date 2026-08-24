# Workflow Engine & Durability

## Job lifecycle

```text
queued → running → completed
              ├→ retrying (transient/job-level) → running …
              ├→ awaiting_approval → queued (after approve) / failed (after reject)
              ├→ failed (attempts exhausted or rejection)
              └→ cancelled
```

Tasks track their own attempts (`max` default 3) and history rows remain for auditing.

## Durability guarantees

| Failure | Recovery |
|---|---|
| Worker crash mid-job | heartbeat older than 300s ⇒ job reclaimable by any worker |
| Application restart | all state in DB; workers re-scan queued/retrying jobs on start |
| Duplicate submission | unique idempotency key returns existing job |
| Provider outage | router health checks + runtime provider downgrade (recorded) |
| Corrupt input | classified failure → repair strategy restarts from asset stage |
| Approval required | job parks in `awaiting_approval`; approve endpoint requeues |

## Claiming semantics

`claim_next_job` orders by priority then FIFO, atomically transitions to `running`, stamps attempt/heartbeat. `claim_job(job_id)` targets a specific job (CLI/API inline execution). Resuming after approval resets gated tasks to pending only when a decided approval exists.

## Running

```bash
python -m agency worker                 # long-lived worker
python -m agency worker --max-jobs 1    # one-shot consumer (cron/systemd friendly)
```

Multiple workers can run concurrently against the same database; SQLite suits single-worker deployments, Postgres is recommended for N>1.
