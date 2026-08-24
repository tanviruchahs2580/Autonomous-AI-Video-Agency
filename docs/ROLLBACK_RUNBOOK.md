# ROLLBACK RUNBOOK

## Application rollback
1. Pick previous healthy tag: `git tag -l` / releases page (currently v1.0.0 → v1.1.0).
2. Compose: `docker compose down api worker && docker compose up -d --build` after checking out the tag,
   or pull the prior image digest and re-point compose (`image:` field).
3. Verify: `/health/live`, `/health/ready`, authenticated smoke call, then run one tiny production job.

Validated: v1.0.0 checkout reproduces its documented baseline (51 tests) — see BASELINE_VALIDATION_REPORT.md;
v1.1.0 adds only additive schema (002) plus hardened behaviors.

## Database migration safety
- Every migration ships a paired down-script (`agency/migrations/NNN_down.sql`).
- Step back one version at a time via `downgrade_one()` (CLI/REPL); automated cycle test exists.
- **Rule**: application N+1 must not run against database N (forward-only compatibility). Roll back app
  first, then schema if required. 001_down is destructive-by-design (dev/staging); production rollbacks use
  backup restore instead (DISASTER_RECOVERY_REPORT.md).

## Configuration rollback
All behavior flags are env vars — revert `.env`/compose environment to previous values and restart. No
migrated state depends on configuration.

## Artifact compatibility
Deliverable manifests include generator provenance; older binaries can read newer manifests (additive JSON).
Rolling back never invalidates existing deliverables.

## Verification checklist post-rollback
- [ ] health live+ready
- [ ] authenticated list projects 200
- [ ] one inline mini-render completes
- [ ] no new failed jobs in `/v1/jobs?state=failed`
