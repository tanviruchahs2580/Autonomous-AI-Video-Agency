# Deployment

## Artifacts

- `deploy/Dockerfile` — python:3.12-slim + ffmpeg, non-root user (uid 10001), healthcheck baked in
- `deploy/docker-compose.yml` — api + worker sharing a named volume
- `.github/workflows/ci.yml` — gates + container build/smoke + deploy validation

## Environments

### Local / dev
```bash
python -m agency serve --port 8000 &
python -m agency worker
```

### Docker Compose (single host)
```bash
cd deploy
echo "AGENCY_API_KEY=$(python -c 'import secrets;print(secrets.token_urlsafe(32))')" > .env
docker compose up -d --build
docker compose logs -f api worker
```

### Production hardening checklist
- [ ] strong `AGENCY_API_KEY`, rotate via `/v1/users/key`
- [ ] Postgres DSN in `AGENCY_DB_URL` when running >1 worker
- [ ] TLS termination in front of port 8000 (reverse proxy)
- [ ] volume backups scheduled (see OPERATIONS.md)
- [ ] `AGENCY_APPROVAL_REQUIRED=true` if publish gate is desired

## GPU workers (optional, generative providers)

The default pipeline is CPU-only. To attach GPU generation:

1. Run ComfyUI on a GPU host (`AGENCY_COMFYUI_URL` points to it)
2. Router health-checks it automatically; image candidates switch by quality score
3. Workflow JSONs are versioned artifacts stored alongside other assets with provenance

## CI/CD pipeline

```text
push → quality-gates:
         ruff → mypy → bandit → pip-audit → pytest (51 tests incl. real E2E render)
     → container-build-test:
         docker build → run container → liveness/readiness probes →
         auth enforcement check (401 unauth / 200 auth) → logs
     → deploy-validation:
         docker compose config validation → artifact presence checks
```

All three jobs must pass for the branch to be considered release-ready.
