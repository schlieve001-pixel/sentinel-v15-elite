-- 009_surplus_math_audit.sql
CREATE TABLE IF NOT EXISTS surplus_math_audit (
    id                  TEXT    PRIMARY KEY,
    asset_id            TEXT    NOT NULL,
    snapshot_id         TEXT    REFERENCES html_snapshots(id),
    doc_id              TEXT    REFERENCES evidence_documents(id),
    html_overbid        INTEGER,
    successful_bid      INTEGER,
    total_indebtedness  INTEGER,
    computed_surplus    INTEGER,    -- successful_bid - total_indebtedness
    voucher_overbid     INTEGER,    -- NULL if no voucher doc
    voucher_doc_id      TEXT    REFERENCES evidence_documents(id),
    match_html_math     INTEGER,    -- 1 if html_overbid == computed (within 1 cent)
    match_voucher       INTEGER,    -- 1 if voucher matches; NULL if no voucher
    data_grade          TEXT    NOT NULL CHECK(data_grade IN ('GOLD','BRONZE')),
    promotion_blocked   INTEGER NOT NULL DEFAULT 0,
    audit_ts            INTEGER NOT NULL,
    notes               TEXT
);
CREATE INDEX IF NOT EXISTS idx_surplus_audit_asset ON surplus_math_audit(asset_id);
