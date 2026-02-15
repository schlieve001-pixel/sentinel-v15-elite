"""
VERIFUSE V2 — Data Quarantine Engine

Quarantines ghost leads (zero-value Vertex artifacts) and demotes Jefferson
false-GOLD leads that lack verified financial data.

Safety: WAL checkpoint before any mutation. All actions logged to pipeline_events.

Usage:
    export VERIFUSE_DB_PATH=/path/to/verifuse_v2.db
    python -m verifuse_v2.db.quarantine
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timezone

DB_PATH = os.environ.get("VERIFUSE_DB_PATH")
if not DB_PATH:
    print("FATAL: VERIFUSE_DB_PATH environment variable is not set.")
    print("  export VERIFUSE_DB_PATH=/home/schlieve001/origin/continuity_lab/verifuse_v2/data/verifuse_v2.db")
    sys.exit(1)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=OFF")  # OFF during migration
    return conn


def run_quarantine() -> dict:
    """Execute the full quarantine pipeline. Returns a summary report."""
    report = {
        "db_path": DB_PATH,
        "ghosts_quarantined": 0,
        "jefferson_demoted": 0,
        "errors": [],
    }

    conn = _get_conn()
    try:
        # ── Step 1: WAL checkpoint ───────────────────────────────────
        print("[1/5] WAL checkpoint...")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        print("  WAL checkpoint complete")

        # ── Step 2: Create leads_quarantine table ────────────────────
        print("[2/5] Creating leads_quarantine table (if not exists)...")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS leads_quarantine (
                id                TEXT PRIMARY KEY,
                case_number       TEXT,
                county            TEXT,
                owner_name        TEXT,
                property_address  TEXT,
                estimated_surplus REAL DEFAULT 0.0,
                record_hash       TEXT,
                winning_bid       REAL DEFAULT 0.0,
                total_debt        REAL DEFAULT 0.0,
                surplus_amount    REAL DEFAULT 0.0,
                overbid_amount    REAL DEFAULT 0.0,
                confidence_score  REAL DEFAULT 0.0,
                status            TEXT DEFAULT 'STAGED',
                sale_date         TEXT,
                claim_deadline    TEXT,
                data_grade        TEXT DEFAULT 'BRONZE',
                source_name       TEXT,
                vertex_processed  INTEGER DEFAULT 0,
                updated_at        TEXT,
                source_link       TEXT,
                evidence_file     TEXT,
                pdf_filename      TEXT,
                vertex_processed_at TEXT,
                extraction_notes  TEXT,
                quarantine_reason TEXT,
                quarantined_at    TEXT
            )
        """)
        print("  leads_quarantine table ready")

        # ── Step 3: Quarantine ghost leads ───────────────────────────
        print("[3/5] Quarantining ghost leads (zero-value Vertex artifacts)...")

        # Get columns that exist in leads table
        leads_cols = {r[1] for r in conn.execute("PRAGMA table_info(leads)").fetchall()}
        # Build column list for INSERT (only columns that exist in leads)
        quarantine_only = {"quarantine_reason", "quarantined_at"}
        all_q_cols = {r[1] for r in conn.execute("PRAGMA table_info(leads_quarantine)").fetchall()}
        shared_cols = sorted(leads_cols & (all_q_cols - quarantine_only))
        col_list = ", ".join(shared_cols)

        now = _now_iso()

        # Count ghost leads first
        ghost_count = conn.execute("""
            SELECT COUNT(*) FROM leads
            WHERE confidence_score <= 0.15
              AND (surplus_amount = 0 OR surplus_amount IS NULL)
              AND source_name LIKE '%post%sale%continuance%'
        """).fetchone()[0]

        if ghost_count > 0:
            conn.execute(f"""
                INSERT OR IGNORE INTO leads_quarantine ({col_list}, quarantine_reason, quarantined_at)
                SELECT {col_list}, 'VERTEX_GHOST_ZERO_VALUE', ?
                FROM leads
                WHERE confidence_score <= 0.15
                  AND (surplus_amount = 0 OR surplus_amount IS NULL)
                  AND source_name LIKE '%post%sale%continuance%'
            """, [now])

            conn.execute("""
                DELETE FROM leads
                WHERE confidence_score <= 0.15
                  AND (surplus_amount = 0 OR surplus_amount IS NULL)
                  AND source_name LIKE '%post%sale%continuance%'
            """)
            report["ghosts_quarantined"] = ghost_count
            print(f"  {ghost_count} ghost leads quarantined")
        else:
            print("  No ghost leads found matching criteria")

        # ── Step 4: Demote Jefferson false-GOLDs ─────────────────────
        print("[4/5] Demoting Jefferson false-GOLD leads...")
        jefferson_count = conn.execute("""
            UPDATE leads
            SET data_grade = 'PIPELINE_STAGING'
            WHERE county = 'Jefferson'
              AND data_grade = 'GOLD'
              AND (winning_bid IS NULL OR winning_bid = 0)
              AND surplus_amount = 0
        """).rowcount
        report["jefferson_demoted"] = jefferson_count
        if jefferson_count > 0:
            print(f"  {jefferson_count} Jefferson false-GOLDs demoted to PIPELINE_STAGING")
        else:
            print("  No Jefferson false-GOLDs found")

        # ── Step 5: Log to pipeline_events ───────────────────────────
        print("[5/5] Logging quarantine events...")
        if report["ghosts_quarantined"] > 0:
            conn.execute("""
                INSERT INTO pipeline_events
                (asset_id, event_type, old_value, new_value, actor, reason, created_at)
                VALUES ('SYSTEM', 'QUARANTINE_GHOSTS', ?, ?, 'quarantine.py', 'Ghost leads with zero value and low confidence', ?)
            """, [
                f"{report['ghosts_quarantined']} leads in leads table",
                f"{report['ghosts_quarantined']} moved to leads_quarantine",
                now,
            ])

        if report["jefferson_demoted"] > 0:
            conn.execute("""
                INSERT INTO pipeline_events
                (asset_id, event_type, old_value, new_value, actor, reason, created_at)
                VALUES ('SYSTEM', 'DEMOTE_JEFFERSON', ?, ?, 'quarantine.py', 'Jefferson false-GOLDs without winning_bid', ?)
            """, [
                f"{report['jefferson_demoted']} GOLD leads",
                f"{report['jefferson_demoted']} demoted to PIPELINE_STAGING",
                now,
            ])

        conn.commit()

        # ── Summary ──────────────────────────────────────────────────
        total_quarantined = conn.execute(
            "SELECT COUNT(*) FROM leads_quarantine"
        ).fetchone()[0]
        remaining_leads = conn.execute(
            "SELECT COUNT(*) FROM leads"
        ).fetchone()[0]
        jeff_gold = conn.execute(
            "SELECT COUNT(*) FROM leads WHERE county='Jefferson' AND data_grade='GOLD'"
        ).fetchone()[0]

        print(f"\n{'='*60}")
        print(f"  QUARANTINE COMPLETE")
        print(f"  Ghosts quarantined:     {report['ghosts_quarantined']}")
        print(f"  Jefferson demoted:      {report['jefferson_demoted']}")
        print(f"  Total in quarantine:    {total_quarantined}")
        print(f"  Remaining leads:        {remaining_leads}")
        print(f"  Jefferson GOLDs left:   {jeff_gold}")
        print(f"{'='*60}\n")

    except Exception as e:
        report["errors"].append(str(e))
        print(f"\n  [FATAL] {e}")
        raise
    finally:
        conn.close()

    return report


if __name__ == "__main__":
    result = run_quarantine()
    if result["errors"]:
        sys.exit(1)
