"""Load test: measures real API latency and concurrent render throughput on THIS host.

Usage: python scripts/load_test.py [--api-requests 200] [--api-concurrency 25] [--renders 10] [--render-concurrency 4]
Writes JSON evidence to docs/evidence/load_test.json
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BRIEF = {
    "title": "Load Probe",
    "objective": "Measure render throughput under concurrency with deterministic offline providers.",
    "audience": "load test",
    "platform": "youtube",
    "duration_s": 8,
    "width": 320,
    "height": 180,
    "fps": 24,
    "cta": "Go",
    "key_points": ["alpha point", "beta point"],
}


def percentiles(values: list[float]) -> dict:
    s = sorted(values)
    def p(q):
        return round(s[min(int(len(s) * q), len(s) - 1)] * 1000, 1) if s else None
    return {"p50_ms": p(0.50), "p95_ms": p(0.95), "p99_ms": p(0.99), "min_ms": round(s[0] * 1000, 1), "max_ms": round(s[-1] * 1000, 1), "n": len(s)}


def api_phase(base_url: str, key: str, total: int, concurrency: int) -> dict:
    import httpx

    latencies: list[float] = []
    errors = {"4xx": 0, "5xx": 0}
    lock = threading.Lock()

    def one(i: int) -> None:
        with httpx.Client(timeout=30.0) as c:
            t0 = time.perf_counter()
            r = c.post(
                f"{base_url}/v1/projects",
                headers={"X-API-Key": key},
                json={"name": f"load-{i}", "brief": BRIEF},
            )
            dt = time.perf_counter() - t0
            with lock:
                latencies.append(dt)
                if r.status_code >= 500:
                    errors["5xx"] += 1
                elif r.status_code >= 400:
                    errors["4xx"] += 1

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        list(ex.map(one, range(total)))
    wall = time.perf_counter() - start
    out = percentiles(latencies)
    out.update({"wall_s": round(wall, 2), "rps": round(total / wall, 1), "errors": errors})
    return out


def render_phase(concurrency: int, count: int, tmp: Path) -> dict:
    """Production-topology load test: enqueue N jobs, run `concurrency` separate worker processes."""
    import subprocess as _sp

    from agency.db import init_db, session_scope
    from agency.models import Job, Project
    from agency.workflow.engine import create_job

    init_db()
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    jids: list[str] = []
    t_enq0 = time.perf_counter()
    for i in range(count):
        with session_scope() as db:
            project = Project(name=f"render-{i}", org_id="default", brief_json=json.dumps(BRIEF))
            db.add(project)
            db.commit()
            job, _ = create_job(db, project.id, "production", {"brief": BRIEF}, idempotency_key=f"load-{i}", org_id="default")
            jids.append(job.id)
    enqueue_s = time.perf_counter() - t_enq0

    procs = []
    logs = []
    for w in range(concurrency):
        lf = open(tmp / f"worker-{w}.log", "wb")
        procs.append(_sp.Popen([sys.executable, "-m", "agency", "worker"], cwd=str(ROOT), env=env, stdout=lf, stderr=_sp.STDOUT))
        logs.append(lf)

    start = time.perf_counter()
    enq_times = {jid: time.time() for jid in jids}
    states: dict[str, str] = {}
    latencies: list[float] = []
    failed = 0
    deadline = time.time() + 900
    pending = set(jids)
    while pending and time.time() < deadline:
        time.sleep(2)
        with session_scope() as db:
            for jid in list(pending):
                j = db.get(Job, jid)
                if j is None:
                    pending.discard(jid)
                    continue
                if j.state in ("completed", "failed", "awaiting_approval"):
                    states[jid] = j.state
                    if j.state == "failed":
                        failed += 1
                    latencies.append(time.time() - enq_times[jid])
                    pending.discard(jid)
    wall = time.perf_counter() - start
    for p in procs:
        if p.poll() is None:
            p.terminate()
    for lf in logs:
        try:
            lf.close()
        except Exception:
            pass
    completed = sum(1 for s in states.values() if s == "completed")
    out = {
        "jobs": count,
        "workers": concurrency,
        "enqueue_s": round(enqueue_s, 2),
        "wall_s": round(wall, 2),
        "completed": completed,
        "failed": failed,
        "throughput_per_min": round(completed / max(wall, 0.001) * 60, 1),
        "queue_latency_s": percentiles(latencies) if latencies else None,
    }
    return out

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-requests", type=int, default=200)
    ap.add_argument("--api-concurrency", type=int, default=25)
    ap.add_argument("--renders", type=int, default=10)
    ap.add_argument("--render-concurrency", type=int, default=4)
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="agency-load-"))
    env = {
        **os.environ,
        "AGENCY_DB_URL": f"sqlite:///{(tmp / 'load.db').as_posix()}",
        "AGENCY_DATA_DIR": str(tmp),
        "AGENCY_STORAGE_DIR": str(tmp / "storage"),
        "AGENCY_TTS_PROVIDER": "synth",
        "AGENCY_RATE_LIMIT_PER_MIN": "1000000",
        "PYTHONPATH": str(ROOT),
    }
    server_log = open(tmp / "uvicorn.log", "wb")
    server = subprocess.Popen([sys.executable, "-m", "agency", "serve", "--port", "8931"], cwd=str(ROOT), env=env, stdout=server_log, stderr=subprocess.STDOUT)

    evidence = {"timestamp": datetime.now(timezone.utc).isoformat(), "host_cpus": os.cpu_count()}
    try:
        import httpx

        ready = False
        for _ in range(60):
            try:
                if httpx.get("http://127.0.0.1:8931/health/live", timeout=2).status_code == 200:
                    ready = True
                    break
            except Exception:
                time.sleep(1)
        assert ready, "server did not become ready"

        print("running API phase...")
        evidence["api"] = api_phase("http://127.0.0.1:8931", os.environ.get("AGENCY_API_KEY", "dev-key"), args.api_requests, args.api_concurrency)
        print(json.dumps(evidence["api"], indent=2))
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
        server_log.close()

    print("running render phase (worker processes)...")
    import agency.config as _cfg
    _cfg.get_settings.cache_clear()
    import agency.db as _dbm
    _dbm.reset_engine()
    evidence["renders"] = render_phase(args.render_concurrency, args.renders, tmp)
    print(json.dumps(evidence["renders"], indent=2))

    evidence_dir = ROOT / "docs" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    out_file = evidence_dir / "load_test.json"
    out_file.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(f"evidence written: {out_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
