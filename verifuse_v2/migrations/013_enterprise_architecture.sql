-- Migration 013: Enterprise Architecture
-- Phases 1-7, 11, 17 schema changes
-- Run via: python3 -m verifuse_v2.migrations.run_migrations

PRAGMA foreign_keys = ON;

-- ─── Phase 1: Canonical Calculations Table ────────────────────────────────────
CREATE TABLE IF NOT EXISTS calculations (
    id                      TEXT    PRIMARY KEY,
    lead_id                 TEXT    NOT NULL REFERENCES leads(id),
    calc_hash               TEXT    NOT NULL,
    pool_source             TEXT    NOT NULL DEFAULT 'UNVERIFIED'
                                    CHECK(pool_source IN ('VOUCHER','LEDGER','HTML_MATH','UNVERIFIED')),
    winning_bid_cents       INTEGER,
    total_due_cents         INTEGER,
    trustee_fees_cents      INTEGER,
    foreclosure_costs_cents INTEGER,
    voucher_overbid_cents   INTEGER,
    voucher_doc_id          TEXT,
    junior_liens_json       TEXT,
    candidate_pool_cents    INTEGER NOT NULL DEFAULT 0,
    verified_net_cents      INTEGER,    -- NULL when trustee_fees missing
    confidence_score        REAL    NOT NULL DEFAULT 0.0,
    confidence_reasons_json TEXT,
    missing_inputs_json     TEXT,
    display_tier            TEXT    NOT NULL DEFAULT 'POTENTIAL'
                                    CHECK(display_tier IN ('POTENTIAL','VERIFIED')),
    triggered_by            TEXT,
    created_ts              INTEGER NOT NULL DEFAULT (unixepoch())
);
CREATE INDEX IF NOT EXISTS idx_calculations_lead
    ON calculations(lead_id, created_ts DESC);

-- ─── Phase 11: Admin Override Log ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS admin_override_log (
    id              TEXT    PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    admin_user_id   TEXT    NOT NULL,
    target_lead_id  TEXT    REFERENCES leads(id),
    target_user_id  TEXT    REFERENCES users(user_id),
    action          TEXT    NOT NULL,
    reason_code     TEXT    NOT NULL,
    old_value       TEXT,
    new_value       TEXT,
    created_ts      INTEGER NOT NULL DEFAULT (unixepoch())
);
CREATE INDEX IF NOT EXISTS idx_override_admin
    ON admin_override_log(admin_user_id, created_ts DESC);
CREATE INDEX IF NOT EXISTS idx_override_lead
    ON admin_override_log(target_lead_id);

-- ─── EPIC 8: Email Log (cooldown + daily cap tracking) ────────────────────────
CREATE TABLE IF NOT EXISTS email_log (
    id          TEXT    PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    email_hash  TEXT    NOT NULL,   -- sha256(lower(email)) — never store plaintext
    mode        TEXT,               -- sendgrid | smtp | ses | log
    sent_ts     INTEGER NOT NULL DEFAULT (unixepoch())
);
CREATE INDEX IF NOT EXISTS idx_email_log_hash_ts
    ON email_log(email_hash, sent_ts DESC);

-- ─── Phase 4: Verification State + Calc Link on leads ─────────────────────────
-- Note: ALTER TABLE in SQLite cannot add CHECK constraints to existing columns.
-- The verification_state DEFAULT and CHECK are enforced at application layer.
-- Columns added idempotently by Python runner via PRAGMA table_info guard.
-- SQL here documents intended schema; Python runner applies safely.

-- leads.verification_state  TEXT DEFAULT 'RAW'
--     CHECK IN ('RAW','EXTRACTED','EVIDENCE_ATTACHED','MATH_VERIFIED','ATTORNEY_READY','PUBLISHED')
-- leads.calc_hash            TEXT
-- leads.current_calc_id      TEXT REFERENCES calculations(id)
-- leads.last_verified_ts     INTEGER
-- leads.verified_by          TEXT
-- leads.pool_source          TEXT DEFAULT 'UNVERIFIED'
--     CHECK IN ('VOUCHER','LEDGER','HTML_MATH','UNVERIFIED')

-- ─── Phase 3: lien_records Table Swap ─────────────────────────────────────────
-- Expand lien_type CHECK to include HELOC, MECHANIC, TAX.
-- Add: recording_number, recording_date, document_id.
-- Row count verified by Python runner before DROP.
-- SQL below executed by Python runner after asserting row counts match.

-- Python runner executes:
--   1. CREATE TABLE lien_records_new (...)
--   2. INSERT INTO lien_records_new SELECT ... FROM lien_records
--   3. assert COUNT(lien_records_new) == COUNT(lien_records)
--   4. DROP TABLE lien_records
--   5. ALTER TABLE lien_records_new RENAME TO lien_records
--   6. CREATE INDEX

-- ─── Phase 2: evidence_documents Extension ────────────────────────────────────
-- Applied via Python PRAGMA table_info guard in run_migrations.py (idempotent).
-- Columns: recording_number, recording_date, verification_status, verified_by, verified_ts
