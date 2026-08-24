from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import DeclarativeBase


def uid() -> str:
    return uuid.uuid4().hex


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class Base(DeclarativeBase):
    pass


import json  # noqa: E402

from sqlalchemy import Boolean, Float, Integer, Text  # noqa: E402
from sqlalchemy.orm import Mapped, mapped_column  # noqa: E402


class Org(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uid)
    name: Mapped[str]
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str]
    status: Mapped[str] = mapped_column(Text, default="active")
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)

    @property
    def settings(self) -> dict:
        return {}


class Webhook(Base):
    __tablename__ = "webhooks"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(Text, index=True)
    url: Mapped[str]
    secret: Mapped[str] = mapped_column(Text)
    events_json: Mapped[str] = mapped_column(Text, default="[]")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def events(self) -> list:
        return json.loads(self.events_json or "[]")

    @events.setter
    def events(self, value: list) -> None:
        self.events_json = json.dumps(value)


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uid)
    webhook_id: Mapped[str] = mapped_column(Text, index=True)
    event_type: Mapped[str]
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(Text, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    next_retry_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)
    delivered_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class Budget(Base):
    __tablename__ = "budgets"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uid)
    org_id: Mapped[str | None] = mapped_column(Text, index=True, nullable=True)
    project_id: Mapped[str | None] = mapped_column(Text, index=True, nullable=True)
    scope: Mapped[str] = mapped_column(Text, default="tenant")
    max_cost_per_job_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    daily_limit_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    monthly_limit_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(Text, index=True)
    email: Mapped[str] = mapped_column(Text, unique=True)
    role: Mapped[str] = mapped_column(Text, default="viewer")
    api_key_hash: Mapped[str] = mapped_column(Text, index=True)
    api_key_expires_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_key_revoked_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    must_rotate_key: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uid)
    org_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str]
    status: Mapped[str] = mapped_column(Text, default="created")
    brief_json: Mapped[str] = mapped_column(Text, default="{}")
    spec_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)
    updated_at: Mapped[str] = mapped_column(Text, default=now_iso)

    @property
    def brief(self) -> dict:
        return json.loads(self.brief_json or "{}")

    @brief.setter
    def brief(self, value: dict) -> None:
        self.brief_json = json.dumps(value)

    @property
    def spec(self) -> dict:
        return json.loads(self.spec_json or "{}")

    @spec.setter
    def spec(self, value: dict) -> None:
        self.spec_json = json.dumps(value)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(Text, index=True)
    org_id: Mapped[str | None] = mapped_column(Text, index=True, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    type: Mapped[str] = mapped_column(Text, default="production")
    state: Mapped[str] = mapped_column(Text, default="queued", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=5)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    repair_count: Mapped[int] = mapped_column(Integer, default=0)
    heartbeat_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)
    started_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    finished_at: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def payload(self) -> dict:
        return json.loads(self.payload_json or "{}")

    @payload.setter
    def payload(self, value: dict) -> None:
        self.payload_json = json.dumps(value)

    @property
    def result(self) -> dict | None:
        return json.loads(self.result_json) if self.result_json else None

    @result.setter
    def result(self, value: dict | None) -> None:
        self.result_json = json.dumps(value) if value is not None else None


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(Text, index=True)
    name: Mapped[str]
    agent: Mapped[str]
    seq: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(Text, default="pending")
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    input_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_class: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    finished_at: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def output(self) -> dict:
        return json.loads(self.output_json) if self.output_json else {}

    @output.setter
    def output(self, value: dict) -> None:
        self.output_json = json.dumps(value)


class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uid)
    org_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_id: Mapped[str | None] = mapped_column(Text, index=True, nullable=True)
    kind: Mapped[str]
    source_uri: Mapped[str]
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    license_state: Mapped[str] = mapped_column(Text, default="unknown")
    license_json: Mapped[str] = mapped_column(Text, default="{}")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)

    @property
    def tags(self) -> list:
        return json.loads(self.tags_json or "[]")

    @tags.setter
    def tags(self, value: list) -> None:
        self.tags_json = json.dumps(value)

    @property
    def license(self) -> dict:
        return json.loads(self.license_json or "{}")

    @license.setter
    def license(self, value: dict) -> None:
        self.license_json = json.dumps(value)

    @property
    def meta(self) -> dict:
        return json.loads(self.metadata_json or "{}")

    @meta.setter
    def meta(self, value: dict) -> None:
        self.metadata_json = json.dumps(value)


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uid)
    project_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_id: Mapped[str | None] = mapped_column(Text, index=True, nullable=True)
    task_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str]
    storage_key: Mapped[str]
    sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    provenance_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)

    @property
    def meta(self) -> dict:
        return json.loads(self.metadata_json or "{}")

    @meta.setter
    def meta(self, value: dict) -> None:
        self.metadata_json = json.dumps(value)

    @property
    def provenance(self) -> dict:
        return json.loads(self.provenance_json or "{}")

    @provenance.setter
    def provenance(self, value: dict) -> None:
        self.provenance_json = json.dumps(value)


class ScriptVersion(Base):
    __tablename__ = "scripts"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(Text, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    content_json: Mapped[str] = mapped_column(Text, default="{}")
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    qa_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)


class Storyboard(Base):
    __tablename__ = "storyboards"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(Text, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    scenes_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)


class Timeline(Base):
    __tablename__ = "timelines"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(Text, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    edl_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)


class QAReport(Base):
    __tablename__ = "qa_reports"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uid)
    project_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_id: Mapped[str | None] = mapped_column(Text, index=True, nullable=True)
    task_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    layer: Mapped[str]
    passed: Mapped[bool]
    score: Mapped[float] = mapped_column(Float, default=0.0)
    findings_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)

    @property
    def findings(self) -> list:
        return json.loads(self.findings_json or "[]")

    @findings.setter
    def findings(self, value: list) -> None:
        self.findings_json = json.dumps(value)


class Repair(Base):
    __tablename__ = "repairs"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(Text, index=True)
    failure_class: Mapped[str]
    stage: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan_json: Mapped[str] = mapped_column(Text, default="{}")
    applied: Mapped[bool] = mapped_column(Boolean, default=False)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uid)
    project_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_id: Mapped[str | None] = mapped_column(Text, index=True, nullable=True)
    kind: Mapped[str]
    status: Mapped[str] = mapped_column(Text, default="requested")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[str] = mapped_column(Text, default=now_iso)
    decided_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(Text, nullable=True)


class Deliverable(Base):
    __tablename__ = "deliverables"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(Text, index=True)
    job_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    platform: Mapped[str]
    storage_key: Mapped[str]
    manifest_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)

    @property
    def manifest(self) -> dict:
        return json.loads(self.manifest_json or "{}")

    @manifest.setter
    def manifest(self, value: dict) -> None:
        self.manifest_json = json.dumps(value)


class CostEntry(Base):
    __tablename__ = "costs"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uid)
    project_id: Mapped[str | None] = mapped_column(Text, index=True, nullable=True)
    org_id: Mapped[str | None] = mapped_column(Text, index=True, nullable=True)
    job_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str]
    provider: Mapped[str]
    model: Mapped[str] = mapped_column(Text, default="")
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    unit: Mapped[str] = mapped_column(Text, default="")
    amount_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uid)
    ts: Mapped[str] = mapped_column(Text, default=now_iso)
    actor: Mapped[str] = mapped_column(Text, default="system")
    action: Mapped[str]
    entity_type: Mapped[str]
    entity_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    org_id: Mapped[str | None] = mapped_column(Text, index=True, nullable=True)
    detail_json: Mapped[str] = mapped_column(Text, default="{}")


class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uid)
    ts: Mapped[str] = mapped_column(Text, default=now_iso)
    job_id: Mapped[str | None] = mapped_column(Text, index=True, nullable=True)
    task_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    org_id: Mapped[str | None] = mapped_column(Text, index=True, nullable=True)
    level: Mapped[str] = mapped_column(Text, default="info")
    event: Mapped[str]
    data_json: Mapped[str] = mapped_column(Text, default="{}")

