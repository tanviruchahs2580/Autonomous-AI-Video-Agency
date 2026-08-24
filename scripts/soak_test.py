"""Soak test: sustained mini-render loop; tracks RSS growth for leak signals.

Usage: python scripts/soak_test.py [--minutes 3]   → docs/evidence/soak_test.json
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BRIEF = {"title": "Soak", "objective": "Sustained render stability probe.", "audience": "sre", "platform": "youtube",
         "duration_s": 6, "width": 320, "height": 180, "fps": 24, "cta": "Go", "key_points": ["stability one", "stability two"]}


def rss_mb() -> float:
    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_uint32), ("PageFaultCount", ctypes.c_uint32),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

    if os.name != "nt":
        return -1.0
    pmc = PROCESS_MEMORY_COUNTERS()
    pmc.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
    k32 = ctypes.WinDLL("kernel32.dll")
    psapi = ctypes.WinDLL("Psapi.dll")
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    handle = k32.GetCurrentProcess()
    if psapi.GetProcessMemoryInfo(ctypes.c_void_p(handle), ctypes.byref(pmc), pmc.cb):
        return round(pmc.WorkingSetSize / (1024 * 1024), 1)
    return -2.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=3.0)
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="agency-soak-"))
    os.environ.update({
        "AGENCY_DB_URL": f"sqlite:///{(tmp / 'soak.db').as_posix()}",
        "AGENCY_DATA_DIR": str(tmp),
        "AGENCY_STORAGE_DIR": str(tmp / "storage"),
        "AGENCY_TTS_PROVIDER": "synth",
    })
    for mod in list(sys.modules):
        if mod.startswith("agency"):
            del sys.modules[mod]

    import agency.config as config_mod
    from agency.config import Settings

    settings = Settings(env="development", api_key="soak", db_url=os.environ["AGENCY_DB_URL"], storage_dir=tmp / "storage", data_dir=tmp, tts_provider="synth")
    config_mod.get_settings = lambda: settings  # type: ignore[assignment]
    import agency.db as db_mod

    for m in ("agency.db", "agency.agents.stages", "agency.capabilities.router", "agency.capabilities.tts", "agency.capabilities.media"):
        if m in sys.modules and hasattr(sys.modules[m], "get_settings"):
            setattr(sys.modules[m], "get_settings", lambda: settings)
    db_mod.reset_engine()
    from agency.db import init_db, session_scope

    init_db()
    from agency.agents.stages import HANDLERS
    from agency.models import Job, Project
    from agency.workflow.engine import WorkflowEngine, claim_job, create_job

    engine = WorkflowEngine(handlers=HANDLERS)
    counter = {"n": 0}
    failures: list[str] = []
    lock = __import__("threading").Lock()

    def one() -> None:
        with lock:
            counter["n"] += 1
            i = counter["n"]
        try:
            with session_scope() as db:
                p = Project(name=f"soak-{i}", org_id="default", brief_json=json.dumps(BRIEF))
                db.add(p)
                db.commit()
                job, _ = create_job(db, p.id, "production", {"brief": BRIEF}, idempotency_key=f"soak-{i}", org_id="default")
                jid = job.id
            with session_scope() as db:
                cj = claim_job(db, jid, "soak")
                res = engine.execute_job(db, cj, "soak")
                if res.state != "completed":
                    failures.append(f"{res.state}:{(res.error or '-')[:80]}")
        except Exception as exc:
            failures.append(str(exc)[:120])

    samples: list[dict] = []
    deadline = time.time() + args.minutes * 60
    print(f"soaking for {args.minutes} minutes on {os.cpu_count()} cpus...")
    while time.time() < deadline:
        batch_start = time.time()
        with ThreadPoolExecutor(max_workers=3) as ex:
            list(ex.map(lambda _: one(), range(3)))
        samples.append({"t": round(time.time() - deadline + args.minutes * 60, 1), "rss_mb": rss_mb()})
        if len(samples) % 10 == 0:
            print(f"jobs={counter['n']} rss={samples[-1]['rss_mb']}MB")

    first = samples[0]["rss_mb"] if samples else 0
    last = samples[-1]["rss_mb"] if samples else 0
    growth_pct = round((last - first) / max(first, 1) * 100, 1) if first > 0 else 0.0
    evidence = {
        "duration_minutes": args.minutes,
        "jobs_completed": counter["n"] - len(failures),
        "failures": failures[:5],
        "failure_count": len(failures),
        "rss_first_mb": first,
        "rss_last_mb": last,
        "rss_growth_pct": growth_pct,
        "leak_signal": bool(growth_pct > 50),
        "finished": datetime.now(timezone.utc).isoformat(),
    }
    out = ROOT / "docs" / "evidence" / "soak_test.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    db_mod.reset_engine()

    import shutil

    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if not failures and not evidence["leak_signal"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
