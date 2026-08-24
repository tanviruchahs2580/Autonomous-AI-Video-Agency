DROP INDEX IF EXISTS ix_budgets_org;
DROP INDEX IF EXISTS ix_deliveries_status;
DROP INDEX IF EXISTS ix_deliveries_webhook;
DROP INDEX IF EXISTS ix_webhooks_org;
DROP TABLE IF EXISTS budgets;
DROP TABLE IF EXISTS webhook_deliveries;
DROP TABLE IF EXISTS webhooks;
ALTER TABLE users DROP COLUMN must_rotate_key;
