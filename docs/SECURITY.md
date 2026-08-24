# Security Model

## Authentication & authorization
- API keys: random 192-bit tokens (`agy_…`), stored as SHA-256 hashes; constant-time comparison
- RBAC: viewer/editor/approver/admin permission sets enforced per endpoint
- Development mode additionally accepts the configured master key for bootstrap; production env disables it
- Rate limiting: per-client fixed window (default 120/min) → HTTP 429

## Input handling
- Uploads: extension allow-list, size cap (default 512 MB), magic-byte sniffing against declared media type; mismatches rejected (415). Executable/script payloads cannot enter storage as media.
- Storage paths: client filenames never used for storage keys (server-generated hex names); `safe_join` guards every path composition; traversal attempts raise.
- Text inputs sanitized of control characters and length-capped at the API boundary.
- SSRF guard: outbound URL utility resolves DNS and blocks private/loopback/link-local/reserved/multicast targets.

## Process execution
- FFmpeg/ffprobe invoked exclusively with argument lists (`shell=False`); no user string ever reaches a shell. Injection tested (`test_no_shell_injection_in_media_calls`).
- Subprocess timeouts on all invocations (media ops default 900s).

## Data protection
- Secrets only from environment; never logged (structured logs carry request/job/task IDs only).
- `.env.example` documents required rotation (`AGENCY_API_KEY`).
- Audit log table records actor/action/entity for sensitive operations (auth denials, project/job creation, uploads).

## Known boundaries (documented, non-blocking)
- SQLite default DB is single-writer; production multi-worker deployments should set Postgres DSN.
- Local object store has no at-rest encryption; deploy with disk/volume encryption or swap in an encrypted S3-compatible store via the `ObjectStore` interface.
