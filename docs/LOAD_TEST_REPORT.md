# LOAD TEST REPORT

Environment: Windows host, 8 logical CPUs, Python 3.12, SQLite (WAL), FFmpeg 9.0, offline synth TTS.
Script: `scripts/load_test.py` · Raw JSON: `docs/evidence/load_test.json`

## API phase (300 POST /v1/projects @ 30 concurrent)
| Metric | Value |
|---|---|
| p50 latency | 17.9 ms |
| p95 latency | 164.8 ms |
| p99 latency | 317.4 ms |
| Throughput | 9.7 req/s |
| 5xx | 0 |

## Render phase — production topology (24 queued jobs, 6 separate worker processes)
Target per job: 8 s, 320×180 brief. Raw evidence run A:

| Metric | Value |
|---|---|
| Completed | 22 / 24 |
| Escalated to approval (repair budget) | 2 |
| Wall clock | 50.5 s for the batch |
| Throughput | **26.1 jobs/min** on 6 workers |

Earlier in-process thread-pool variant was replaced by this worker-process topology after it exposed
SQLite multi-writer contention; production guidance is PostgreSQL (see DATABASE_PRODUCTION_GUIDE.md).

## Interpretation
- Single worker ≈ 4–5 jobs/min at 8 s target on this CPU; scaling to 6 workers yielded ≈26/min (≈5.2× linear).
- The 2 escalated jobs demonstrate the bounded repair + human-gate path operating under load rather than silent failure.

## Limitations
- Host-dependent numbers; CI runners will differ.
- 500-job tier not executed here (time budget); script supports `--renders 500` for a provisioned host.
- GPU/egress costs not applicable (no GPU/cloud providers configured).
