-- VeriFuse vNEXT — Gate 6: Equity Resolution Schema
-- Migration: 005_equity_resolution.sql
-- Applied by: run_migrations.py Phase 12

-- 1. lien_records — junior lien snapshot from Lienor Redemption tab
CREATE TABLE IF NOT EXISTS lien_records (
  id               TEXT PRIMARY KEY,
  asset_id         TEXT NOT NULL,
  lien_type        TEXT NOT NULL CHECK(lien_type IN (
                     'IRS','HOA','MORTGAGE','JUDGMENT','OTHER')),
  lienholder_name  TEXT,
  priority         INTEGER,
  amount_cents     INTEGER NOT NULL DEFAULT 0,
  is_open          INTEGER NOT NULL DEFAULT 1,
  source           TEXT DEFAULT 'govsoft_html',
  retrieved_ts     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lien_records_asset ON lien_records(asset_id);

-- 2. equity_resolution — one row per asset; UNIQUE enforced
CREATE TABLE IF NOT EXISTS equity_resolution (
  id                       TEXT PRIMARY KEY,
  asset_id                 TEXT NOT NULL UNIQUE,
  gross_surplus_cents      INTEGER NOT NULL DEFAULT 0,
  junior_liens_total_cents INTEGER NOT NULL DEFAULT 0,
  net_owner_equity_cents   INTEGER NOT NULL DEFAULT 0,
  classification           TEXT NOT NULL CHECK(classification IN (
                             'LIEN_ABSORBED',
                             'OWNER_ELIGIBLE',
                             'TREASURER_TRANSFERRED',
                             'RESOLUTION_PENDING',
                             'NEEDS_REVIEW_TREASURER_WINDOW')),
  resolved_ts              INTEGER NOT NULL,
  notes                    TEXT
);
CREATE INDEX IF NOT EXISTS idx_equity_resolution_asset ON equity_resolution(asset_id);
