-- VeriFuse vNEXT Phase 10 — Ingestion Evidence Schema
-- Migration 004: County Profiles, Observability, Evidence Tables
-- All statements use CREATE/CREATE INDEX IF NOT EXISTS for idempotency.

-- ── County Profiles ───────────────────────────────────────────────
-- One row per county. Platform config for Playwright engine.
-- base_url sourced from env vars only — never hardcoded.

CREATE TABLE IF NOT EXISTS county_profiles (
    county                TEXT    NOT NULL PRIMARY KEY,
    platform_type         TEXT    NOT NULL CHECK(platform_type IN ('govsoft','custom','unknown')),
    captcha_mode          TEXT    NOT NULL CHECK(captcha_mode IN ('none','entry','detail'))
                                  DEFAULT 'none',
    requires_accept_terms INTEGER NOT NULL DEFAULT 0,
    base_url              TEXT    NOT NULL,
    search_path           TEXT    NOT NULL,
    detail_path           TEXT    NOT NULL,
    selectors_json        TEXT,           -- per-county selector overrides (JSON)
    last_verified_ts      INTEGER
);

-- ── Ingestion Runs ────────────────────────────────────────────────
-- Observability: one row per scraper run.
-- FAILED_STALE set on startup cleanup of zombie RUNNING rows (age > 2h).

CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id           TEXT    NOT NULL PRIMARY KEY,
    county           TEXT    NOT NULL,
    start_ts         INTEGER NOT NULL,
    end_ts           INTEGER,
    status           TEXT    NOT NULL CHECK(status IN (
                         'RUNNING','SUCCESS','FAILED','PARTIAL','FAILED_STALE'
                     )) DEFAULT 'RUNNING',
    cases_processed  INTEGER NOT NULL DEFAULT 0,
    cases_failed     INTEGER NOT NULL DEFAULT 0,
    notes            TEXT
);

CREATE INDEX IF NOT EXISTS idx_ingestion_runs_county
    ON ingestion_runs (county, start_ts);

-- ── HTML Snapshots ────────────────────────────────────────────────
-- Raw gzipped HTML per (asset, snapshot_type, content hash).
-- UNIQUE prevents duplicate captures of the same page state.

CREATE TABLE IF NOT EXISTS html_snapshots (
    id             TEXT    NOT NULL PRIMARY KEY,
    asset_id       TEXT    NOT NULL,
    snapshot_type  TEXT    NOT NULL CHECK(snapshot_type IN (
                       'SEARCH_RESULTS','CASE_DETAIL','SALE_INFO','LIENOR_TAB','DOCS_TAB'
                   )),
    raw_html_gzip  BLOB    NOT NULL,
    html_sha256    TEXT    NOT NULL,
    retrieved_ts   INTEGER NOT NULL,
    user_agent     TEXT,
    UNIQUE (asset_id, snapshot_type, html_sha256)
);

CREATE INDEX IF NOT EXISTS idx_html_snapshots_asset
    ON html_snapshots (asset_id);

-- ── Evidence Documents ────────────────────────────────────────────
-- One row per downloaded document (PDF, TIFF, etc.).
-- filename = raw GovSoft filename (stored as-is).
-- doc_type = free text; no CHECK — raw string from GovSoft.
-- doc_family = normalised CHECK enum derived from filename heuristic.
-- content_type = MIME type derived from file extension.
-- UNIQUE prevents double-ingest of same doc on same asset.

CREATE TABLE IF NOT EXISTS evidence_documents (
    id             TEXT    NOT NULL PRIMARY KEY,
    asset_id       TEXT    NOT NULL,
    filename       TEXT    NOT NULL,
    doc_type       TEXT    NOT NULL,
    doc_family     TEXT    NOT NULL CHECK(doc_family IN (
                       'BID','COP','NED','PTD','OB','NOTICE','INVOICE','OTHER'
                   )),
    file_path      TEXT    NOT NULL,
    file_sha256    TEXT    NOT NULL,
    bytes          INTEGER NOT NULL,
    content_type   TEXT    NOT NULL DEFAULT 'application/pdf',
    retrieved_ts   INTEGER NOT NULL,
    UNIQUE (asset_id, doc_family, file_sha256)
);

CREATE INDEX IF NOT EXISTS idx_evidence_docs_asset
    ON evidence_documents (asset_id);

-- ── Extraction Events ─────────────────────────────────────────────
-- One row per extraction attempt per asset.
-- Mirrors processing_status on asset_registry.

CREATE TABLE IF NOT EXISTS extraction_events (
    id              TEXT    NOT NULL PRIMARY KEY,
    asset_id        TEXT    NOT NULL,
    engine_version  TEXT,
    run_ts          INTEGER,
    status          TEXT    NOT NULL CHECK(status IN (
                        'PENDING','EXTRACTED','VALIDATED','NEEDS_REVIEW','CAPTCHA_BLOCKED'
                    )),
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_extraction_events_asset
    ON extraction_events (asset_id);

-- ── Field Evidence ────────────────────────────────────────────────
-- OCR bounding boxes per field per document.
-- Normalised coordinates (0.0–1.0) relative to page dimensions.

CREATE TABLE IF NOT EXISTS field_evidence (
    id               TEXT    NOT NULL PRIMARY KEY,
    evidence_doc_id  TEXT    NOT NULL REFERENCES evidence_documents(id),
    field_name       TEXT    NOT NULL,
    extracted_value  TEXT,
    confidence       REAL,
    norm_x1          REAL,
    norm_y1          REAL,
    norm_x2          REAL,
    norm_y2          REAL,
    page_number      INTEGER,
    ocr_source       TEXT    NOT NULL CHECK(ocr_source IN ('pdfplumber','document_ai')),
    created_ts       INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_field_evidence_doc
    ON field_evidence (evidence_doc_id);
