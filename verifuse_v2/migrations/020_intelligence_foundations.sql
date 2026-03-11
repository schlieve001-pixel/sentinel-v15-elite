-- Migration 020: Intelligence Foundations
-- Adds legal_timers, lead state machine, source trace, verification history, platform_settings
-- All CREATE TABLE uses IF NOT EXISTS — safe to re-run

-- ── Legal Timers ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS legal_timers (
    id TEXT PRIMARY KEY,
    lead_id TEXT NOT NULL REFERENCES leads(id),
    asset_id TEXT,
    county TEXT,
    sale_date TEXT,
    restriction_end TEXT,
    treasurer_transfer TEXT,
    claim_deadline TEXT,
    monitor_status TEXT DEFAULT 'ACTIVE'
        CHECK(monitor_status IN ('ACTIVE','EXPIRED','CLAIMED','TRANSFERRED','CLOSED')),
    last_checked TEXT,
    alert_sent INTEGER DEFAULT 0,
    days_remaining INTEGER,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_legal_timers_lead ON legal_timers(lead_id);
CREATE INDEX IF NOT EXISTS idx_legal_timers_deadline ON legal_timers(claim_deadline);
CREATE INDEX IF NOT EXISTS idx_legal_timers_status ON legal_timers(monitor_status);

-- ── Lead State Machine ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS lead_state_machine (
    id TEXT PRIMARY KEY,
    lead_id TEXT NOT NULL REFERENCES leads(id),
    from_state TEXT,
    to_state TEXT NOT NULL,
    triggered_by TEXT,
    actor_id TEXT,
    reason TEXT,
    transitioned_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_lsm_lead ON lead_state_machine(lead_id);

-- ── Lead Events Log ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS lead_events_log (
    id TEXT PRIMARY KEY,
    lead_id TEXT NOT NULL REFERENCES leads(id),
    event_type TEXT NOT NULL,
    actor_id TEXT,
    detail_json TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_lel_lead ON lead_events_log(lead_id);
CREATE INDEX IF NOT EXISTS idx_lel_type ON lead_events_log(event_type);

-- ── Lead Source Trace ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS lead_source_trace (
    id TEXT PRIMARY KEY,
    lead_id TEXT NOT NULL REFERENCES leads(id),
    scraper_version TEXT,
    scrape_timestamp TEXT,
    source_url TEXT,
    document_capture_hash TEXT,
    adapter_name TEXT,
    schema_version TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_lst_lead ON lead_source_trace(lead_id);

-- ── Verification History ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS verification_history (
    id TEXT PRIMARY KEY,
    lead_id TEXT NOT NULL REFERENCES leads(id),
    verification_state TEXT,
    data_grade TEXT,
    confidence_score REAL,
    pool_source TEXT,
    calc_hash TEXT,
    verified_by TEXT,
    verified_at TEXT DEFAULT (datetime('now')),
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_vh_lead ON verification_history(lead_id);

-- ── Platform Settings ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS platform_settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT DEFAULT (datetime('now')),
    updated_by TEXT
);
INSERT OR IGNORE INTO platform_settings(key, value) VALUES
    ('founding_attorney_slots_claimed', '0'),
    ('founding_attorney_slots_total', '10'),
    ('founding_credits_on_signup', '5');

-- ── Extend unlock_spend_journal ───────────────────────────────────────────────
-- Add action, lead_id, user_id columns (safe: ALTER TABLE if column not present)
-- These may fail if columns already exist — that is expected and safe to ignore

-- ── Extend audit_log ─────────────────────────────────────────────────────────
-- entity_type, entity_id, old_value_json, new_value_json
