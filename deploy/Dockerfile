FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml README.md ./
COPY agency ./agency
COPY examples ./examples
RUN pip install --no-cache-dir --no-deps .

RUN useradd -m -u 10001 agency
USER agency

ENV AGENCY_DATA_DIR=/app/data \
    AGENCY_STORAGE_DIR=/app/data/storage \
    AGENCY_DB_URL=sqlite:////app/data/agency.db

VOLUME ["/app/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/health/live || exit 1

CMD ["python", "-m", "agency", "serve", "--host", "0.0.0.0", "--port", "8000"]
