# QA & Automated Repair

## Three mandatory layers

### Technical QA (stage 15)
ffprobe + decode + loudness verification of the graded master:
container family, video codec h264, audio codec aac, resolution vs spec, fps vs spec, duration window (0.65×–1.45× target), stereo audio present, full decode pass (no corruption), integrated loudness within ±3 LU of `AGENCY_QA_TARGET_LUFS`, true peak ≤ −0.3 dBTP.

Failure classes: `qa_container`, `qa_codec`, `qa_resolution`, `qa_fps`, `qa_duration`, `qa_audio`, `qa_loudness`, `corrupt_media`.

### Creative QA (stage 16)
- CTA present in narration audio (token coverage ≥ 50%)
- Hook section present in narration
- Branding: dominant colors of frames sampled at 15/50/85% vs brand palette (avg distance ≤ 160)
- Caption validation: monotonic timings, no overrun, reading speed ≤ 20 cps, line-length sanity at low resolutions

Failure class: `qa_creative`. Score recorded in QA report.

### Multimodal QA (stage 17)
Brief → Script → Timeline → Render consistency:
- concept coverage: stopword-filtered, stem-matched brief concepts present in script (≥ 45%)
- storyboard scene count == rendered clip count
- aspect ratio matches platform/brief spec (±0.02)
- final duration drift from brief target ≤ 35%

Failure class: `qa_multimodal`.

All reports persist to `qa_reports` with findings arrays and scores.

## Automated repair loop

```text
Task failure
   → classify (failure_class on task)
   → stage-retryable? (transient/render_crash/provider_unavailable/ffmpeg_error, or attempt < 2)
        yes → retry same stage with backoff (attempt-tracked per seq)
        no  → repair budget left?
              yes → pipeline repair strategy:
                    qa_loudness    → restart from audio_mix
                    qa_duration    → restart from editorial_assembly
                    qa_sync        → restart from av_mux
                    corrupt_media  → restart from asset_acquisition
                    other          → restart from pipeline start
              no  → escalate human: job → awaiting_approval (+ approval row, audit event)
```

Repair budget default 2 (`AGENCY_QA_MAX_REPAIRS`). Every decision is written to `repairs` with its plan and result; every transition emits an event. No infinite loops are possible — both counters (`task.attempt`, `job.repair_count`) are monotonically bounded.

## Verified behaviors (tests)

- transient failure retried until success then completes (`test_engine_retries_transient_failure_then_succeeds`)
- budget exhaustion escalates to approval queue (`test_engine_escalates_after_budget_exhausted`)
- approved gate resumes job to completion (`test_approval_gate_resumes_job`)
- real production E2E passes all three layers on an actual render (`tests/test_e2e_production.py`)
- corrupted media fixture fails decode check (`test_probe_detects_corruption`)
