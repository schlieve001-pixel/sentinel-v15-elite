-- Migration 018: Ops Jobs — admin-triggered pipeline jobs with live output
-- Applied idempotently by run_migrations.py

CREATE TABLE IF NOT EXISTS ops_jobs (
    id          TEXT PRIMARY KEY,
    command     TEXT NOT NULL,              -- e.g. 'pending-sales', 'gate4-run-all'
    args_json   TEXT,                       -- JSON array of extra args
    status      TEXT NOT NULL DEFAULT 'QUEUED',  -- QUEUED|RUNNING|SUCCESS|FAILED|CANCELLED
    triggered_by TEXT,                      -- user email
    triggered_at INTEGER NOT NULL,
    started_at  INTEGER,
    finished_at INTEGER,
    output      TEXT,                       -- last 64KB of stdout+stderr
    exit_code   INTEGER,
    county      TEXT                        -- optional county filter
);

CREATE INDEX IF NOT EXISTS idx_ops_jobs_status   ON ops_jobs(status);
CREATE INDEX IF NOT EXISTS idx_ops_jobs_triggered ON ops_jobs(triggered_at DESC);

-- Pre-sale monitoring: track which counties have been scanned and when
CREATE TABLE IF NOT EXISTS presale_scan_log (
    id           TEXT PRIMARY KEY,
    county       TEXT NOT NULL,
    scan_ts      INTEGER NOT NULL,
    cases_found  INTEGER NOT NULL DEFAULT 0,
    cases_inserted INTEGER NOT NULL DEFAULT 0,
    cases_skipped  INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'SUCCESS',
    notes        TEXT
);

CREATE INDEX IF NOT EXISTS idx_presale_scan_county ON presale_scan_log(county, scan_ts DESC);
