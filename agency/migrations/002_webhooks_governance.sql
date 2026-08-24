-- 002_webhooks_and_governance
CREATE TABLE IF NOT EXISTS webhooks (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    url TEXT NOT NULL,
    secret TEXT NOT NULL,
    events_json TEXT NOT NULL DEFAULT '[]',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT,
    created_by TEXT
);
CREATE INDEX IF NOT EXISTS ix_webhooks_org ON webhooks(org_id);

CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id TEXT PRIMARY KEY,
    webhook_id TEXT NOT NULL REFERENCES webhooks(id),
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    next_retry_at TEXT,
    response_code INTEGER,
    last_error TEXT,
    created_at TEXT,
    delivered_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_deliveries_webhook ON webhook_deliveries(webhook_id);
CREATE INDEX IF NOT EXISTS ix_deliveries_status ON webhook_deliveries(status);

CREATE TABLE IF NOT EXISTS budgets (
    id TEXT PRIMARY KEY,
    org_id TEXT,
    project_id TEXT,
    scope TEXT NOT NULL DEFAULT 'tenant',
    max_cost_per_job_usd REAL,
    daily_limit_usd REAL,
    monthly_limit_usd REAL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_budgets_org ON budgets(org_id);

ALTER TABLE users ADD COLUMN must_rotate_key INTEGER NOT NULL DEFAULT 0;
