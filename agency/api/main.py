from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy import text as sqltext

from agency import __version__
from agency.agents.registry import get_registry
from agency.capabilities.router import check_provider_health
from agency.config import ensure_dirs, get_settings
from agency.db import get_engine, init_db, session_scope
from agency.models import (
    Approval,
    Artifact,
    Asset,
    CostEntry,
    Deliverable,
    Event,
    Job,
    Project,
    QAReport,
    Repair,
    Task,
    User,
    now_iso,
)
from agency.observability import audit, new_request_id
from agency.security import (
    ROLE_PERMISSIONS,
    RateLimiter,
    generate_api_key,
    hash_api_key,
    safe_join,
    validate_extension,
    verify_api_key,
)
from agency.storage import sha256_file
from agency.workflow.engine import WorkflowEngine, claim_job, create_job

logger = logging.getLogger("agency.api")

app = FastAPI(title="Autonomous AI Video Agency", version=__version__, docs_url="/docs")
_rate = RateLimiter(get_settings().rate_limit_per_min)


@app.on_event("startup")
def _startup() -> None:
    settings = get_settings()
    ensure_dirs(settings)
    configure = logging.getLogger("agency")
    if not configure.handlers:
        from agency.observability import configure_logging

        configure_logging(settings.log_level)
    init_db()
    get_engine()


def _authenticate(request: Request, permission: str, x_api_key: str | None) -> User | None:
    request_id = getattr(request.state, "request_id", None) or new_request_id()
    request.state.request_id = request_id
    client_key = x_api_key or ""
    identity_key = f"{request.client.host if request.client else 'unknown'}"
    if not _rate.allow(identity_key):
        raise HTTPException(status_code=429, detail="rate limit exceeded", headers={"X-Request-ID": request_id})
    settings = get_settings()
    if not client_key:
        raise HTTPException(status_code=401, detail="missing API key", headers={"X-Request-ID": request_id})
    with session_scope() as db:
        user = db.execute(select(User).where(User.api_key_hash == hash_api_key(client_key))).scalar_one_or_none()
        if user is None:
            if settings.env == "development" and verify_api_key(client_key, hash_api_key(settings.api_key)):
                return None
            audit(db, "anonymous", "auth.denied", "request", request_id, {"reason": "invalid key"})
            raise HTTPException(status_code=401, detail="invalid API key", headers={"X-Request-ID": request_id})
        perms = ROLE_PERMISSIONS.get(user.role, set())
        if permission not in perms:
            audit(db, user.email, "authz.denied", "request", request_id, {"permission": permission})
            raise HTTPException(status_code=403, detail=f"role {user.role} lacks {permission}", headers={"X-Request-ID": request_id})
        db.expunge(user)
        return user


def _auth_factory(permission: str):
    def dep(request: Request, x_api_key: str | None = Header(default=None)) -> User | None:
        return _authenticate(request, permission, x_api_key)

    return dep


auth_read = _auth_factory("read")
auth_write = _auth_factory("write")
auth_approve = _auth_factory("approve")
auth_admin = _auth_factory("admin")


class BriefModel(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=2000)
    audience: str = Field(default="general", max_length=300)
    platform: str = Field(default="youtube", max_length=40)
    duration_s: float = Field(default=45, ge=5, le=3600)
    brand: dict = Field(default_factory=dict)
    cta: str = Field(default="Learn more", max_length=200)
    language: str = Field(default="en", max_length=10)
    key_points: list[str] = Field(default_factory=list, max_length=8)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    brief: BriefModel


class JobCreate(BaseModel):
    idempotency_key: str | None = Field(default=None, max_length=100)


class DecisionModel(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    note: str = Field(default="", max_length=500)


class ApiKeyIssue(BaseModel):
    email: str
    role: str = Field(default="viewer", pattern="^(viewer|editor|approver|admin)$")
    org_name: str = "default"


def error(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "detail": detail}})


@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = new_request_id()
    request.state.request_id = rid
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response


@app.get("/health/live")
def liveness():
    return {"status": "alive", "version": __version__}


@app.get("/health/ready")
def readiness():
    try:
        with session_scope() as db:
            db.execute(sqltext("SELECT 1"))
        return {"status": "ready", "database": "ok"}
    except Exception as exc:
        return JSONResponse(status_code=503, content={"status": "not_ready", "database": str(exc)[:200]})


@app.post("/v1/users/key")
def issue_key(body: ApiKeyIssue, _: None = Depends(auth_admin)):
    raw = generate_api_key()
    with session_scope() as db:
        org = db.execute(sqltext("SELECT id FROM organizations WHERE name=:n"), {"n": body.org_name}).first()
        if org is None:
            from agency.models import Org

            org_row = Org(name=body.org_name)
            db.add(org_row)
            db.commit()
            org_id = org_row.id
        else:
            org_id = org[0]
        existing = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
        if existing is not None:
            existing.api_key_hash = hash_api_key(raw)
            existing.role = body.role
        else:
            db.add(User(org_id=org_id, email=body.email, role=body.role, api_key_hash=hash_api_key(raw)))
        db.commit()
    return {"api_key": raw, "role": body.role}


@app.post("/v1/projects")
def create_project(body: ProjectCreate, request: Request, user=Depends(auth_write)):
    with session_scope() as db:
        project = Project(name=body.name, brief_json=body.brief.model_dump_json(), status="created")
        db.add(project)
        db.commit()
        with audit(db, user.email if user else "dev-key", "project.created", "project", project.id) as ctx:
            ctx["name"] = body.name
        return {"id": project.id, "name": project.name, "status": project.status}


@app.get("/v1/projects")
def list_projects(request: Request, page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100), user=Depends(auth_read)):
    with session_scope() as db:
        total = db.execute(select(func.count()).select_from(Project)).scalar() or 0
        rows = db.execute(
            select(Project).order_by(Project.created_at.desc()).limit(size).offset((page - 1) * size)
        ).scalars().all()
        return {"total": total, "page": page, "items": [{"id": p.id, "name": p.name, "status": p.status} for p in rows]}


@app.get("/v1/projects/{project_id}")
def get_project(project_id: str, user=Depends(auth_read)):
    with session_scope() as db:
        p = db.get(Project, project_id)
        if p is None:
            raise HTTPException(404, "project not found")
        jobs = db.execute(select(Job).where(Job.project_id == project_id)).scalars().all()
        return {
            "id": p.id,
            "name": p.name,
            "status": p.status,
            "brief": p.brief,
            "spec": p.spec,
            "jobs": [{"id": j.id, "state": j.state, "type": j.type} for j in jobs],
        }


@app.delete("/v1/projects/{project_id}", status_code=204)
def delete_project(project_id: str, request: Request, user=Depends(auth_write)):
    with session_scope() as db:
        p = db.get(Project, project_id)
        if p is None:
            raise HTTPException(404, "project not found")
        active = db.execute(select(Job).where(Job.project_id == project_id, Job.state.in_(["queued", "running", "retrying"]))).scalars().first()
        if active is not None:
            raise HTTPException(409, "project has active jobs; cancel them first")
        db.delete(p)
        db.commit()
    return PlainTextResponse("", status_code=204)


@app.post("/v1/projects/{project_id}/jobs")
def create_production_job(project_id: str, body: JobCreate, user=Depends(auth_write)):
    with session_scope() as db:
        p = db.get(Project, project_id)
        if p is None:
            raise HTTPException(404, "project not found")
        job, created = create_job(
            db,
            project_id=project_id,
            job_type="production",
            payload={"brief": p.brief},
            idempotency_key=body.idempotency_key,
        )
        if not created:
            return {"id": job.id, "state": job.state, "deduplicated": True}
        with audit(db, user.email if user else "dev-key", "job.created", "job", job.id):
            pass
        return {"id": job.id, "state": job.state, "deduplicated": False}


@app.get("/v1/jobs/{job_id}")
def get_job(job_id: str, user=Depends(auth_read)):
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        tasks = db.execute(select(Task).where(Task.job_id == job_id).order_by(Task.seq, Task.attempt)).scalars().all()
        repairs = db.execute(select(Repair).where(Repair.job_id == job_id)).scalars().all()
        qa = db.execute(select(QAReport).where(QAReport.job_id == job_id)).scalars().all()
        costs = db.execute(select(CostEntry).where(CostEntry.job_id == job_id)).scalars().all()
        return {
            "id": job.id,
            "state": job.state,
            "attempts": job.attempts,
            "repair_count": job.repair_count,
            "error": job.error,
            "result": job.result,
            "tasks": [
                {"seq": t.seq, "name": t.name, "agent": t.agent, "state": t.state, "attempt": t.attempt, "duration_ms": t.duration_ms, "error": t.error}
                for t in tasks
            ],
            "repairs": [{"failure_class": r.failure_class, "stage": r.stage, "plan": json.loads(r.plan_json), "applied": r.applied} for r in repairs],
            "qa_reports": [{"layer": q.layer, "passed": q.passed, "score": q.score, "findings": json.loads(q.findings_json)} for q in qa],
            "cost_usd": round(sum(c.amount_usd for c in costs), 6),
        }


@app.get("/v1/jobs")
def list_jobs(state: str | None = None, page: int = 1, size: int = 20, user=Depends(auth_read)):
    with session_scope() as db:
        q = select(Job).order_by(Job.created_at.desc())
        if state:
            q = q.where(Job.state == state)
        total = db.execute(select(func.count()).select_from(Job)).scalar() or 0
        rows = db.execute(q.limit(size).offset((page - 1) * size)).scalars().all()
        return {"total": total, "items": [{"id": j.id, "project_id": j.project_id, "state": j.state} for j in rows]}


@app.post("/v1/jobs/{job_id}/cancel")
def cancel_job(job_id: str, user=Depends(auth_write)):
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        if job.state in ("completed", "failed", "cancelled"):
            raise HTTPException(409, f"cannot cancel job in state {job.state}")
        job.state = "cancelled"
        job.finished_at = now_iso()
        db.commit()
        return {"id": job.id, "state": job.state}


@app.post("/v1/approvals/{approval_or_job}/decision")
def decide_approval(approval_or_job: str, body: DecisionModel, user=Depends(auth_approve)):
    with session_scope() as db:
        approval = db.get(Approval, approval_or_job)
        if approval is None:
            approval = db.execute(
                select(Approval).where(Approval.job_id == approval_or_job, Approval.status == "requested").order_by(Approval.requested_at.desc())
            ).scalars().first()
        if approval is None:
            raise HTTPException(404, "no pending approval found")
        approval.status = body.decision
        approval.note = body.note
        approval.decided_at = now_iso()
        approval.decided_by = user.email if user else "dev-key"
        job = db.get(Job, approval.job_id)
        if job is not None and job.state == "awaiting_approval":
            if body.decision == "approved":
                job.state = "queued"
                job.heartbeat_at = None
            else:
                job.state = "failed"
                job.error = f"rejected at approval gate: {body.note}"
                job.finished_at = now_iso()
        db.commit()
        return {"approval_id": approval.id, "status": approval.status, "job_state": job.state if job else None}


@app.post("/v1/projects/{project_id}/assets")
async def upload_asset(project_id: str, request: Request, file: UploadFile = File(...), license_state: str = Query(default="unknown"), user=Depends(auth_write)):
    settings = get_settings()
    with session_scope() as db:
        p = db.get(Project, project_id)
        if p is None:
            raise HTTPException(404, "project not found")
        try:
            ext = validate_extension(file.filename or "")
        except ValueError as exc:
            return error(415, "unsupported_media_type", str(exc))
        data = await file.read()
        if len(data) > settings.max_upload_mb * 1024 * 1024:
            return error(413, "payload_too_large", f"max {settings.max_upload_mb} MB")
        assets_dir = safe_join(settings.data_dir, "uploads", project_id)
        assets_dir.mkdir(parents=True, exist_ok=True)
        import secrets

        dest = assets_dir / f"{secrets.token_hex(8)}{ext}"
        dest.write_bytes(data)
        from agency.security import validate_upload

        try:
            meta = validate_upload(dest, ext, settings.max_upload_mb * 1024 * 1024)
        except ValueError as exc:
            dest.unlink(missing_ok=True)
            return error(415, "malicious_or_invalid_file", str(exc))
        asset = Asset(
            project_id=project_id,
            kind="upload",
            source_uri=file.filename or dest.name,
            storage_key=str(dest),
            sha256=sha256_file(dest),
            bytes=len(data),
            license_state=license_state,
        )
        asset.license = {"state": license_state}
        asset.meta = {"sniffed_kind": meta["sniffed_kind"]}
        db.add(asset)
        db.commit()
        with audit(db, user.email if user else "dev-key", "asset.uploaded", "asset", asset.id):
            pass
        return {"id": asset.id, "sha256": asset.sha256, "license_state": asset.license_state, "bytes": asset.bytes}


@app.get("/v1/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: str, user=Depends(auth_read)):
    with session_scope() as db:
        art = db.get(Artifact, artifact_id)
        if art is None:
            raise HTTPException(404, "artifact not found")
        path = Path(art.storage_key)
        if not path.exists():
            raise HTTPException(410, "artifact file missing from storage")
        return FileResponse(path, filename=path.name)


@app.get("/v1/deliverables")
def list_deliverables(project_id: str | None = None, page: int = 1, size: int = 50, user=Depends(auth_read)):
    with session_scope() as db:
        q = select(Deliverable).order_by(Deliverable.created_at.desc())
        if project_id:
            q = q.where(Deliverable.project_id == project_id)
        rows = db.execute(q.limit(size).offset((page - 1) * size)).scalars().all()
        return {
            "items": [
                {
                    "id": d.id,
                    "platform": d.platform,
                    "path": d.storage_key,
                    "manifest": json.loads(d.manifest_json),
                }
                for d in rows
            ]
        }


@app.get("/v1/deliverables/{deliverable_id}/download")
def download_deliverable(deliverable_id: str, user=Depends(auth_read)):
    settings = get_settings()
    with session_scope() as db:
        d = db.get(Deliverable, deliverable_id)
        if d is None:
            raise HTTPException(404, "deliverable not found")
        try:
            path = safe_join(settings.data_dir, Path(d.storage_key))
        except ValueError:
            raise HTTPException(400, "invalid storage path") from None
        if not path.exists():
            raise HTTPException(410, "deliverable file missing from storage")
        return FileResponse(path, filename=path.name, media_type="video/mp4")


@app.post("/v1/jobs/{job_id}/run", response_model=None)
def run_job_inline(job_id: str, user=Depends(auth_write)):
    from .agents.stages import HANDLERS

    engine = WorkflowEngine(handlers=HANDLERS)
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        if job.state in ("running",):
            raise HTTPException(409, "job already running")
        job.state = "queued"
        job.heartbeat_at = None
        db.commit()
        claimed = claim_job(db, job_id=job.id, worker_id="inline-api")
        if claimed is None:
            return {"id": job.id, "state": "queued", "note": "job not claimable in current state"}
        engine.execute_job(db, claimed, worker_id="inline-api")
        db.refresh(claimed)
        return {"id": claimed.id, "state": claimed.state, "result": claimed.result}


@app.get("/v1/costs")
def cost_summary(project_id: str | None = None, user=Depends(auth_read)):
    with session_scope() as db:
        q = select(CostEntry)
        if project_id:
            q = q.where(CostEntry.project_id == project_id)
        rows = db.execute(q).scalars().all()
        by_category: dict[str, float] = {}
        by_provider: dict[str, float] = {}
        for c in rows:
            by_category[c.category] = round(by_category.get(c.category, 0.0) + c.amount_usd, 6)
            by_provider[c.provider] = round(by_provider.get(c.provider, 0.0) + c.amount_usd, 6)
        return {"total_usd": round(sum(c.amount_usd for c in rows), 6), "by_category": by_category, "by_provider": by_provider}


@app.get("/v1/events")
def recent_events(job_id: str | None = None, limit: int = Query(100, le=1000), user=Depends(auth_read)):
    with session_scope() as db:
        q = select(Event).order_by(Event.ts.desc()).limit(limit)
        if job_id:
            q = q.where(Event.job_id == job_id)
        rows = db.execute(q).scalars().all()
        return {"events": [{"ts": e.ts, "level": e.level, "event": e.event, "job_id": e.job_id, "data": json.loads(e.data_json)} for e in rows]}


@app.get("/v1/system/status")
def system_status(user=Depends(auth_read)):
    providers = {}
    for name in ("openai", "comfyui", "edge-tts", "local-deterministic"):
        h = check_provider_health(name)
        providers[name] = {"healthy": h.healthy, "detail": h.detail}
    with session_scope() as db:
        counts = {}
        for state in ("queued", "running", "awaiting_approval", "failed", "completed"):
            n = db.execute(select(func.count()).select_from(Job).where(Job.state == state)).scalar() or 0
            counts[state] = n
    return {"version": __version__, "providers": providers, "queue": counts, "registry_agents_active": len([a for a in get_registry() if a["status"] == "active"])}


