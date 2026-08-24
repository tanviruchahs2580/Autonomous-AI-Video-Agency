-- 001_initial_schema (dialect-neutral: timestamps supplied by ORM layer)
CREATE TABLE IF NOT EXISTS organizations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT
);

INSERT INTO tenants (id, name, status) SELECT 'default', 'Default Tenant', 'active'
WHERE NOT EXISTS (SELECT 1 FROM tenants WHERE id = 'default');

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL DEFAULT 'viewer',
    api_key_hash TEXT NOT NULL,
    api_key_expires_at TEXT,
    api_key_revoked_at TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_users_org ON users(org_id);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    org_id TEXT,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'created',
    brief_json TEXT NOT NULL DEFAULT '{}',
    spec_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_projects_org ON projects(org_id);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    org_id TEXT,
    idempotency_key TEXT UNIQUE,
    type TEXT NOT NULL DEFAULT 'production',
    state TEXT NOT NULL DEFAULT 'queued',
    priority INTEGER NOT NULL DEFAULT 5,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    payload_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT,
    error TEXT,
    repair_count INTEGER NOT NULL DEFAULT 0,
    heartbeat_at TEXT,
    created_at TEXT,
    started_at TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_jobs_state ON jobs(state);
CREATE INDEX IF NOT EXISTS ix_jobs_project ON jobs(project_id);
CREATE INDEX IF NOT EXISTS ix_jobs_org ON jobs(org_id);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    name TEXT NOT NULL,
    agent TEXT NOT NULL,
    seq INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'pending',
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    input_json TEXT,
    output_json TEXT,
    error TEXT,
    failure_class TEXT,
    duration_ms INTEGER,
    started_at TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_tasks_job ON tasks(job_id);

CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    org_id TEXT,
    project_id TEXT,
    kind TEXT NOT NULL,
    source_uri TEXT NOT NULL,
    storage_key TEXT,
    sha256 TEXT,
    bytes INTEGER,
    license_state TEXT NOT NULL DEFAULT 'unknown',
    license_json TEXT NOT NULL DEFAULT '{}',
    tags_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_assets_project ON assets(project_id);
CREATE INDEX IF NOT EXISTS ix_assets_org ON assets(org_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_assets_project_sha ON assets(project_id, sha256) WHERE sha256 IS NOT NULL;

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    job_id TEXT,
    task_id TEXT,
    kind TEXT NOT NULL,
    storage_key TEXT NOT NULL,
    sha256 TEXT,
    bytes INTEGER,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    provenance_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_artifacts_job ON artifacts(job_id);
CREATE INDEX IF NOT EXISTS ix_artifacts_project ON artifacts(project_id);

CREATE TABLE IF NOT EXISTS scripts (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    content_json TEXT NOT NULL,
    approved INTEGER NOT NULL DEFAULT 0,
    qa_json TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS storyboards (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    scenes_json TEXT NOT NULL,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS timelines (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    edl_json TEXT NOT NULL,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS qa_reports (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    job_id TEXT,
    task_id TEXT,
    layer TEXT NOT NULL,
    passed INTEGER NOT NULL,
    score REAL NOT NULL DEFAULT 0,
    findings_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS repairs (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    failure_class TEXT NOT NULL,
    stage TEXT,
    plan_json TEXT NOT NULL DEFAULT '{}',
    applied INTEGER NOT NULL DEFAULT 0,
    result TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    job_id TEXT,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'requested',
    note TEXT,
    requested_at TEXT,
    decided_at TEXT,
    decided_by TEXT
);

CREATE TABLE IF NOT EXISTS deliverables (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    job_id TEXT,
    platform TEXT NOT NULL,
    storage_key TEXT NOT NULL,
    manifest_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_deliverables_project ON deliverables(project_id);

CREATE TABLE IF NOT EXISTS costs (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    org_id TEXT,
    job_id TEXT,
    task_id TEXT,
    category TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    quantity REAL NOT NULL DEFAULT 0,
    unit TEXT NOT NULL DEFAULT '',
    amount_usd REAL NOT NULL DEFAULT 0,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_costs_project ON costs(project_id);
CREATE INDEX IF NOT EXISTS ix_costs_org ON costs(org_id);

CREATE TABLE IF NOT EXISTS audit_logs (
    id TEXT PRIMARY KEY,
    ts TEXT,
    actor TEXT NOT NULL DEFAULT 'system',
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    org_id TEXT,
    detail_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_audit_org ON audit_logs(org_id);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    ts TEXT,
    job_id TEXT,
    task_id TEXT,
    org_id TEXT,
    level TEXT NOT NULL DEFAULT 'info',
    event TEXT NOT NULL,
    data_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_events_job ON events(job_id);
CREATE INDEX IF NOT EXISTS ix_events_org ON events(org_id);
