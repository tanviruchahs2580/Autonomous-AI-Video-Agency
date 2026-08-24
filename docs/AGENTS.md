# Agent System

35 agents from the design spec are mapped onto the implementation. Agents that perform pipeline stages are deterministic stage handlers; cross-cutting agents are implemented as engine/platform services. Per the spec's own rule, no unnecessary LLM agents were created — LLMs are optional providers behind the router.

## Pipeline-stage owners

| Agent | Stage | Implementation |
|---|---|---|
| Intake Agent | intake | brief validation → machine spec (platform/resolution/duration rules) |
| Research Agent + Fact Checker | research | key-point extraction; numeric claims flagged `needs_verification` |
| Creative Director | creative_direction | concept, tone, brand palette, music mood selection |
| Script Agent | script_writing | template composer (deterministic) or routed LLM; word-budget enforcement |
| Storyboard Agent | storyboard | timed scene distribution proportional to narration length |
| Asset Intelligence Agent | asset_acquisition | tagging, provenance metadata |
| Asset Acquisition Agent | asset_acquisition | procedural scene image generation per brand palette |
| Rights/License Agent | asset_acquisition | blocks `unknown` rights assets from use (never treated commercial-safe) |
| Voice/TTS Agent | narration | provider chain: edge-tts → synth-local downgrade w/ recorded reason |
| Auto-Cleanup Agent | autocleanup | word-gap silence detection/removal + timing remap |
| Editorial Agent | editorial_assembly | EDL construction + timeline validation |
| Animation Agent | editorial_assembly | Ken Burns zoompan motion over stills |
| Motion Graphics Agent | motion_graphics | title card + lower-third with time windows |
| Render Agent | rough_concat / av_mux | FFmpeg render graph execution |
| Sound Design Agent | audio_mix | ducking weights, mix, two-pass loudness normalize to target LUFS |
| Music Agent | audio_mix | procedural royalty-free-by-construction chord progression bed |
| Caption Agent | burn_captions | ASS styling/safe-zones burn-in + SRT sidecar |
| Color Agent | color_grade | saturation/contrast grade |
| Technical QA Agent | technical_qa | 10 automated checks |
| Creative QA Agent | creative_qa | script coverage, branding distance, caption readability |
| Multimodal QA Agent | multimodal_qa | brief↔script↔timeline↔render consistency scoring |
| Publishing Agent | delivery | platform variants, thumbnail, metadata manifest |
| Human Approval Agent | delivery | optional pre-publish gate (`AGENCY_APPROVAL_REQUIRED`) |
| Memory/Analytics/FinOps Agents | finalize | persistence, metrics record, cost roll-up |

## Platform services (cross-cutting)

| Agent | Where |
|---|---|
| Master Orchestrator | `agency/workflow/engine.py` |
| Project Manager | project/job state transitions in engine + API |
| Model Router | `agency/capabilities/router.py` (quality/cost/latency/health) |
| Security Agent | `agency/security.py` + API middleware |
| Observability Agent | `agency/observability.py` + events table |
| Repair Agent | engine repair loop (classification → strategy → bounded retries → escalation) |
| Generative Media Agent | procedural graphics engine; ComfyUI HTTP adapter point |
| Video Generation Agent | reserved adapter point (documented, not faked) |

Registry source: `agency/agents/registry.py` — dump with `python -m agency agents`.
