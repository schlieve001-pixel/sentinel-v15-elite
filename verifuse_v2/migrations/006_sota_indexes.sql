-- 006_sota_indexes.sql

-- Index 1: Unlock ledger — user lookup
CREATE INDEX IF NOT EXISTS idx_unlock_ledger_user
  ON unlock_ledger_entries(user_id);

-- Index 2: Leads — county + grade (primary dashboard filter)
CREATE INDEX IF NOT EXISTS idx_leads_county_grade
  ON leads(county, data_grade);

-- Index 3: Leads — grade + surplus sort (preview sorted query)
CREATE INDEX IF NOT EXISTS idx_leads_grade_surplus
  ON leads(data_grade, estimated_surplus DESC, sale_date DESC);

-- Index 4: Daily views — user+day lookup
-- Column confirmed: day (NOT view_date)
CREATE INDEX IF NOT EXISTS idx_user_daily_views_day
  ON user_daily_lead_views(user_id, day);

-- Index 5: Daily views — UNIQUE deduplication
-- dedupe probe runs in run_migrations.py BEFORE this file is applied
CREATE UNIQUE INDEX IF NOT EXISTS uniq_user_day_lead
  ON user_daily_lead_views(user_id, day, lead_id);

-- Index 6: Leads — composite UNIQUE
-- run_migrations.py checks PRAGMA index_list(leads) before applying;
-- skips this if idx_leads_county_case (same columns) already exists as UNIQUE
CREATE UNIQUE INDEX IF NOT EXISTS uniq_leads_county_case
  ON leads(county, case_number);
