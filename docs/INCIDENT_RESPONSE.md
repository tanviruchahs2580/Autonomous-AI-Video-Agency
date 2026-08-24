# INCIDENT RESPONSE

## Severity ladder
| Sev | Definition | Response |
|---|---|---|
| SEV1 | API down / data loss / cross-tenant leak suspected | page on-call, incident channel, status updates every 30 min |
| SEV2 | Feature broken (renders failing, queue stalled) | ticket + same-business-day |
| SEV3 | Degraded (slow, single-tenant issue) | next business day |

## First 15 minutes (SEV1)
1. Freeze: stop deploys.
2. Capture state: `GET /v1/system/status`, `GET /v1/events?limit=200`, container logs.
3. If data integrity suspected: **take immediate backup** (`python -m agency backup`) before any restarts.
4. Classify via ALERTING_RUNBOOK table; apply the matching first-response.

## Containment playbook
- Bad deploy → ROLLBACK_RUNBOOK (previous image tag; migrations have paired down-scripts).
- Compromised key → revoke endpoint; audit `GET /v1/audit` for actions performed by that actor.
- Tenant isolation suspicion → freeze writes (`AGENCY_APPROVAL_REQUIRED=true` gates publishing), snapshot DB, reproduce with the tenant-isolation test suite against production data copy.

## Post-incident
Within 5 business days: timeline, root cause, detection gap, action items with owners. Attach relevant
evidence files from docs/evidence/. Update THREAT_MODEL.md if a new vector was involved.

## Contacts placeholder
Fill in per organization: on-call rotation tool, escalation phone, compliance officer (for tenant-data incidents).
