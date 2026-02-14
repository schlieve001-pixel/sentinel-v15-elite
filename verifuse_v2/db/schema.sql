-- VERIFUSE V2 — Titanium Schema
-- Production foundation. PRAGMA foreign_keys = ON enforced at connection.
-- All timestamps are ISO8601 UTC. All money is REAL (USD).

-- ── Core leads table ───────────────────────────────────────────────
-- NOTE: "status" (RESTRICTED/ACTIONABLE/EXPIRED) is NEVER stored.
--       It is computed at runtime from sale_date + claim_deadline.
CREATE TABLE IF NOT EXISTS assets (
    asset_id            TEXT PRIMARY KEY,
    county              TEXT NOT NULL,
    state               TEXT NOT NULL DEFAULT 'CO',
    jurisdiction        TEXT NOT NULL,
    case_number         TEXT,
    asset_type          TEXT NOT NULL DEFAULT 'FORECLOSURE_SURPLUS',
    source_name         TEXT,
    statute_window      TEXT,
    days_remaining      INTEGER,
    owner_of_record     TEXT,
    property_address    TEXT,
    lien_type           TEXT,
    sale_date           TEXT,                        -- ISO8601 date of foreclosure sale
    claim_deadline      TEXT,                        -- ISO8601 computed: sale_date + statute window
    redemption_date     TEXT,
    recorder_link       TEXT,
    -- V2 financial columns (Titanium spec)
    winning_bid         REAL DEFAULT 0.0,            -- Bid price at foreclosure auction
    total_debt          REAL DEFAULT 0.0,            -- Total indebtedness / lien amount
    surplus_amount      REAL DEFAULT 0.0,            -- max(0, winning_bid - total_debt)
    estimated_surplus   REAL DEFAULT 0.0,            -- Legacy compat (= surplus_amount)
    total_indebtedness  REAL DEFAULT 0.0,            -- Legacy compat (= total_debt)
    overbid_amount      REAL DEFAULT 0.0,
    fee_cap             REAL,
    -- V2 scoring
    completeness_score  REAL DEFAULT 0.0,
    confidence_score    REAL DEFAULT 0.0,            -- 0.0-1.0 extraction confidence
    risk_score          REAL DEFAULT 0.0,
    data_grade          TEXT DEFAULT 'BRONZE',
    -- Provenance
    record_hash         TEXT,
    source_file_hash    TEXT,
    source_file         TEXT,
    vertex_processed    INTEGER DEFAULT 0,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

-- ── Legal status tracking ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS legal_status (
    asset_id        TEXT PRIMARY KEY REFERENCES assets(asset_id),
    record_class    TEXT NOT NULL DEFAULT 'PIPELINE',
    data_grade      TEXT NOT NULL DEFAULT 'BRONZE',
    days_remaining  INTEGER,
    statute_window  TEXT,
    work_status     TEXT,
    attorney_id     TEXT,
    last_evaluated_at TEXT,
    promoted_at     TEXT,
    closed_at       TEXT,
    close_reason    TEXT
);

-- ── Statute authority (jurisdiction rules) ───────────────────────
CREATE TABLE IF NOT EXISTS statute_authority (
    jurisdiction    TEXT NOT NULL,
    state           TEXT NOT NULL,
    county          TEXT NOT NULL,
    asset_type      TEXT NOT NULL,
    statute_years   INTEGER,
    triggering_event TEXT,
    statute_citation TEXT,
    fee_cap_pct     REAL,
    fee_cap_flat    REAL,
    requires_court  INTEGER DEFAULT 0,
    known_issues    TEXT,
    verified_date   TEXT,
    verified_by     TEXT,
    confidence      REAL DEFAULT 1.0,
    PRIMARY KEY (jurisdiction, asset_type)
);

-- ── Pipeline audit trail ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pipeline_events (
    event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id        TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    old_value       TEXT,
    new_value       TEXT,
    actor           TEXT DEFAULT 'system',
    reason          TEXT,
    metadata_json   TEXT,
    created_at      TEXT NOT NULL
);

-- ── Users (attorneys / subscribers) ──────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    user_id             TEXT PRIMARY KEY,
    email               TEXT UNIQUE NOT NULL,
    password_hash       TEXT NOT NULL,
    full_name           TEXT,
    firm_name           TEXT,
    bar_number          TEXT,
    bar_state           TEXT DEFAULT 'CO',
    -- Titanium: attorney verification gate
    attorney_status     TEXT NOT NULL DEFAULT 'NONE'
                        CHECK(attorney_status IN ('NONE','PENDING','VERIFIED','REJECTED')),
    attorney_verified_at TEXT,                       -- ISO8601 when verified
    -- Billing
    tier                TEXT NOT NULL DEFAULT 'recon',
    credits_remaining   INTEGER NOT NULL DEFAULT 0,
    credits_reset_at    TEXT,
    stripe_customer_id  TEXT,
    stripe_subscription_id TEXT,
    -- Access
    is_admin            INTEGER NOT NULL DEFAULT 0,
    is_active           INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL,
    last_login_at       TEXT
);

-- ── Titanium: Lead unlocks (atomic credit + audit) ──────────────
-- One row per (user, lead). Credit deducted atomically.
CREATE TABLE IF NOT EXISTS lead_unlocks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL REFERENCES users(user_id),
    lead_id         TEXT NOT NULL REFERENCES assets(asset_id),
    unlocked_at     TEXT NOT NULL,                   -- ISO8601 UTC
    ip_address      TEXT,
    plan_tier       TEXT,
    UNIQUE(user_id, lead_id)
);

-- ── Legacy unlocks table (kept for backward compat) ─────────────
CREATE TABLE IF NOT EXISTS unlocks (
    unlock_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL REFERENCES users(user_id),
    asset_id        TEXT NOT NULL REFERENCES assets(asset_id),
    unlock_type     TEXT NOT NULL DEFAULT 'full',
    disclaimer_accepted INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL
);

-- ── Subscription tiers reference ─────────────────────────────────
CREATE TABLE IF NOT EXISTS tiers (
    tier_id         TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    price_monthly   INTEGER NOT NULL,
    credits_per_month INTEGER NOT NULL,
    description     TEXT
);

INSERT OR IGNORE INTO tiers VALUES ('recon',     'Recon',     199,   5,  'Denver Metro, 5 unlocks/mo, 50 views/day');
INSERT OR IGNORE INTO tiers VALUES ('operator',  'Operator',  399,  25,  'All CO counties, 25 unlocks/mo, 200 views/day');
INSERT OR IGNORE INTO tiers VALUES ('sovereign', 'Sovereign', 699, 100,  '100 unlocks/mo, 500 views/day, priority data');

-- ── Scraper registry ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS scraper_registry (
    scraper_name    TEXT PRIMARY KEY,
    jurisdiction    TEXT,
    record_type     TEXT,
    fields_collected TEXT,
    known_gaps      TEXT,
    update_frequency_days INTEGER DEFAULT 7,
    legal_confidence REAL DEFAULT 0.7,
    last_run_at     TEXT,
    last_run_status TEXT,
    records_produced INTEGER DEFAULT 0,
    enabled         INTEGER DEFAULT 1,
    disabled_reason TEXT
);

-- ── Blacklist ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS blacklist (
    address_hash    TEXT PRIMARY KEY,
    reason          TEXT,
    added_at        TEXT,
    added_by        TEXT
);

-- ── Staging table ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS assets_staging (
    asset_id        TEXT PRIMARY KEY,
    county          TEXT,
    state           TEXT DEFAULT 'CO',
    case_number     TEXT,
    owner_of_record TEXT,
    property_address TEXT,
    sale_date       TEXT,
    estimated_surplus REAL DEFAULT 0.0,
    data_grade      TEXT DEFAULT 'BRONZE',
    source_name     TEXT,
    original_source TEXT,
    staged_at       TEXT,
    reason          TEXT,
    pdf_path        TEXT,
    status          TEXT DEFAULT 'STAGED',
    processed_at    TEXT,
    engine_version  TEXT
);

-- ── Indexes ──────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_assets_county ON assets(county);
CREATE INDEX IF NOT EXISTS idx_assets_grade ON assets(data_grade);
CREATE INDEX IF NOT EXISTS idx_assets_surplus ON assets(surplus_amount);
CREATE INDEX IF NOT EXISTS idx_assets_sale_date ON assets(sale_date);
CREATE INDEX IF NOT EXISTS idx_assets_claim_deadline ON assets(claim_deadline);
CREATE INDEX IF NOT EXISTS idx_legal_class ON legal_status(record_class);
CREATE INDEX IF NOT EXISTS idx_legal_grade ON legal_status(data_grade);
CREATE INDEX IF NOT EXISTS idx_events_asset ON pipeline_events(asset_id);
CREATE INDEX IF NOT EXISTS idx_unlocks_user ON unlocks(user_id);
CREATE INDEX IF NOT EXISTS idx_unlocks_asset ON unlocks(asset_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
-- Titanium: compound index for lead_unlocks (covers UNIQUE + lookups)
CREATE INDEX IF NOT EXISTS idx_lead_unlocks_user_lead ON lead_unlocks(user_id, lead_id);
CREATE INDEX IF NOT EXISTS idx_lead_unlocks_lead ON lead_unlocks(lead_id);
