-- Migration 016: Auth Security — Account lockout + password reset
-- Applied idempotently via run_migrations.py evolve_users() or api.py startup.

-- Account lockout columns
ALTER TABLE users ADD COLUMN failed_login_count INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN locked_until TEXT;

-- Password reset columns
ALTER TABLE users ADD COLUMN password_reset_token TEXT;
ALTER TABLE users ADD COLUMN password_reset_sent_at TEXT;
