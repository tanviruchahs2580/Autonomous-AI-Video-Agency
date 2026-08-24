from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agents.registry import get_registry
from .config import ensure_dirs, get_settings
from .db import backup_database, init_db, session_scope
from .models import Job, Project
from .observability import configure_logging
from .workflow.engine import WorkflowEngine, claim_job, create_job


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agency", description="Autonomous AI Video Agency control CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate", help="apply database migrations")
    p_serve = sub.add_parser("serve", help="run API server")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_worker = sub.add_parser("worker", help="run production worker loop")
    p_worker.add_argument("--max-jobs", type=int, default=None)
    p_project = sub.add_parser("project", help="create project from brief JSON file")
    p_project.add_argument("--name", required=True)
    p_project.add_argument("--brief", required=True, help="path to brief json")
    p_run = sub.add_parser("run", help="create and execute a production job inline")
    p_run.add_argument("--brief", required=True)
    p_run.add_argument("--name", default=None, help="project name")
    p_run.add_argument("--out-dir", default=None, help="where deliverables land (informational)")
    sub.add_parser("status", help="show system status summary")
    p_backup = sub.add_parser("backup", help="backup database")
    p_backup.add_argument("--target", required=True)
    sub.add_parser("agents", help="print agent registry")
    p_cleanup = sub.add_parser("cleanup", help="artifact retention cleanup")
    p_cleanup.add_argument("--older-than-days", type=int, default=30)
    p_cleanup.add_argument("--apply", action="store_true", help="without this flag the run is dry-run only")
    p_cleanup.add_argument("--include-orphans", action="store_true")

    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)
    ensure_dirs(settings)

    if args.command == "migrate":
        applied = init_db()
        print(f"migrations applied: {applied or 'none pending'}")
        return 0

    init_db()

    if args.command == "serve":
        import uvicorn

        uvicorn.run("agency.api.main:app", host=args.host, port=args.port, log_level=settings.log_level.lower())
        return 0

    if args.command == "worker":
        from .worker import run_worker

        return run_worker(max_jobs=args.max_jobs)

    if args.command == "agents":
        print(json.dumps(get_registry(), indent=2))
        return 0

    if args.command == "cleanup":
        from agency.lifecycle import run_cleanup

        summary = run_cleanup(older_than_days=args.older_than_days, apply=args.apply, include_orphans=args.include_orphans)
        print(json.dumps(summary, indent=2))
        return 0

    if args.command == "status":
        with session_scope() as db:
            jobs = db.query(Job).all()
        by_state: dict[str, int] = {}
        for j in jobs:
            by_state[j.state] = by_state.get(j.state, 0) + 1
        print(json.dumps({"jobs_by_state": by_state}, indent=2))
        return 0

    if args.command == "backup":
        target = Path(args.target)
        backup_database(target)
        print(f"backup written to {target}")
        return 0

    brief_path = Path(args.brief)
    if not brief_path.exists():
        print(f"brief file not found: {brief_path}", file=sys.stderr)
        return 2
    brief = json.loads(brief_path.read_text(encoding="utf-8"))

    with session_scope() as db:
        project = Project(name=args.name if hasattr(args, "name") else Path(args.brief).stem, brief_json=json.dumps(brief))
        db.add(project)
        db.commit()
        project_id = project.id
        job, created = create_job(db, project_id=project_id, job_type="production", payload={"brief": brief}, idempotency_key=f"cli-{project_id}")
        job_id = job.id

    from .agents.stages import HANDLERS

    engine = WorkflowEngine(handlers=HANDLERS)
    with session_scope() as db:
        job = claim_job(db, job_id=job_id, worker_id="cli-inline")
        if job is None:
            print("job could not be claimed", file=sys.stderr)
            return 3
        result = engine.execute_job(db, job, worker_id="cli-inline")
        state = result.state
        output = {
            "project_id": project_id,
            "job_id": job.id,
            "state": state,
            "result": job.result,
            "error": job.error,
        }
    print(json.dumps(output, indent=2))
    return 0 if state == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())

