# PRODUCTION DEPLOYMENT GUIDE

This is the operator-facing path from zero to serving production traffic.

## 0. Sizing guidance (from executed load test)
- 6 worker processes on 8 vCPU sustained ≈ 26 mini-jobs/min (8 s target). Scale workers ≈ expected concurrent minutes of rendered output per minute demanded.
- API is lightweight (p95 ≈ 165 ms at 30× concurrency on SQLite); run ≥2 API replicas behind TLS.

## 1. Host prerequisites
- Docker Engine + Compose v2 **or** Python 3.12 + FFmpeg.
- Volume for `/app/data` (database + object storage), encrypted at rest if required.

## 2. Configuration
```bash
git clone https://github.com/tanviruchahs2580/Autonomous-AI-Video-Agency.git
cd Autonomous-AI-Video-Agency/deploy
cat > .env <<EOF
AGENCY_API_KEY=$(openssl rand -hex 32)
AGENCY_APPROVAL_REQUIRED=true
AGENCY_TTS_PROVIDER=edge
EOF
```

## 3. Launch
### Container path (verified in CI)
```bash
docker compose up -d --build
curl -fsS -H "X-API-Key: $AGENCY_API_KEY" http://localhost:8000/health/ready
```

### Production database
Use the staging profile to attach PostgreSQL + MinIO (see DATABASE_PRODUCTION_GUIDE.md) and point
`AGENCY_DB_URL` at Postgres before first migration. SQLite remains valid for single-node installs.

## 4. Bootstrap tenants & keys
```bash
KEY="X-API-Key: <bootstrap key from .env>"
curl -H "$KEY" -H "Content-Type: application/json" \
  -d '{"name":"acme","admin_email":"ops@acme.test"}' http://localhost:8000/v1/tenants
```
Store the returned admin key in your secret manager. Issue role-scoped keys per user; enable budgets:
`POST /v1/budgets`.

## 5. First production job (end-to-end proof)
```bash
PID=$(curl -H "$KEY" -H 'Content-Type: application/json' -d @brief.json .../v1/projects | jq -r .id)
JID=$(curl -H "$KEY" -H 'Content-Type: application/json' -d '{}' .../v1/projects/$PID/jobs | jq -r .id)
curl -H "$KEY" -X POST .../v1/jobs/$JID/run          # or wait for a worker
curl -H "$KEY" .../v1/jobs/$JID | jq '.state,.result.qa_summary'
```
Expect `completed` with technical/creative/multimodal all passed and downloadable deliverables.

## 6. Day-2
Attach monitoring (OBSERVABILITY.md), load ALERTING_RUNBOOK rules, schedule backups + monthly DR drill
(DISASTER_RECOVERY_REPORT.md), review costs weekly (`GET /v1/costs`, FinOps section of the final report).

## Verification matrix (what was executed where)
| Step | Local host | CI runner | Staging profile |
|---|---|---|---|
| Clean clone→serve→auth→render | ✅ (fresh clone test) | ✅ container smoke | definition provided |
| PostgreSQL live | ENVIRONMENT BLOCKED | — | profile ready |
| MinIO/S3 live | ENVIRONMENT BLOCKED (adapter+contract code shipped) | — | profile ready |
