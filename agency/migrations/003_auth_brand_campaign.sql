-- 003_auth_brand_campaign_approval
CREATE TABLE IF NOT EXISTS clients (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    name TEXT NOT NULL,
    contact_email TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_clients_org ON clients(org_id);

CREATE TABLE IF NOT EXISTS brand_kits (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    client_id TEXT,
    name TEXT NOT NULL,
    palette_json TEXT NOT NULL DEFAULT '[]',
    font_name TEXT DEFAULT 'Arial',
    logo_key TEXT,
    intro_template TEXT,
    outro_template TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_brandkits_org ON brand_kits(org_id);

CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    client_id TEXT,
    name TEXT NOT NULL,
    objective TEXT DEFAULT '',
    start_date TEXT,
    end_date TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_campaigns_org ON campaigns(org_id);
CREATE INDEX IF NOT EXISTS ix_campaigns_client ON campaigns(client_id);

ALTER TABLE projects ADD COLUMN campaign_id TEXT;
ALTER TABLE projects ADD COLUMN brand_kit_id TEXT;
ALTER TABLE projects ADD COLUMN client_id TEXT;

CREATE TABLE IF NOT EXISTS deliverable_reviews (
    id TEXT PRIMARY KEY,
    deliverable_id TEXT NOT NULL REFERENCES deliverables(id),
    reviewer TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('submit_review','approve','request_changes','comment')),
    comment TEXT DEFAULT '',
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_reviews_deliverable ON deliverable_reviews(deliverable_id);

CREATE TABLE IF NOT EXISTS script_revisions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    version INTEGER NOT NULL,
    sections_json TEXT NOT NULL,
    full_text TEXT NOT NULL,
    edited_by TEXT NOT NULL,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_scriptrev_project ON script_revisions(project_id);
