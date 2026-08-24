from __future__ import annotations

import logging
import os
import signal
import sys
import time

from .config import ensure_dirs, get_settings
from .db import init_db, session_scope
from .models import Job
from .observability import configure_logging
from .workflow.engine import WorkflowEngine, claim_next_job, heartbeat


def run_worker(poll_seconds: float | None = None, max_jobs: int | None = None) -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = logging.getLogger("agency.worker")
    ensure_dirs(settings)
    init_db()
    from agency.agents.stages import HANDLERS as STAGE_HANDLERS
    engine = WorkflowEngine(handlers=STAGE_HANDLERS)
    poll = poll_seconds if poll_seconds is not None else settings.worker_poll_seconds
    worker_id = f"worker-{os.getpid()}"
    processed = 0
    logger.info("worker started: %s", worker_id)

    stop = False

    def _handle(signum, frame):
        nonlocal stop
        stop = True

    try:
        signal.signal(signal.SIGTERM, _handle)
        signal.signal(signal.SIGINT, _handle)
    except (ValueError, AttributeError):
        pass

    hb_thread_running = True

    def _heartbeat_loop():
        while hb_thread_running:
            time.sleep(5)
            try:
                from sqlalchemy import select

                with session_scope() as db:
                    rows = db.execute(select(Job).where(Job.state == "running")).scalars().all()
                    for j in rows:
                        heartbeat(j.id)
            except Exception:
                logger.exception("heartbeat failed")

    import threading

    threading.Thread(target=_heartbeat_loop, daemon=True).start()

    while not stop:
        if max_jobs is not None and processed >= max_jobs:
            break
        try:
            with session_scope() as db:
                job = claim_next_job(db, worker_id=worker_id)
            if job is None:
                try:
                    from agency.webhooks import process_pending_deliveries

                    with session_scope() as db:
                        stats = process_pending_deliveries(db)
                        if any(stats.values()):
                            logger.info("webhook deliveries processed: %s", stats)
                except Exception:
                    logger.exception("webhook delivery drain failed")
                time.sleep(poll)
                continue
            with session_scope() as db:
                fresh = db.merge(job)
                engine.execute_job(db, fresh, worker_id=worker_id)
            processed += 1
        except Exception:
            logger.exception("worker loop error")
            time.sleep(1.0)
    hb_thread_running = False
    logger.info("worker stopped after %d jobs", processed)
    return 0


if __name__ == "__main__":
    sys.exit(run_worker())

