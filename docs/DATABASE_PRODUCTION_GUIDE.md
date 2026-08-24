# DATABASE PRODUCTION GUIDE

## Dialects
| Environment | DB | Notes |
|---|---|---|
| Development / CI / demo | SQLite (WAL) | default; zero-config |
| Production | PostgreSQL 14+ | set `AGENCY_DB_URL=postgresql+psycopg://user:pass@host:5432/agency` |

Migrations are dialect-neutral (no SQLite-specific DDL); the runner applies identical SQL on both.
Install the PG driver in production images: `pip install psycopg[binary]` (or add to requirements-postgres.txt).

## Connection management (built-in)
- `pool_pre_ping=True` — dead connections recycled automatically
- `pool_size=10`, `max_overflow=20`, `pool_timeout=30s`, `pool_recycle=1800s`
- `busy_timeout` raised to 30 s for SQLite; PG relies on server locks + pre-ping
- Every write path runs inside `session_scope()` transactions with rollback-on-error

## Concurrency model
Workers claim jobs via atomic state transition (`queued/retrying → running`) guarded by row state checks.
Multiple worker processes are supported; for >2 concurrent workers use PostgreSQL.

Verified behaviors (tests): concurrent job creation under 30× HTTP concurrency; 6-worker process pool
completing 24-job batch; stale-running reclaim after heartbeat expiry; transaction rollback on failure;
migration upgrade → downgrade → upgrade cycle (`tests/test_webhooks_governance.py::test_migration_downgrade_upgrade_cycle`).

## Staging deployment (docker compose)
```bash
cd deploy
POSTGRES_PASSWORD=strong MINIO_ROOT_PASSWORD=strong docker compose --profile staging up -d postgres minio
AGENCY_DB_URL='postgresql+psycopg://agency:strong@postgres:5432/agency' \
AGENCY_API_KEY=... docker compose --profile staging up -d api worker
```

## Live PostgreSQL execution status
**ENVIRONMENT BLOCKED on the validation host**: no PostgreSQL server available and no Docker daemon locally.
Code-side validation performed: dialect-neutral migrations, ORM compatibility, connection-pool configuration,
staging compose definition. Execute the staging profile above to complete live validation; expected effort <10 min.

## Backup / restore
SQLite: online backup API + artifacts tar (see scripts/dr_drill.py — measured RTO 0.087 s, RPO 0.113 s).
PostgreSQL: nightly `pg_dump -Fc` + WAL archiving (RPO ≤ archive timeout), restore = stop workers →
restore dump → point app at DB → start → `/health/ready`.

## Rollback strategy
Migrations ship paired down-scripts (`NNN_down.sql`). `downgrade_one()` steps back one version at a time.
Upgrade→downgrade→upgrade is covered by an automated test. Application rollback: redeploy previous image tag;
schema is backward-compatible within a minor release line.
