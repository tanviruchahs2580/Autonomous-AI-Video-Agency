# THREAT MODEL

Scope: API surface, media ingestion, AI-generated content path, webhook egress, storage.

## Assets
Tenant data (briefs, scripts, assets), deliverables, credentials (API keys, webhook secrets), cost records.

## Entry points & mitigations
| Threat vector | Example attack | Mitigation in place |
|---|---|---|
| Unauthenticated access | key brute force | rate limit per IP (429), hashed keys, constant-time compare, audit trail |
| Privilege escalation | viewer calls write endpoint | RBAC matrix enforced server-side per route (tests cover deny cases) |
| Cross-tenant read/write | guessed IDs | every query tenant-scoped; foreign-tenant IDs return **404** (no enumeration); automated matrix test |
| Malicious upload | exe as .mp4, zip bombs, oversized | extension allow-list + magic-byte sniff + ffprobe validation (duration/resolution/codec caps) + size cap; server-side random storage names |
| Path traversal | `../../` filenames/keys | filenames never trusted; `safe_join` on all path composition; storage keys validated |
| SSRF | webhook to metadata IP | DNS resolve + private/link-local/reserved block at creation AND delivery |
| Shell injection via media | crafted filename→ffmpeg | argument-list subprocess only (`shell=False`); paths server-generated; injection test asserts no side effects |
| Prompt injection (LLM script) | brief containing "ignore instructions…" | LLM output constrained to JSON schema for script text only; text is sanitized and can never invoke tools/executables; deterministic composer is default |
| Caption/subtitle injection | ASS control chars in narration | brace-block stripping + control-char sanitization before burn-in |
| Webhook tampering/replay | forged callbacks | HMAC-SHA256 signature with per-hook secret + delivery id headers; https enforced in production env |
| Secret leakage | keys in logs/repos | structured logs exclude secrets; gitleaks in CI; hashed storage |

## Out of scope / accepted risks (documented)
- No WAF/DDoS layer (deployment responsibility — put behind reverse proxy/CDN).
- Local object store has no at-rest encryption; production should use encrypted volumes or S3 with SSE.
- MFA/SSO: architecture is OIDC-ready (external IdP issues keys) but no built-in interactive login exists by design.
