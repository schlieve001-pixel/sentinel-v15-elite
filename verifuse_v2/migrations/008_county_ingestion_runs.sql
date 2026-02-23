-- 008_county_ingestion_runs.sql
CREATE TABLE IF NOT EXISTS county_ingestion_runs (
    run_id        TEXT    PRIMARY KEY,
    county        TEXT    NOT NULL,
    window_from   TEXT    NOT NULL,   -- ISO date YYYY-MM-DD
    window_to     TEXT    NOT NULL,   -- ISO date YYYY-MM-DD
    browser_count INTEGER,            -- NULL if count undetectable
    db_count      INTEGER NOT NULL DEFAULT 0,
    delta         INTEGER,            -- NULL if browser_count NULL
    status        TEXT    NOT NULL
                  CHECK(status IN (
                      'PASS','FAIL','OVERFLOW',
                      'NEEDS_MANUAL_REVIEW_OVERFLOW','ERROR'))
                  DEFAULT 'FAIL',
    errors        TEXT,
    run_ts        INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_county_ingestion_county
  ON county_ingestion_runs(county, window_from, window_to);
