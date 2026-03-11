-- Migration 019: READY_TO_FILE state + verification columns + case_outcomes table
-- Applied automatically by run_migrations.py at startup (idempotent)

-- Add verification_state to leads (already exists as default 'RAW' — use ALTER OR IGNORE pattern)
-- Note: verification_state column may already exist from prior migrations; these are all safe no-ops if so

-- lien_search_performed: 1 if LIENOR_TAB scraped or lien_records populated
ALTER TABLE leads ADD COLUMN lien_search_performed INTEGER DEFAULT 0;

-- surplus_verified: 1 when pool_source confirmed as VOUCHER or LEDGER
ALTER TABLE leads ADD COLUMN surplus_verified INTEGER DEFAULT 0;

-- rtf_achieved_at: timestamp when lead first reached READY_TO_FILE state
ALTER TABLE leads ADD COLUMN rtf_achieved_at TEXT;

-- owner_contact_json: aggregated owner contact intel from assessor + skip-trace
ALTER TABLE leads ADD COLUMN owner_contact_json TEXT;

-- display_grade: API-layer downgrade indicator (never overwrites data_grade)
ALTER TABLE leads ADD COLUMN display_grade TEXT;

-- case_outcomes: attorney filing outcome tracking (the "Bloomberg Moat" dataset)
CREATE TABLE IF NOT EXISTS case_outcomes (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    case_id TEXT REFERENCES attorney_cases(id),
    attorney_id TEXT REFERENCES users(user_id),
    filing_date TEXT,
    hearing_date TEXT,
    result TEXT CHECK(result IN ('won','settled','dismissed','pending','withdrawn')),
    amount_recovered_cents INTEGER,
    time_to_recovery_days INTEGER,
    judge_name TEXT,
    county TEXT,
    notes TEXT,
    recorded_at TEXT DEFAULT (datetime('now')),
    recorded_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_case_outcomes_county ON case_outcomes(county);
CREATE INDEX IF NOT EXISTS idx_case_outcomes_result ON case_outcomes(result);
CREATE INDEX IF NOT EXISTS idx_case_outcomes_attorney ON case_outcomes(attorney_id);
