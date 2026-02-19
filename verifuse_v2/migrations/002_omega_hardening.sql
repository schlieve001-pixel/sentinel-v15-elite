-- 002_omega_hardening.sql
-- Omega v4.7 schema additions: wallet, transactions, rate limits, founders, audit
-- Applied by run_migrations.py (idempotent — all CREATE IF NOT EXISTS)

PRAGMA foreign_keys = ON;

-- ── Wallet (dual-credit ledger) ─────────────────────────────────
CREATE TABLE IF NOT EXISTS wallet (
    user_id TEXT PRIMARY KEY,
    subscription_credits INTEGER NOT NULL DEFAULT 0 CHECK(subscription_credits >= 0),
    purchased_credits INTEGER NOT NULL DEFAULT 0 CHECK(purchased_credits >= 0),
    tier TEXT NOT NULL DEFAULT 'scout',
    updated_at TEXT
);

-- ── Transactions (immutable ledger) ─────────────────────────────
CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    type TEXT NOT NULL,
    amount INTEGER NOT NULL DEFAULT 0,
    credits INTEGER NOT NULL DEFAULT 0,
    balance_after INTEGER,
    idempotency_key TEXT UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Stripe event dedup ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS stripe_events (
    event_id TEXT UNIQUE NOT NULL,
    type TEXT,
    received_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Founders cap ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS founders_redemptions (
    user_id TEXT PRIMARY KEY,
    redeemed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Daily lead view limits ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_daily_lead_views (
    user_id TEXT NOT NULL,
    day TEXT NOT NULL,
    lead_id TEXT NOT NULL,
    PRIMARY KEY (user_id, day, lead_id)
);

-- ── Email verification (code-based) ────────────────────────────
CREATE TABLE IF NOT EXISTS email_verifications (
    user_id TEXT PRIMARY KEY,
    code_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    resend_after TEXT,
    attempts INTEGER NOT NULL DEFAULT 0
);

-- ── Rate limits (epoch-second timestamps) ───────────────────────
CREATE TABLE IF NOT EXISTS rate_limits (
    key TEXT NOT NULL,
    ts INTEGER NOT NULL
);

-- ── Audit log ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    action TEXT NOT NULL,
    meta_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    ip TEXT
);

-- ── Subscriptions (local Stripe mirror) ─────────────────────────
CREATE TABLE IF NOT EXISTS subscriptions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    stripe_subscription_id TEXT,
    stripe_customer_id TEXT,
    tier TEXT NOT NULL DEFAULT 'scout',
    status TEXT NOT NULL DEFAULT 'active',
    current_period_start TEXT,
    current_period_end TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT
);

-- ── Indices ─────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_rate_limits_key_ts ON rate_limits(key, ts);
CREATE INDEX IF NOT EXISTS idx_udlv_user_day ON user_daily_lead_views(user_id, day);
CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_log_user ON audit_log(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id);

-- Dedupe index on lead_unlocks (prevent double-unlock rows)
CREATE UNIQUE INDEX IF NOT EXISTS idx_lead_unlocks_dedupe ON lead_unlocks(user_id, lead_id);
