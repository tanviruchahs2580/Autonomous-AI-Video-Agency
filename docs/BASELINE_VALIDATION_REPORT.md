# BASELINE VALIDATION REPORT

## Scope
Re-verification of v1.0.0 claims before hardening work, executed on this host.

## Commands & Results
| Check | Command | Result |
|---|---|---|
| Lint | `ruff check agency tests` | All checks passed |
| Types | `mypy agency` | Success: no issues in 25 files |
| Security | `bandit -c .bandit -r agency` | No issues identified |
| Tests | `pytest tests` | **51 passed** (matches v1.0.0 claim) |
| Real render | prior production run artifact | master.mp4 1280x720@30 H.264/AAC 24.00s, decode PASS, −16.4 LUFS |

Evidence files: `docs/evidence/baseline_*.txt`

## Discrepancies found during re-verification
None against the v1.0.0 report. However the audit uncovered defects the original suite did not cover:

1. **No tenant enforcement** despite org_id columns (blocking for multi-tenant use).
2. **SQLite-only DDL defaults** (`strftime`) would break PostgreSQL migrations.
3. **Resume-after-restart lost pipeline context** (`ctx_*` state not persisted on some stage outputs) — discovered by new chaos test.
4. Script word-budget enforcer ignored hook/CTA length → duration drift on short briefs.

All four were fixed in this release with regression tests (see CHANGELOG).
