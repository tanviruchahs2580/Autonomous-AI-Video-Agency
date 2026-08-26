from __future__ import annotations

import json
import logging
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy import text as sqltext

from agency import __version__
from agency.agents.registry import get_registry
from agency.auth import hash_password, make_token, verify_password, verify_token
from agency.capabilities.media import MediaError
from agency.capabilities.media import probe as media_probe
from agency.capabilities.router import check_provider_health
from agency.config import ensure_dirs, get_settings
from agency.db import get_engine, init_db, session_scope
from agency.metrics import METRICS
from agency.models import (
    Approval,
    Artifact,
    Asset,
    Budget,
    CostEntry,
    Deliverable,
    Event,
    Job,
    Org,
    Project,
    QAReport,
    Repair,
    Task,
    Tenant,
    User,
    Webhook,
    now_iso,
)
from agency.models_platform import BrandKit, Campaign, Client, DeliverableReview, NotificationRecord, ScriptRevision
from agency.observability import audit, new_request_id
from agency.security import (
    RateLimiter,
    assert_public_url,
    generate_api_key,
    hash_api_key,
    permissions_for,
    resolve_role,
    safe_join,
    validate_extension,
    verify_api_key,
)
from agency.storage import sha256_file
from agency.webhooks import WEBHOOK_EVENT_TYPES, check_budget, dispatch_event, process_pending_deliveries
from agency.workflow.engine import WorkflowEngine, claim_job, create_job, notify_webhooks

logger = logging.getLogger("agency.api")

app = FastAPI(title="Autonomous AI Video Agency", version=__version__, docs_url="/docs")

# ── STATIC FRONTEND ────────────────────────────────────────────────────────
_static_dir = Path(__file__).resolve().parent.parent / "static"
if _static_dir.exists():
    app.mount("/app", StaticFiles(directory=str(_static_dir), html=True), name="dashboard")

    @app.get("/", include_in_schema=False)
    def _root_redirect():
        return RedirectResponse(url="/app/dashboard.html")
_rate = RateLimiter(get_settings().rate_limit_per_min)

_settings_boot = get_settings()
if _settings_boot.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in _settings_boot.cors_origins.split(",") if o.strip()],
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["X-API-Key", "Content-Type"],
    )


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    rid = new_request_id()
    request.state.request_id = rid
    request.state.tenant_id = None
    import time as _time

    started = _time.monotonic()
    try:
        response = await call_next(request)
    except Exception:
        METRICS.inc("agency_api_requests_total", {"status": "500"})
        raise
    duration = _time.monotonic() - started
    status = response.status_code
    path_group = request.scope.get("route").path if request.scope.get("route") else request.url.path
    METRICS.inc("agency_api_requests_total", {"method": request.method, "path": path_group, "status": str(status)})
    METRICS.observe("agency_api_request_latency_seconds", duration)
    METRICS.inc("agency_api_errors_total" if status >= 500 else "agency_client_errors_total" if status >= 400 else "agency_api_ok_total", {"method": request.method})
    response.headers["X-Request-ID"] = rid
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


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
        if user.api_key_revoked_at is not None:
            audit(db, user.email, "auth.denied", "request", request_id, {"reason": "revoked key"}, org_id=user.org_id)
            raise HTTPException(status_code=401, detail="API key revoked", headers={"X-Request-ID": request_id})
        if user.api_key_expires_at is not None and user.api_key_expires_at < datetime.now(UTC).isoformat():
            audit(db, user.email, "auth.denied", "request", request_id, {"reason": "expired key"}, org_id=user.org_id)
            raise HTTPException(status_code=401, detail="API key expired", headers={"X-Request-ID": request_id})
        perms = permissions_for(user.role)
        if permission not in perms:
            audit(db, user.email, "authz.denied", "request", request_id, {"permission": permission}, org_id=user.org_id)
            raise HTTPException(status_code=403, detail=f"role {user.role} lacks {permission}", headers={"X-Request-ID": request_id})
        request.state.tenant_id = user.org_id
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
auth_audit = _auth_factory("audit")


# ── AUTHENTICATION (JWT for frontend) ────────────────────────────────────────

class RegisterModel(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=8, max_length=128)
    tenant_name: str = Field(default="", max_length=100)


@app.post("/auth/register")
def register(body: RegisterModel):
    with session_scope() as db:
        existing = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(409, "email already registered")
        from agency.models import uid
        if body.tenant_name:
            tenant_id = uid()
            db.add(Tenant(id=tenant_id, name=body.tenant_name))
            db.commit()
            db.add(Org(id=tenant_id, name=body.tenant_name))
            org_id = tenant_id
        else:
            org_id = "default"
        pw_hash = hash_password(body.password)
        user = User(org_id=org_id, email=body.email, role="admin", api_key_hash=pw_hash)
        db.add(user)
        db.commit()
    token = make_token({"sub": body.email, "org": org_id, "role": "admin"})
    return {"access_token": token, "token_type": "bearer", "email": body.email}


class LoginModel(BaseModel):
    email: str
    password: str


@app.post("/auth/login")
def login(body: LoginModel):
    with session_scope() as db:
        user = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
        if user is None:
            raise HTTPException(401, "invalid credentials")
        if not verify_password(body.password, user.api_key_hash):
            raise HTTPException(401, "invalid credentials")
        token = make_token({"sub": user.email, "org": user.org_id, "role": user.role})
    return {"access_token": token, "token_type": "bearer", "email": user.email}


def _jwt_payload(request: Request):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    payload = verify_token(auth_header[7:])
    if payload is None:
        raise HTTPException(401, "invalid or expired token")
    return payload


# ── CLIENTS ──────────────────────────────────────────────────────────────────

class ClientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


@app.post("/v1/clients")
def create_client(body: ClientCreate, request: Request):
    p = _jwt_payload(request)
    with session_scope() as db:
        c = Client(org_id=p["org"], name=body.name)
        db.add(c)
        db.commit()
        return {"id": c.id, "name": c.name}


@app.get("/v1/clients")
def list_clients(request: Request):
    p = _jwt_payload(request)
    with session_scope() as db:
        rows = db.execute(select(Client).where(Client.org_id == p["org"])).scalars().all()
        return {"items": [{"id": c.id, "name": c.name} for c in rows]}


# ── BRAND KITS ───────────────────────────────────────────────────────────────

class BrandKitCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    palette: list[str] = Field(default_factory=list)


@app.post("/v1/brand-kits")
def create_brand_kit(body: BrandKitCreate, request: Request):
    p = _jwt_payload(request)
    with session_scope() as db:
        bk = BrandKit(org_id=p["org"], name=body.name, palette_json=json.dumps(body.palette))
        db.add(bk)
        db.commit()
        return {"id": bk.id, "name": bk.name}


@app.get("/v1/brand-kits")
def list_brand_kits(request: Request):
    p = _jwt_payload(request)
    with session_scope() as db:
        rows = db.execute(select(BrandKit).where(BrandKit.org_id == p["org"])).scalars().all()
        return {"items": [{"id": b.id, "name": b.name, "palette": json.loads(b.palette_json)} for b in rows]}


# ── CAMPAIGNS ────────────────────────────────────────────────────────────────

class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    client_id: str | None = None


@app.post("/v1/campaigns")
def create_campaign(body: CampaignCreate, request: Request):
    p = _jwt_payload(request)
    with session_scope() as db:
        c = Campaign(org_id=p["org"], client_id=body.client_id, name=body.name)
        db.add(c)
        db.commit()
        return {"id": c.id, "name": c.name}


@app.get("/v1/campaigns")
def list_campaigns(request: Request):
    p = _jwt_payload(request)
    with session_scope() as db:
        rows = db.execute(select(Campaign).where(Campaign.org_id == p["org"])).scalars().all()
        return {"items": [{"id": c.id, "name": c.name, "client_id": c.client_id} for c in rows]}


# ── SCRIPT REVISION ──────────────────────────────────────────────────────────

class ScriptRevisionModel(BaseModel):
    hook: str = Field(max_length=500)
    beats: list[str] = Field(max_length=5)
    cta: str = Field(max_length=300)


@app.patch("/v1/projects/{project_id}/script")
def revise_script(project_id: str, body: ScriptRevisionModel, request: Request):
    p = _jwt_payload(request)
    tid = p["org"]
    with session_scope() as db:
        proj = db.execute(select(Project).where(Project.id == project_id, Project.org_id == tid)).scalar_one_or_none()
        if proj is None:
            raise HTTPException(404, "not found")
        sections = {"hook": body.hook, "beats": body.beats, "cta": body.cta}
        full_text = f"{body.hook} {' '.join(body.beats)} {body.cta}"
        rev_count = db.execute(select(func.count()).select_from(ScriptRevision).where(ScriptRevision.project_id == project_id)).scalar() or 0
        rev = ScriptRevision(project_id=project_id, version=rev_count + 2, sections_json=json.dumps(sections), full_text=full_text, edited_by=p["sub"])
        db.add(rev)
        db.commit()
        return {"version": rev.version, "message": "Script revised. Create a new job to re-render."}


@app.get("/v1/projects/{project_id}/script/revisions")
def list_script_revisions(project_id: str, request: Request):
    _jwt_payload(request)
    with session_scope() as db:
        rows = db.execute(select(ScriptRevision).where(ScriptRevision.project_id == project_id).order_by(ScriptRevision.version)).scalars().all()
        return {"items": [{"version": r.version, "full_text": r.full_text} for r in rows]}


# ── DELIVERABLE REVIEW ───────────────────────────────────────────────────────

class ReviewAction(BaseModel):
    action: str = Field(pattern="^(submit_review|approve|request_changes|comment)$")
    comment: str = Field(default="", max_length=1000)


@app.post("/v1/deliverables/{deliverable_id}/review")
def review_deliverable(deliverable_id: str, body: ReviewAction, request: Request):
    p = _jwt_payload(request)
    with session_scope() as db:
        d = db.get(Deliverable, deliverable_id)
        if d is None:
            raise HTTPException(404, "not found")
        manifest = json.loads(d.manifest_json)
        current = manifest.get("approval_status", "draft")
        review = DeliverableReview(deliverable_id=deliverable_id, reviewer=p["sub"], action=body.action, comment=body.comment)
        db.add(review)
        new_status = current
        if body.action == "submit_review":
            new_status = "internal_review"
        elif body.action == "approve":
            new_status = "approved"
        elif body.action == "request_changes":
            new_status = "changes_requested"
        manifest["approval_status"] = new_status
        d.manifest = manifest
        db.commit()
        return {"deliverable_id": deliverable_id, "status": new_status}


@app.get("/v1/deliverables/{deliverable_id}/reviews")
def list_reviews(deliverable_id: str, request: Request):
    with session_scope() as db:
        rows = db.execute(select(DeliverableReview).where(DeliverableReview.deliverable_id == deliverable_id)).scalars().all()
        return {"items": [{"reviewer": r.reviewer, "action": r.action, "comment": r.comment} for r in rows]}


# ── NOTIFICATIONS ────────────────────────────────────────────────────────────

@app.get("/v1/notifications")
def list_notifications(request: Request):
    p = _jwt_payload(request)
    with session_scope() as db:
        rows = db.execute(select(NotificationRecord).where(NotificationRecord.org_id == p["org"]).order_by(NotificationRecord.created_at.desc()).limit(50)).scalars().all()
        unread = sum(1 for n in rows if n.read_at is None)
        return {"unread_count": unread, "items": [{"id": n.id, "title": n.title, "read": n.read_at is not None} for n in rows]}


def tenant_of(user: User | None) -> str:
    return user.org_id if user is not None and user.org_id else "default"


def actor_name(user: User | None) -> str:
    return user.email if user is not None else "dev-key"


async def _read_upload_and_validate(file: UploadFile, dest: Path) -> dict:
    settings = get_settings()
    ext = validate_extension(file.filename or "")
    data = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(data) <= 0:
        raise ValueError("empty file")
    if len(data) > max_bytes:
        raise ValueError(f"file exceeds maximum allowed size of {settings.max_upload_mb} MB")
    dest.write_bytes(data)
    from agency.security import sniff_kind

    head = data[:64]
    kind = sniff_kind(head)
    media_exts = {".mp4", ".mov", ".webm", ".mkv", ".mp3", ".wav", ".m4a", ".png", ".jpg", ".jpeg"}
    if ext in media_exts and kind is None:
        raise ValueError("file content does not match a known safe media signature")
    meta: dict = {"size": len(data), "sniffed_kind": kind}
    if settings.upload_probe_enabled and ext in {".mp4", ".mov", ".webm", ".mkv", ".mp3", ".wav", ".m4a"}:
        try:
            info = media_probe(dest)
        except MediaError as exc:
            raise ValueError(f"media probe failed: {exc}") from exc
        if info.duration_s > settings.media_max_duration_s:
            raise ValueError(f"media duration {info.duration_s:.0f}s exceeds cap {settings.media_max_duration_s}s")
        if (info.width or 0) > settings.media_max_width or (info.height or 0) > settings.media_max_height:
            raise ValueError("media resolution exceeds platform cap")
        allowed_v = {c.strip() for c in settings.allowed_video_codecs.split(",")}
        allowed_a = {c.strip() for c in settings.allowed_audio_codecs.split(",")}
        if info.video_codec and info.video_codec not in allowed_v:
            raise ValueError(f"video codec {info.video_codec} not allowed")
        if info.audio_codec and info.audio_codec not in allowed_a:
            raise ValueError(f"audio codec {info.audio_codec} not allowed")
        meta["probe"] = {"duration_s": round(info.duration_s, 2), "resolution": f"{info.width}x{info.height}", "video_codec": info.video_codec, "audio_codec": info.audio_codec}
    return meta


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


def error(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "detail": detail}})


class ApiKeyIssue(BaseModel):
    email: str
    role: str = Field(default="client", pattern="^(owner|admin|producer|editor|reviewer|client|auditor|service_account|viewer|approver)$")
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class WebhookCreate(BaseModel):
    url: str = Field(min_length=8, max_length=500)
    events: list[str] = Field(default_factory=list, max_length=10)


class BudgetCreate(BaseModel):
    project_id: str | None = None
    max_cost_per_job_usd: float | None = Field(default=None, ge=0)
    daily_limit_usd: float | None = Field(default=None, ge=0)
    monthly_limit_usd: float | None = Field(default=None, ge=0)


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


class TenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    admin_email: str = Field(min_length=3, max_length=200)


@app.post("/v1/tenants")
def create_tenant(body: TenantCreate, user=Depends(auth_admin)):
    raw = generate_api_key()
    with session_scope() as db:
        existing_user = db.execute(select(User).where(User.email == body.admin_email)).scalar_one_or_none()
        if existing_user is not None:
            raise HTTPException(409, "email already exists")
        from agency.models import uid

        tenant = Tenant(id=uid(), name=body.name)
        db.add(tenant)
        db.commit()
        db.add(Org(id=tenant.id, name=body.name))
        db.add(User(org_id=tenant.id, email=body.admin_email, role="admin", api_key_hash=hash_api_key(raw)))
        db.commit()
        audit(db, actor_name(user), "tenant.created", "tenant", tenant.id, {"name": body.name}, org_id=tenant.id)
        return {"tenant_id": tenant.id, "admin_api_key": raw}


@app.post("/v1/users/key")
def issue_key(body: ApiKeyIssue, user=Depends(auth_admin)):
    raw = generate_api_key()
    with session_scope() as db:
        org_id = tenant_of(user)
        existing = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
        expires_at = (
            (datetime.now(UTC) + timedelta(days=body.expires_in_days)).isoformat() if body.expires_in_days else None
        )
        role = resolve_role(body.role)
        if existing is not None:
            if existing.org_id != org_id:
                raise HTTPException(404, "user not found in your tenant")
            existing.api_key_hash = hash_api_key(raw)
            existing.role = role
            existing.api_key_expires_at = expires_at
            existing.api_key_revoked_at = None
        else:
            db.add(User(org_id=org_id, email=body.email, role=role, api_key_hash=hash_api_key(raw), api_key_expires_at=expires_at))
        db.commit()
        audit(db, actor_name(user), "key.issued", "user", body.email, {"role": role, "expires": bool(expires_at)}, org_id=org_id)
    return {"api_key": raw, "role": role, "expires_at": expires_at}


@app.delete("/v1/users/{email}/key")
def revoke_key(email: str, user=Depends(auth_admin)):
    with session_scope() as db:
        target = db.execute(select(User).where(User.email == email, User.org_id == tenant_of(user))).scalar_one_or_none()
        if target is None:
            raise HTTPException(404, "user not found in your tenant")
        target.api_key_revoked_at = now_iso()
        db.commit()
        audit(db, actor_name(user), "key.revoked", "user", email, {}, org_id=tenant_of(user))
    return {"email": email, "revoked": True}


@app.post("/v1/projects")
def create_project(body: ProjectCreate, request: Request, user=Depends(auth_write)):
    with session_scope() as db:
        project = Project(name=body.name, brief_json=body.brief.model_dump_json(), status="created", org_id=tenant_of(user))
        db.add(project)
        db.commit()
        with audit(db, actor_name(user), "project.created", "project", project.id, {"name": body.name}, org_id=tenant_of(user)):
            pass
        return {"id": project.id, "name": project.name, "status": project.status}


@app.get("/v1/projects")
def list_projects(request: Request, page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100), user=Depends(auth_read)):
    tid = tenant_of(user)
    with session_scope() as db:
        base = select(Project).where(Project.org_id == tid)
        total = db.execute(select(func.count()).select_from(base.subquery())).scalar() or 0
        rows = db.execute(base.order_by(Project.created_at.desc()).limit(size).offset((page - 1) * size)).scalars().all()
        return {"total": total, "page": page, "items": [{"id": p.id, "name": p.name, "status": p.status} for p in rows]}


@app.get("/v1/projects/{project_id}")
def get_project(project_id: str, user=Depends(auth_read)):
    tid = tenant_of(user)
    with session_scope() as db:
        p = db.execute(select(Project).where(Project.id == project_id, Project.org_id == tid)).scalar_one_or_none()
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
    tid = tenant_of(user)
    with session_scope() as db:
        p = db.execute(select(Project).where(Project.id == project_id, Project.org_id == tid)).scalar_one_or_none()
        if p is None:
            raise HTTPException(404, "project not found")
        active = db.execute(select(Job).where(Job.project_id == project_id, Job.state.in_(["queued", "running", "retrying"]))).scalars().first()
        if active is not None:
            raise HTTPException(409, "project has active jobs; cancel them first")
        db.delete(p)
        db.commit()
        audit(db, actor_name(user), "project.deleted", "project", project_id, {}, org_id=tid)
    return PlainTextResponse("", status_code=204)


@app.post("/v1/projects/{project_id}/jobs")
def create_production_job(project_id: str, body: JobCreate, user=Depends(auth_write)):
    settings = get_settings()
    with session_scope() as db:
        p = db.execute(select(Project).where(Project.id == project_id, Project.org_id == tenant_of(user))).scalar_one_or_none()
        if p is None:
            raise HTTPException(404, "project not found")
        estimate = settings.default_job_cost_estimate_usd
        verdict = check_budget(db, tenant_of(user), project_id, estimate)
        if not verdict["allowed"]:
            audit(db, actor_name(user), "job.rejected_budget", "project", project_id, {"reason": verdict["reason"]}, org_id=tenant_of(user))
            return error(402, "budget_exceeded", verdict["reason"])
        job, created = create_job(
            db,
            project_id=project_id,
            job_type="production",
            payload={"brief": p.brief},
            idempotency_key=body.idempotency_key,
            org_id=tenant_of(user),
        )
        if not created:
            return {"id": job.id, "state": job.state, "deduplicated": True}
        with audit(db, actor_name(user), "job.created", "job", job.id, {}, org_id=tenant_of(user)):
            pass
        return {"id": job.id, "state": job.state, "deduplicated": False}


@app.get("/v1/jobs/{job_id}")
def get_job(job_id: str, user=Depends(auth_read)):
    tid = tenant_of(user)
    with session_scope() as db:
        job = db.execute(select(Job).where(Job.id == job_id, Job.org_id == tid)).scalar_one_or_none()
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


@app.post("/v1/projects/{project_id}/assets")
async def upload_asset(project_id: str, request: Request, file: UploadFile = File(...), license_state: str = Query(default="unknown"), user=Depends(auth_write)):
    settings = get_settings()
    with session_scope() as db:
        p = db.execute(select(Project).where(Project.id == project_id, Project.org_id == tenant_of(user))).scalar_one_or_none()
        if p is None:
            raise HTTPException(404, "project not found")
        try:
            ext = validate_extension(file.filename or "")
        except ValueError as exc:
            return error(415, "unsupported_media_type", str(exc))
        assets_dir = safe_join(settings.data_dir, "uploads", project_id)
        assets_dir.mkdir(parents=True, exist_ok=True)
        dest = assets_dir / f"{secrets.token_hex(8)}{ext}"
        try:
            meta = await _read_upload_and_validate(file, dest)
        except ValueError as exc:
            dest.unlink(missing_ok=True)
            return error(415, "malicious_or_invalid_file", str(exc))
        asset = Asset(
            project_id=project_id,
            org_id=tenant_of(user),
            kind="upload",
            source_uri=file.filename or dest.name,
            storage_key=str(dest),
            sha256=sha256_file(dest),
            bytes=meta["size"],
            license_state=license_state,
        )
        asset.license = {"state": license_state}
        asset.meta = {"sniffed_kind": meta.get("sniffed_kind"), "probe": meta.get("probe")}
        db.add(asset)
        db.commit()
        with audit(db, actor_name(user), "asset.uploaded", "asset", asset.id, {"bytes": meta["size"]}, org_id=tenant_of(user)):
            pass
        return {"id": asset.id, "sha256": asset.sha256, "license_state": asset.license_state, "bytes": asset.bytes, "probe": meta.get("probe")}


@app.get("/v1/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: str, user=Depends(auth_read)):
    tid = tenant_of(user)
    with session_scope() as db:
        art = db.get(Artifact, artifact_id)
        if art is None or (art.project_id and not _project_in_tenant(db, art.project_id, tid)):
            raise HTTPException(404, "artifact not found")
        path = Path(art.storage_key)
        if not path.exists():
            raise HTTPException(410, "artifact file missing from storage")
        with audit(db, actor_name(user), "artifact.downloaded", "artifact", artifact_id, {}, org_id=tid):
            pass
        return FileResponse(path, filename=path.name)


def _project_in_tenant(db, project_id: str, tenant: str) -> bool:
    row = db.execute(sqltext("SELECT org_id FROM projects WHERE id=:p"), {"p": project_id}).first()
    return bool(row) and (row[0] == tenant or (row[0] is None and tenant == "default"))


@app.get("/v1/deliverables")
def list_deliverables(project_id: str | None = None, page: int = 1, size: int = 50, user=Depends(auth_read)):
    tid = tenant_of(user)
    with session_scope() as db:
        tenant_project_ids = [row[0] for row in db.execute(sqltext("SELECT id FROM projects WHERE org_id=:o OR org_id IS NULL"), {"o": tid}).fetchall()]
        q = select(Deliverable).where(Deliverable.project_id.in_(tenant_project_ids or ["-"])).order_by(Deliverable.created_at.desc())
        if project_id:
            if project_id not in tenant_project_ids:
                return {"items": []}
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
    tid = tenant_of(user)
    with session_scope() as db:
        d = db.get(Deliverable, deliverable_id)
        if d is None or not _project_in_tenant(db, d.project_id, tid):
            raise HTTPException(404, "deliverable not found")
        try:
            path = safe_join(settings.data_dir, Path(d.storage_key))
        except ValueError:
            raise HTTPException(400, "invalid storage path") from None
        if not path.exists():
            raise HTTPException(410, "deliverable file missing from storage")
        with audit(db, actor_name(user), "deliverable.downloaded", "deliverable", deliverable_id, {}, org_id=tid):
            pass
        return FileResponse(path, filename=path.name, media_type="video/mp4")


@app.post("/v1/jobs/{job_id}/run", response_model=None)
def run_job_inline(job_id: str, user=Depends(auth_write)):
    from agency.agents.stages import HANDLERS

    engine = WorkflowEngine(handlers=HANDLERS)
    tid = tenant_of(user)
    with session_scope() as db:
        job = db.execute(select(Job).where(Job.id == job_id, Job.org_id == tid)).scalar_one_or_none()
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
        started = datetime.now(UTC)
        engine.execute_job(db, claimed, worker_id="inline-api")
        db.refresh(claimed)
        METRICS.inc("agency_jobs_total", {"state": claimed.state})
        METRICS.observe("agency_job_total_duration_seconds", (datetime.now(UTC) - started).total_seconds())
        notify_webhooks_inline(db, claimed)
        return {"id": claimed.id, "state": claimed.state, "result": claimed.result}


def notify_webhooks_inline(db, job: Job) -> None:
    from agency.workflow.engine import notify_webhooks

    if job.state == "completed":
        notify_webhooks(db, job.org_id, "job.completed", {"job_id": job.id})


@app.get("/v1/costs")
def cost_summary(project_id: str | None = None, user=Depends(auth_read)):
    tid = tenant_of(user)
    with session_scope() as db:
        q = select(CostEntry).where(CostEntry.org_id == tid)
        if project_id:
            if not _project_in_tenant(db, project_id, tid):
                raise HTTPException(404, "project not found")
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
    tid = tenant_of(user)
    with session_scope() as db:
        q = select(Event).where(Event.org_id == tid).order_by(Event.ts.desc()).limit(limit)
        if job_id:
            owned = db.execute(select(Job.id).where(Job.id == job_id, Job.org_id == tid)).scalar_one_or_none()
            if owned is None:
                return {"events": []}
            q = q.where(Event.job_id == job_id)
        rows = db.execute(q).scalars().all()
        return {"events": [{"ts": e.ts, "level": e.level, "event": e.event, "job_id": e.job_id, "data": json.loads(e.data_json)} for e in rows]}


@app.get("/v1/audit")
def recent_audit(limit: int = Query(100, le=1000), user=Depends(auth_audit)):
    tid = tenant_of(user)
    with session_scope() as db:
        from agency.models import AuditLog

        rows = db.execute(select(AuditLog).where(AuditLog.org_id == tid).order_by(AuditLog.ts.desc()).limit(limit)).scalars().all()
        return {
            "items": [
                {"ts": a.ts, "actor": a.actor, "action": a.action, "entity_type": a.entity_type, "entity_id": a.entity_id, "detail": json.loads(a.detail_json or "{}")}
                for a in rows
            ]
        }


@app.post("/v1/jobs/{job_id}/cancel")
def cancel_job(job_id: str, user=Depends(auth_write)):
    tid = tenant_of(user)
    with session_scope() as db:
        job = db.execute(select(Job).where(Job.id == job_id, Job.org_id == tid)).scalar_one_or_none()
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
        if approval is None or not _project_in_tenant(db, approval.project_id or "", tenant_of(user)):
            candidate = db.execute(
                select(Approval).where(Approval.job_id == approval_or_job, Approval.status == "requested").order_by(Approval.requested_at.desc())
            ).scalars().first()
            if candidate is None or not _project_in_tenant(db, candidate.project_id or "", tenant_of(user)):
                raise HTTPException(404, "no pending approval found")
            approval = candidate
        approval.status = body.decision
        approval.note = body.note
        approval.decided_at = now_iso()
        approval.decided_by = actor_name(user)
        job = db.get(Job, approval.job_id)
        if job is not None and job.state == "awaiting_approval":
            if body.decision == "approved":
                job.state = "queued"
                job.heartbeat_at = None
            else:
                job.state = "failed"
                job.error = f"rejected at approval gate: {body.note}"
                job.finished_at = now_iso()
                notify_webhooks(db, job.org_id, "job.failed", {"job_id": job.id, "reason": "approval_rejected"})
        db.commit()
        audit(db, actor_name(user), "approval.decided", "approval", approval.id, {"decision": body.decision}, org_id=tenant_of(user))
        return {"approval_id": approval.id, "status": approval.status, "job_state": job.state if job else None}


@app.post("/v1/webhooks")
def create_webhook(body: WebhookCreate, user=Depends(auth_admin)):
    from urllib.parse import urlparse

    try:
        assert_public_url(body.url)
    except ValueError as exc:
        raise HTTPException(422, f"webhook URL rejected: {exc}") from exc
    parsed = urlparse(body.url)
    if parsed.scheme != "https" and get_settings().env == "production":
        raise HTTPException(422, "webhook URLs must use https in production")
    invalid = [e for e in body.events if e not in WEBHOOK_EVENT_TYPES]
    if invalid:
        raise HTTPException(422, f"unknown event types: {invalid}; allowed: {WEBHOOK_EVENT_TYPES}")
    secret = "whsec_" + secrets.token_urlsafe(32)
    with session_scope() as db:
        hook = Webhook(org_id=tenant_of(user), url=str(body.url), secret=secret, events_json=json.dumps(body.events), created_by=actor_name(user))
        db.add(hook)
        db.commit()
        audit(db, actor_name(user), "webhook.created", "webhook", hook.id, {"url": str(body.url)}, org_id=tenant_of(user))
        return {"id": hook.id, "url": hook.url, "secret": secret, "events": body.events, "note": "store the secret now; it is required to verify signatures"}


@app.get("/v1/webhooks")
def list_webhooks(user=Depends(auth_admin)):
    with session_scope() as db:
        hooks = db.execute(select(Webhook).where(Webhook.org_id == tenant_of(user))).scalars().all()
        return {"items": [{"id": w.id, "url": w.url, "events": w.events, "active": bool(w.active)} for w in hooks]}


@app.delete("/v1/webhooks/{webhook_id}")
def delete_webhook(webhook_id: str, user=Depends(auth_admin)):
    with session_scope() as db:
        hook = db.execute(select(Webhook).where(Webhook.id == webhook_id, Webhook.org_id == tenant_of(user))).scalar_one_or_none()
        if hook is None:
            raise HTTPException(404, "webhook not found")
        hook.active = False
        db.commit()
        audit(db, actor_name(user), "webhook.deleted", "webhook", webhook_id, {}, org_id=tenant_of(user))
        return {"id": webhook_id, "deleted": True}


@app.post("/v1/webhooks/{webhook_id}/test")
def test_webhook(webhook_id: str, user=Depends(auth_admin)):
    with session_scope() as db:
        hook = db.execute(select(Webhook).where(Webhook.id == webhook_id, Webhook.org_id == tenant_of(user))).scalar_one_or_none()
        if hook is None:
            raise HTTPException(404, "webhook not found")
        delivery_ids = dispatch_event(db, tenant_of(user), "job.completed", {"test": True})
    stats = process_pending_deliveries_with_scope(tenant_of(user))
    return {"dispatched": len(delivery_ids), "delivery_stats": stats}


def process_pending_deliveries_with_scope(tenant: str) -> dict:
    from agency.db import session_scope as scope

    with scope() as db:
        return process_pending_deliveries(db)


@app.post("/v1/budgets")
def create_budget(body: BudgetCreate, user=Depends(auth_admin)):
    with session_scope() as db:
        budget = Budget(
            org_id=tenant_of(user),
            project_id=body.project_id,
            scope="project" if body.project_id else "tenant",
            max_cost_per_job_usd=body.max_cost_per_job_usd,
            daily_limit_usd=body.daily_limit_usd,
            monthly_limit_usd=body.monthly_limit_usd,
        )
        db.add(budget)
        db.commit()
        audit(db, actor_name(user), "budget.created", "budget", budget.id, {"scope": budget.scope}, org_id=tenant_of(user))
        return {"id": budget.id, "scope": budget.scope}


@app.get("/v1/metrics", response_class=PlainTextResponse)
def metrics(user=Depends(auth_read)):
    with session_scope() as db:
        queue_gauges = {}
        for state in ("queued", "running", "retrying", "awaiting_approval", "failed", "completed"):
            n = db.execute(select(func.count()).select_from(Job).where(Job.state == state)).scalar() or 0
            queue_gauges[f'agency_queue_depth{{state="{state}"}}'] = float(n)
    METRICS.set_gauge("agency_metrics_scrape_total", (METRICS.percentile("agency_api_request_latency_seconds", 50) or 0))
    body = METRICS.render_prometheus(queue_gauges)
    return Response(content=body, media_type="text/plain; version=0.0.4")


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
    return {
        "version": __version__,
        "providers": {
            **providers,
            "video_generation": {"healthy": False, "detail": "OPTIONAL / NOT CONFIGURED — reserved adapter point"},
        },
        "queue": counts,
        "registry_agents_active": len([a for a in get_registry() if a["status"] == "active"]),
    }


