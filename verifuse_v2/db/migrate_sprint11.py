"""
VERIFUSE V2 — Sprint 11 Migration Script
==========================================
Idempotent schema changes for Sprint 11.

All ALTER TABLE commands check PRAGMA table_info first.
All CREATE TABLE use IF NOT EXISTS.
All UPDATEs are safe to run multiple times.

Usage:
    export VERIFUSE_DB_PATH=/path/to/verifuse_v2.db
    python -m verifuse_v2.db.migrate_sprint11
"""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

DB_PATH = os.environ.get(
    "VERIFUSE_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data", "verifuse_v2.db"),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Get set of column names for a table."""
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {r[1] for r in rows}
    except Exception:
        return set()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
        [table],
    ).fetchone()
    return row[0] > 0


def _add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, typedef: str
) -> bool:
    """Add column if it doesn't exist. Returns True if added."""
    cols = _get_columns(conn, table)
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {typedef}")
        log.info("  Added column %s.%s (%s)", table, column, typedef)
        return True
    return False


def run_migration():
    """Execute all Sprint 11 migrations. Idempotent."""
    if not os.path.exists(DB_PATH):
        log.error("Database not found: %s", DB_PATH)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")

    log.info("=" * 60)
    log.info("  SPRINT 11 MIGRATION")
    log.info("  DB: %s", DB_PATH)
    log.info("  Time: %s", _now())
    log.info("=" * 60)

    # ── Task 0A: Null out fee_cap_pct (legal safety) ────────────────
    log.info("")
    log.info("Task 0A: Legal Safety — fee_cap_pct")

    leads_cols = _get_columns(conn, "leads")
    if "fee_cap_pct" in leads_cols:
        count = conn.execute(
            "SELECT COUNT(*) FROM leads WHERE fee_cap_pct IS NOT NULL"
        ).fetchone()[0]
        if count > 0:
            conn.execute("UPDATE leads SET fee_cap_pct = NULL WHERE fee_cap_pct IS NOT NULL")
            log.info("  Nulled %d rows with fee_cap_pct in leads", count)
        else:
            log.info("  fee_cap_pct already NULL in all leads rows")
    else:
        log.info("  fee_cap_pct column not found in leads — OK")

    # Also null in statute_authority
    sa_cols = _get_columns(conn, "statute_authority")
    if "fee_cap_pct" in sa_cols:
        count = conn.execute(
            "SELECT COUNT(*) FROM statute_authority WHERE fee_cap_pct IS NOT NULL"
        ).fetchone()[0]
        if count > 0:
            conn.execute("UPDATE statute_authority SET fee_cap_pct = NULL WHERE fee_cap_pct IS NOT NULL")
            log.info("  Nulled %d rows with fee_cap_pct in statute_authority", count)
        else:
            log.info("  fee_cap_pct already NULL in statute_authority")

    # Also null fee_cap in assets table
    assets_cols = _get_columns(conn, "assets")
    if "fee_cap" in assets_cols:
        count = conn.execute(
            "SELECT COUNT(*) FROM assets WHERE fee_cap IS NOT NULL"
        ).fetchone()[0]
        if count > 0:
            conn.execute("UPDATE assets SET fee_cap = NULL WHERE fee_cap IS NOT NULL")
            log.info("  Nulled %d rows with fee_cap in assets", count)

    conn.commit()

    # ── Task 0B: Recompute statute_window_status ────────────────────
    log.info("")
    log.info("Task 0B: Recompute statute_window_status")

    # Add statute_window_status to leads if missing
    _add_column_if_missing(conn, "leads", "statute_window_status", "TEXT")

    has_claim_deadline = "claim_deadline" in leads_cols or "claim_deadline" in _get_columns(conn, "leads")

    if has_claim_deadline:
        conn.execute("""
            UPDATE leads SET statute_window_status = CASE
                WHEN sale_date IS NULL OR TRIM(sale_date) = '' THEN 'UNKNOWN'
                WHEN claim_deadline IS NOT NULL AND TRIM(claim_deadline) != ''
                     AND date(claim_deadline) < date('now') THEN 'EXPIRED'
                WHEN date(sale_date, '+6 months') >= date('now') THEN 'DATA_ACCESS_ONLY'
                ELSE 'ESCROW_ENDED'
            END
        """)
        log.info("  Recomputed statute_window_status (with EXPIRED branch)")
    else:
        conn.execute("""
            UPDATE leads SET statute_window_status = CASE
                WHEN sale_date IS NULL OR TRIM(sale_date) = '' THEN 'UNKNOWN'
                WHEN date(sale_date, '+6 months') >= date('now') THEN 'DATA_ACCESS_ONLY'
                ELSE 'ESCROW_ENDED'
            END
        """)
        log.info("  Recomputed statute_window_status (no claim_deadline column)")

    # Report
    for status in ["DATA_ACCESS_ONLY", "ESCROW_ENDED", "EXPIRED", "UNKNOWN"]:
        try:
            cnt = conn.execute(
                "SELECT COUNT(*) FROM leads WHERE statute_window_status = ?", [status]
            ).fetchone()[0]
            if cnt > 0:
                log.info("    %s: %d", status, cnt)
        except Exception:
            pass

    conn.commit()

    # ── Task 0E: Vertex Budget Gate tables ──────────────────────────
    log.info("")
    log.info("Task 0E: Vertex Budget Gate tables")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS vertex_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            source_pdf_sha256 TEXT,
            cost_usd REAL DEFAULT 0.0,
            model_used TEXT,
            status TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    log.info("  vertex_usage table ready")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS vertex_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_pdf_path TEXT NOT NULL,
            source_pdf_sha256 TEXT,
            queued_at TEXT NOT NULL DEFAULT (datetime('now')),
            status TEXT DEFAULT 'PENDING'
        )
    """)
    log.info("  vertex_queue table ready")

    conn.commit()

    # ── Task 0F: Download Audit table ───────────────────────────────
    log.info("")
    log.info("Task 0F: Download Audit + Tenant Isolation")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS download_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            lead_id TEXT NOT NULL,
            doc_type TEXT NOT NULL,
            granted INTEGER NOT NULL DEFAULT 1,
            timestamp TEXT NOT NULL DEFAULT (datetime('now')),
            ip_address TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_download_audit_user_lead
        ON download_audit(user_id, lead_id, timestamp)
    """)
    log.info("  download_audit table + index ready")

    # Add verified_attorney columns to users
    _add_column_if_missing(conn, "users", "verified_attorney", "INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "users", "firm_address", "TEXT")
    _add_column_if_missing(conn, "users", "bar_verified_at", "TEXT")

    conn.commit()

    # ── Task 0G: Kill the Split-Brain — Merge assets → leads ───────
    log.info("")
    log.info("Task 0G: Merge assets → leads")

    # Add legacy_asset_id column
    _add_column_if_missing(conn, "leads", "legacy_asset_id", "TEXT")

    # Add attorney_packet_ready if missing
    _add_column_if_missing(conn, "leads", "attorney_packet_ready", "INTEGER DEFAULT 0")

    # Create index for merge speed
    conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_county_case ON leads(county, case_number)")

    # Check if assets table exists and has data
    if _table_exists(conn, "assets"):
        asset_count = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
        log.info("  assets table has %d rows", asset_count)

        if asset_count > 0:
            # Step 1: COALESCE into existing leads that match on normalized (county, case_number)
            conn.execute("""
                UPDATE leads SET
                    owner_name = COALESCE(leads.owner_name, (
                        SELECT a.owner_of_record FROM assets a
                        WHERE UPPER(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(a.county,'-',''),' ',''),'.',''),'/','')))
                            = UPPER(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(leads.county,'-',''),' ',''),'.',''),'/',''))
                        )
                        AND UPPER(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(a.case_number,'-',''),' ',''),'.',''),'/','')))
                            = UPPER(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(leads.case_number,'-',''),' ',''),'.',''),'/',''))
                        )
                        AND a.case_number IS NOT NULL
                        ORDER BY a.updated_at DESC, COALESCE(a.estimated_surplus, 0) DESC
                        LIMIT 1
                    )),
                    property_address = COALESCE(leads.property_address, (
                        SELECT a.property_address FROM assets a
                        WHERE UPPER(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(a.county,'-',''),' ',''),'.',''),'/','')))
                            = UPPER(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(leads.county,'-',''),' ',''),'.',''),'/',''))
                        )
                        AND UPPER(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(a.case_number,'-',''),' ',''),'.',''),'/','')))
                            = UPPER(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(leads.case_number,'-',''),' ',''),'.',''),'/',''))
                        )
                        AND a.case_number IS NOT NULL
                        ORDER BY a.updated_at DESC, COALESCE(a.estimated_surplus, 0) DESC
                        LIMIT 1
                    )),
                    estimated_surplus = CASE
                        WHEN leads.estimated_surplus = 0 OR leads.estimated_surplus IS NULL THEN (
                            SELECT COALESCE(a.estimated_surplus, 0) FROM assets a
                            WHERE UPPER(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(a.county,'-',''),' ',''),'.',''),'/','')))
                                = UPPER(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(leads.county,'-',''),' ',''),'.',''),'/',''))
                            )
                            AND UPPER(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(a.case_number,'-',''),' ',''),'.',''),'/','')))
                                = UPPER(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(leads.case_number,'-',''),' ',''),'.',''),'/',''))
                            )
                            AND a.case_number IS NOT NULL
                            ORDER BY a.updated_at DESC, COALESCE(a.estimated_surplus, 0) DESC
                            LIMIT 1
                        ) ELSE leads.estimated_surplus END,
                    total_debt = CASE
                        WHEN leads.total_debt = 0 OR leads.total_debt IS NULL THEN (
                            SELECT COALESCE(a.total_indebtedness, 0) FROM assets a
                            WHERE UPPER(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(a.county,'-',''),' ',''),'.',''),'/','')))
                                = UPPER(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(leads.county,'-',''),' ',''),'.',''),'/',''))
                            )
                            AND UPPER(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(a.case_number,'-',''),' ',''),'.',''),'/','')))
                                = UPPER(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(leads.case_number,'-',''),' ',''),'.',''),'/',''))
                            )
                            AND a.case_number IS NOT NULL
                            ORDER BY a.updated_at DESC, COALESCE(a.estimated_surplus, 0) DESC
                            LIMIT 1
                        ) ELSE leads.total_debt END,
                    sale_date = COALESCE(leads.sale_date, (
                        SELECT a.sale_date FROM assets a
                        WHERE UPPER(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(a.county,'-',''),' ',''),'.',''),'/','')))
                            = UPPER(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(leads.county,'-',''),' ',''),'.',''),'/',''))
                        )
                        AND UPPER(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(a.case_number,'-',''),' ',''),'.',''),'/','')))
                            = UPPER(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(leads.case_number,'-',''),' ',''),'.',''),'/',''))
                        )
                        AND a.case_number IS NOT NULL
                        ORDER BY a.updated_at DESC, COALESCE(a.estimated_surplus, 0) DESC
                        LIMIT 1
                    )),
                    legacy_asset_id = COALESCE(leads.legacy_asset_id, (
                        SELECT a.asset_id FROM assets a
                        WHERE UPPER(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(a.county,'-',''),' ',''),'.',''),'/','')))
                            = UPPER(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(leads.county,'-',''),' ',''),'.',''),'/',''))
                        )
                        AND UPPER(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(a.case_number,'-',''),' ',''),'.',''),'/','')))
                            = UPPER(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(leads.case_number,'-',''),' ',''),'.',''),'/',''))
                        )
                        AND a.case_number IS NOT NULL
                        ORDER BY a.updated_at DESC, COALESCE(a.estimated_surplus, 0) DESC
                        LIMIT 1
                    ))
                WHERE leads.case_number IS NOT NULL
            """)
            merged = conn.execute(
                "SELECT COUNT(*) FROM leads WHERE legacy_asset_id IS NOT NULL"
            ).fetchone()[0]
            log.info("  Step 1: %d leads enriched from assets", merged)

            # Step 2: INSERT unmatched assets as new leads
            conn.execute("""
                INSERT OR IGNORE INTO leads (
                    id, case_number, county, owner_name, property_address,
                    estimated_surplus, total_debt, overbid_amount, sale_date,
                    source_name, data_grade, confidence_score, updated_at, legacy_asset_id
                )
                SELECT
                    'asset:' || asset_id,
                    case_number, county, owner_of_record, property_address,
                    COALESCE(estimated_surplus, 0), COALESCE(total_indebtedness, 0),
                    COALESCE(overbid_amount, 0), sale_date, source_name,
                    COALESCE(data_grade, 'BRONZE'), COALESCE(confidence_score, 0),
                    COALESCE(updated_at, datetime('now')), asset_id
                FROM assets
                WHERE NOT EXISTS (
                    SELECT 1 FROM leads l
                    WHERE UPPER(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(l.county,'-',''),' ',''),'.',''),'/','')))
                        = UPPER(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(assets.county,'-',''),' ',''),'.',''),'/',''))
                    )
                    AND UPPER(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(l.case_number,'-',''),' ',''),'.',''),'/','')))
                        = UPPER(TRIM(REPLACE(REPLACE(REPLACE(REPLACE(assets.case_number,'-',''),' ',''),'.',''),'/',''))
                    )
                    AND assets.case_number IS NOT NULL
                )
            """)
            new_count = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
            log.info("  Step 2: leads table now has %d rows", new_count)

    conn.commit()

    # ── Task 0J: Lead Provenance Table ──────────────────────────────
    log.info("")
    log.info("Task 0J: Lead Provenance table")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS lead_provenance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id TEXT NOT NULL,
            source_pdf_path TEXT,
            source_pdf_sha256 TEXT,
            parser_used TEXT,
            retrieved_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (lead_id) REFERENCES leads(id)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_lead_provenance_lead
        ON lead_provenance(lead_id)
    """)
    log.info("  lead_provenance table + index ready")

    conn.commit()

    # ── Log migration event ─────────────────────────────────────────
    try:
        conn.execute("""
            INSERT INTO pipeline_events
            (asset_id, event_type, old_value, new_value, actor, reason, created_at)
            VALUES ('SYSTEM', 'MIGRATION', 'sprint-10', 'sprint-11', 'migrate_sprint11.py',
                    'Phase -1 critical corrections', ?)
        """, [_now()])
        conn.commit()
    except Exception as e:
        log.warning("Could not log migration event: %s", e)

    # ── Summary ─────────────────────────────────────────────────────
    log.info("")
    log.info("=" * 60)
    log.info("  SPRINT 11 MIGRATION COMPLETE")
    log.info("=" * 60)

    # Lead counts by grade
    try:
        rows = conn.execute("""
            SELECT data_grade, COUNT(*) as cnt,
                   COALESCE(SUM(estimated_surplus), 0) as total
            FROM leads
            GROUP BY data_grade
            ORDER BY total DESC
        """).fetchall()
        for r in rows:
            log.info("  %s: %d leads ($%,.0f)", r[0] or "UNGRADED", r[1], r[2])
    except Exception:
        pass

    total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    log.info("  Total leads: %d", total)
    log.info("=" * 60)

    conn.close()
    return True


if __name__ == "__main__":
    run_migration()
