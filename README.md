# Autonomous AI Video Agency

Brief-to-delivery autonomous video production system. Takes a client production brief through the professional video lifecycle — intake, research, creative direction, script, storyboard, asset generation, narration, editing, motion graphics, audio mix, captions, color, rendering, three-layer QA, automated repair, and multi-platform delivery — producing a real playable video with full provenance, cost tracking and audit logging.

```
Client Brief → Intake → Research → Creative → Script → Storyboard → Assets
    → TTS Narration → Silence Cleanup → Editorial Assembly → Motion Graphics
    → Render → Audio Mix → Mux → Captions → Color → Technical/Creative/Multimodal QA
    → Automated Repair Loop → Delivery Variants → Provenance + Cost + Audit
```

## Quick start

Requirements: Python 3.11+, FFmpeg on PATH.

```bash
pip install -r requirements.txt

# apply migrations
python -m agency migrate

# produce a video from a brief (inline execution)
python -m agency run --brief examples/brief_product_launch.json --name "Demo"
```

The final JSON includes deliverable paths, QA results and cost. The master MP4 is playable immediately.

### Server mode

```bash
python -m agency serve --port 8000        # API server
python -m agency worker                   # durable job worker
```

```bash
curl -H "X-API-Key: $AGENCY_API_KEY" http://localhost:8000/v1/projects
```

### Docker

```bash
cd deploy
AGENCY_API_KEY=change-me docker compose up --build
```

See [docs/SETUP.md](docs/SETUP.md) for full setup, [docs/OPERATIONS.md](docs/OPERATIONS.md) for ops.

## What it produces

For `examples/brief_product_launch.json`:

- `master.mp4` — H.264/AAC, brief-specified resolution/fps, EBU R128 loudness-normalized narration over procedural music bed, burned styled captions, title card + lower-third overlays, Ken Burns scene motion
- `variant_square.mp4` — 1:1 platform variant
- `thumbnail.png` — headline thumbnail rendered from the master
- `captions.srt` — sidecar captions with word timings
- `metadata.json` — publishing manifest
- Full DB record: tasks, artifacts w/ provenance, QA reports (3 layers), repairs, costs, audit log, events

## Architecture

Capability-first design: requirements are permanent, tools are replaceable adapters.

| Capability | Adapter | Notes |
|---|---|---|
| Media backbone | FFmpeg 9.x | probe/render/mux/loudnorm/silence/concat |
| TTS | edge-tts → synth-local fallback chain | natural voice when network available; deterministic offline fallback guaranteed |
| Transcription | timeline-authoritative (+ optional faster-whisper adapter) | our own narration ⇒ synthesis timings are authoritative |
| Graphics | Pillow procedural engine | scenes/title cards/lower-thirds/thumbnails from brand palette |
| Generative images | procedural (ComfyUI HTTP adapter point) | provenance tracked; unknown-rights assets blocked |
| Model routing | quality/cost/latency/health router | provider health cached; automatic fallback |
| Workflow | DB-backed durable engine | states, retries w/ backoff, repair strategies, stale-heartbeat recovery, approval gates |
| API | FastAPI | key auth, RBAC, rate limit, idempotency, structured errors |

Full details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [docs/TOOL_REGISTRY.md](docs/TOOL_REGISTRY.md) · [docs/AGENTS.md](docs/AGENTS.md)

## Quality gates

```text
ruff check agency tests          # lint/format
mypy agency                      # type check
bandit -c .bandit -r agency      # security scan
pytest tests                     # 51 tests incl. real-media integration + full E2E production run
```

CI runs all gates plus container build/smoke-test and deploy validation on every push: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)

## Documentation

- [Setup](docs/SETUP.md)
- [Architecture](docs/ARCHITECTURE.md)
- [API reference](docs/API.md)
- [Agent system](docs/AGENTS.md)
- [Workflow & durability](docs/WORKFLOW.md)
- [QA & automated repair](docs/QA_AND_REPAIR.md)
- [Security model](docs/SECURITY.md)
- [Tool registry](docs/TOOL_REGISTRY.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Operations / backup / DR](docs/OPERATIONS.md)

## License

MIT. Generated media is produced in-house (procedurally or via configured providers); external asset rights are enforced by the license gate — unknown-rights assets are never used commercially.
