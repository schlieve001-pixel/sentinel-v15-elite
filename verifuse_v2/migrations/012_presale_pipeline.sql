-- Migration 012: Pre-Sale Pipeline
-- ============================================================
-- Adds pre-sale foreclosure columns to leads table.
-- Pre-sale leads are cases where the trustee's sale has NOT yet occurred —
-- typically captured from GovSoft "Active" status or NED bulletins.
--
-- Pre-sale flow:
--   NED Filed → 110-125 days → Scheduled Sale → Overbid captured → GOLD/SILVER
--
-- Surplus estimation for pre-sale cases:
--   pre_sale_estimated_surplus = max(0, estimated_appraised_value - opening_bid)
--   Where opening_bid = total debt at time of foreclosure (from NED/CASE_DETAIL)
--   And estimated_appraised_value = county assessor value (from assessor_lookup)
--
-- C.R.S. § 38-38-101 et seq.: Public Trustee foreclosure procedure

-- Pre-sale financial fields
ALTER TABLE leads ADD COLUMN opening_bid REAL DEFAULT 0.0;
ALTER TABLE leads ADD COLUMN estimated_appraised_value REAL DEFAULT 0.0;
ALTER TABLE leads ADD COLUMN pre_sale_estimated_surplus REAL DEFAULT 0.0;
ALTER TABLE leads ADD COLUMN ned_recorded_date TEXT;       -- Date NED was filed with clerk
ALTER TABLE leads ADD COLUMN scheduled_sale_date TEXT;     -- GovSoft scheduled sale date (future)
ALTER TABLE leads ADD COLUMN lender_name TEXT;             -- Foreclosing lender from NED
ALTER TABLE leads ADD COLUMN ned_source TEXT;              -- 'govsoft_active' | 'weld_ned_pdf' | 'manual'

-- Index for fast pre-sale lead queries
CREATE INDEX IF NOT EXISTS idx_leads_presale
    ON leads(processing_status, scheduled_sale_date)
    WHERE processing_status = 'PRE_SALE';

-- Index for leads missing SALE_INFO backfill (Jefferson remediation)
CREATE INDEX IF NOT EXISTS idx_leads_bronze_no_sale_date
    ON leads(county, data_grade, sale_date)
    WHERE data_grade = 'BRONZE' AND (sale_date IS NULL OR sale_date = '');
