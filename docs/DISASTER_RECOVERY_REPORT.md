# DISASTER RECOVERY REPORT

Drill executed by `scripts/dr_drill.py` on this host. Evidence: `docs/evidence/dr_drill.json`.

## Drill procedure
1. Provision isolated temp environment; run migrations; execute a real production job → master MP4 artifact.
2. **Backup**: online SQLite backup API (`src.backup(dst)`) + tar of artifacts dir.
3. **Damage injection**: DELETE deliverables row, UPDATE job→failed, delete master file from storage.
4. **Restore**: stop app sessions (`engine.dispose`), remove stale `-wal`/`-shm`, copy DB back, unpack artifacts.
5. **Verify**: row counts restored, job state restored, SHA-256 of restored master matches pre-disaster hash.

## Measured results
| Metric | Value |
|---|---|
| Backup duration | 0.256 s |
| RPO (max data loss = time since last backup) | **0.113 s** (backup taken immediately before damage) |
| RTO (restore + verify) | **0.087 s** |
| Deliverable integrity | SHA-256 match ✓ |
| Rows/state restored | ✓ (deliverables=2, job=completed) |
| Overall | **PASSED** |

## Critical operational lesson captured
With WAL mode, copying only `agency.db` while services run loses recent committed pages and stale
`-wal`/`-shm` files can replay damage over a restored file. The drill codifies the safe sequence:
online-backup API (or stop services) → backup artifacts → on restore: dispose engines, remove
`-wal`/`-shm`, then restore files. Encoded in `scripts/dr_drill.py`; documented in OPERATIONS_RUNBOOK.md.

PostgreSQL deployments: use `pg_dump`/`pg_basebackup`; RPO/RTO then depend on WAL archiving cadence.
