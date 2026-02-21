-- VeriFuse vNEXT Phase 0 — Foundation Schema
-- Migration 003: Ledger, Registry, RBAC, Tax Assets
-- All statements use CREATE/CREATE INDEX IF NOT EXISTS for idempotency.

-- ── FIFO Unlock Ledger ───────────────────────────────────────────────
-- One row per credit grant (subscription cycle, starter pack, migration).
-- qty_remaining is decremented atomically during unlock.
-- expires_ts = NULL means credits never expire (subscription).
-- stripe_event_id UNIQUE prevents duplicate grants on webhook replay.

CREATE TABLE IF NOT EXISTS unlock_ledger_entries (
    id              TEXT    NOT NULL PRIMARY KEY,
    user_id         TEXT    NOT NULL,
    source          TEXT    NOT NULL,           -- 'subscription' | 'starter' | 'migration' | 'admin'
    qty_total       INTEGER NOT NULL CHECK (qty_total > 0),
    qty_remaining   INTEGER NOT NULL CHECK (qty_remaining >= 0),
    purchased_ts    INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
    expires_ts      INTEGER,                    -- epoch; NULL = never expires
    stripe_event_id TEXT    UNIQUE,             -- idempotency key
    tier_at_purchase TEXT,
    created_at      INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
    CHECK (qty_remaining <= qty_total),
    CHECK (source != 'starter' OR expires_ts IS NOT NULL)
);

-- FIFO order: expires soonest first (NULLs last via (expires_ts IS NULL) ASC),
-- then oldest purchase within same expiry bucket.
CREATE INDEX IF NOT EXISTS idx_ledger_user_fifo
    ON unlock_ledger_entries (user_id, (expires_ts IS NULL), expires_ts, purchased_ts);

-- ── Asset Registry ───────────────────────────────────────────────────
-- Cross-engine financial index. One row per unique asset across all engines.
-- Allows future tax/lien/other asset types alongside FORECLOSURE.

CREATE TABLE IF NOT EXISTS asset_registry (
    asset_id        TEXT    NOT NULL PRIMARY KEY,
    engine_type     TEXT    NOT NULL DEFAULT 'FORECLOSURE',
    source_table    TEXT    NOT NULL DEFAULT 'leads',
    source_id       TEXT    NOT NULL,
    county          TEXT,
    state           TEXT    DEFAULT 'CO',
    amount_cents    INTEGER,                    -- surplus/value in cents
    event_ts        INTEGER,                    -- sale date as epoch (UTC)
    created_at      INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_asset_registry_engine
    ON asset_registry (engine_type, county);

-- ── Asset Unlocks ────────────────────────────────────────────────────
-- One row per (user, asset) unlock. UNIQUE prevents double-spend.
-- INSERT OR IGNORE pattern: if rowcount==0 the asset is already unlocked.

CREATE TABLE IF NOT EXISTS asset_unlocks (
    id              TEXT    NOT NULL PRIMARY KEY,
    user_id         TEXT    NOT NULL,
    asset_id        TEXT    NOT NULL,
    credits_spent   INTEGER NOT NULL DEFAULT 1,
    unlocked_at     INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
    ip_address      TEXT,
    tier_at_unlock  TEXT,
    UNIQUE (user_id, asset_id)
);

CREATE INDEX IF NOT EXISTS idx_asset_unlocks_user
    ON asset_unlocks (user_id, asset_id);

-- ── Unlock Spend Journal ─────────────────────────────────────────────
-- Dispute-proof audit: one row per ledger entry touched per unlock.
-- Allows full reconstruction of which credits were consumed and when.

CREATE TABLE IF NOT EXISTS unlock_spend_journal (
    id                  TEXT    NOT NULL PRIMARY KEY,
    unlock_id           TEXT    NOT NULL,
    ledger_entry_id     TEXT    NOT NULL,
    credits_consumed    INTEGER NOT NULL,
    created_at          INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_spend_journal_unlock
    ON unlock_spend_journal (unlock_id);

-- ── Tax Assets ───────────────────────────────────────────────────────
-- Future: tax lien / tax deed asset type.
-- row_hash UNIQUE enables CSV import idempotency.

CREATE TABLE IF NOT EXISTS tax_assets (
    id               TEXT    NOT NULL PRIMARY KEY,
    county           TEXT    NOT NULL,
    parcel_number    TEXT,
    owner_name       TEXT,
    property_address TEXT,
    tax_year         INTEGER,
    amount_due       REAL,
    sale_date        TEXT,
    data_grade       TEXT    DEFAULT 'BRONZE',
    status           TEXT    DEFAULT 'STAGED',
    row_hash         TEXT    UNIQUE,
    created_at       INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
    updated_at       INTEGER
);

CREATE INDEX IF NOT EXISTS idx_tax_assets_county
    ON tax_assets (county, sale_date);
