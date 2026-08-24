# Setup

## Prerequisites

- Python 3.11+ (tested on 3.12)
- FFmpeg + ffprobe on PATH (winget: `winget install Gyan.FFmpeg`; apt: `sudo apt install ffmpeg`)
- No GPU required for the default pipeline

## Local installation

```bash
git clone https://github.com/tanviruchahs2580/Autonomous-AI-Video-Agency.git
cd Autonomous-AI-Video-Agency
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt -r requirements-dev.txt
copy .env.example .env                            # then edit values

python -m agency migrate
```

The code auto-discovers FFmpeg on PATH and common Windows winget locations.

## Configuration

All settings are env vars prefixed `AGENCY_` (or set in `.env`). See `.env.example`.

| Variable | Default | Purpose |
|---|---|---|
| `AGENCY_API_KEY` | dev-key | API auth key (**change in production**) |
| `AGENCY_DB_URL` | sqlite data dir | SQLAlchemy DSN; Postgres supported |
| `AGENCY_DATA_DIR` | ./data | job working dirs, uploads, backups |
| `AGENCY_STORAGE_DIR` | ./data/storage | object storage root |
| `AGENCY_TTS_PROVIDER` | edge | `edge` = neural voice (network), `synth` = offline deterministic |
| `AGENCY_QA_TARGET_LUFS` | -16 | delivery loudness target |
| `AGENCY_APPROVAL_REQUIRED` | false | require human approval before publishing |
| `AGENCY_QA_MAX_REPAIRS` | 2 | automated repair budget per job |

## Verify installation

```bash
python -m pytest tests            # 51 tests incl. real E2E production
python -m agency run --brief examples/brief_product_launch.json --name Smoke
```

Expected: `"state": "completed"` with deliverable paths and all three QA layers passed.

## Docker deployment

```bash
cd deploy
echo "AGENCY_API_KEY=strong-key-here" > .env
docker compose up -d --build
curl -H "X-API-Key: strong-key-here" http://localhost:8000/health/ready
```

Services: `api` (port 8000) + `worker` (durable queue consumer) sharing the `agency-data` volume.

## Brief format

```json
{
  "title": "Product Launch",
  "objective": "What the video must achieve",
  "audience": "who it is for",
  "platform": "youtube",
  "duration_s": 45,
  "width": 1920, "height": 1080, "fps": 30,
  "cta": "Start free trial",
  "language": "en",
  "brand": {"name": "Brand", "palette": ["#101820", "#1F6FEB", "#F2F7FA"]},
  "key_points": ["point one", "point two", "point three"]
}
```
