# SECRETS MANAGEMENT

## Principles enforced
- No credentials in source, images, logs, or Git (CI runs gitleaks on full history).
- Configuration only via environment (`AGENCY_*`) or mounted secret files; `.env` is git-ignored, `.env.example` documents every variable with placeholders.
- API keys stored **hashed** (SHA-256) in `users.api_key_hash`; raw keys are shown once at issuance.
- Webhook signing secrets are generated server-side (`whsec_…`), displayed once, required for HMAC-SHA256 signature verification by consumers.

## Rotation & lifecycle
| Operation | Endpoint / command |
|---|---|
| Issue key (optional expiry days) | `POST /v1/users/key {"email","role","expires_in_days"}` |
| Revoke immediately | `DELETE /v1/users/{email}/key` |
| Rotate | re-issue (hash overwritten) then revoke old |
| Expiry | automatic 401 after `api_key_expires_at` |

Auth checks run revocation/expiry on every request; denials are audit-logged.

## Production secret-manager strategy
The app reads secrets from environment only — making it compatible with any manager:

| Manager | Mechanism |
|---|---|
| HashiCorp Vault | Vault Agent renders `.env` sidecar / injects env at launch |
| AWS Secrets Manager | ECS/Lambda env injection or External Secrets Operator |
| Azure Key Vault | Key Vault references in App Service/Container Apps |
| GCP Secret Manager | Secret Manager env bindings in Cloud Run/GKE |

Docker: never `ARG`/`ENV` real secrets into images; compose reads `${AGENCY_API_KEY:?}` from a git-ignored `.env`.

## Verification performed
- gitleaks scan wired into CI (full history) — must pass before other jobs.
- Bandit + pip-audit in CI.
- Manual grep of repo/image layers for `AGENCY_API_KEY=` values: only `.env.example` placeholder present.
