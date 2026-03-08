-- Migration 017: Mega-Refactor — RBAC, Attorney Workflow, Lead Enrichment
-- Applied idempotently via _apply_auto_migrations() in run_migrations.py
-- CREATE TABLE IF NOT EXISTS statements only — ALTER TABLE done in Python evolve_017()

PRAGMA foreign_keys = ON;

-- ─── Attorney Case Pipeline ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS attorney_cases (
    id              TEXT    PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    asset_id        TEXT    NOT NULL REFERENCES leads(id),
    user_id         INTEGER NOT NULL REFERENCES users(user_id),
    stage           TEXT    NOT NULL DEFAULT 'LEADS'
                            CHECK(stage IN ('LEADS','CONTACTED','RETAINER_SIGNED','FILED','FUNDS_RELEASED')),
    outcome_type    TEXT    CHECK(outcome_type IN ('claim_approved','claim_denied','settled','no_response')),
    outcome_notes   TEXT,
    outcome_funds_cents INTEGER,
    notes           TEXT,
    created_at      TEXT    DEFAULT (datetime('now')),
    updated_at      TEXT    DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_attorney_cases_asset   ON attorney_cases(asset_id);
CREATE INDEX IF NOT EXISTS idx_attorney_cases_user    ON attorney_cases(user_id);

-- ─── Attorney Territory Locking ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS attorney_territories (
    id              INTEGER PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(user_id),
    territory_type  TEXT    NOT NULL CHECK(territory_type IN ('county','zip','jurisdiction')),
    territory_value TEXT    NOT NULL,
    locked_at       TEXT    DEFAULT (datetime('now')),
    expires_at      TEXT,
    UNIQUE(territory_type, territory_value, user_id)
);

CREATE INDEX IF NOT EXISTS idx_territories_user      ON attorney_territories(user_id);
CREATE INDEX IF NOT EXISTS idx_territories_type_val  ON attorney_territories(territory_type, territory_value);
