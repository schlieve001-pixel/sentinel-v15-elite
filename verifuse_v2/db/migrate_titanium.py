"""
VERIFUSE V2 — Titanium Migration

Safe, idempotent schema migration. Adds columns/tables/indexes
without mutating existing data or lead status.

Usage:
    python -m verifuse_v2.db.migrate_titanium
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from verifuse_v2.db.database import get_db, DB_PATH

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)


def _get_columns(conn, table: str) -> set[str]:
    """Get column names for a table."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


def _get_tables(conn) -> set[str]:
    """Get all table names."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {r[0] for r in rows}


def _add_column(conn, table: str, col: str, typedef: str, report: dict) -> None:
    """Add a column if it doesn't exist."""
    existing = _get_columns(conn, table)
    if col not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
        report["columns_added"].append(f"{table}.{col}")
        log.info("  + Added column %s.%s", table, col)
    else:
        report["columns_skipped"].append(f"{table}.{col}")


def _create_index(conn, name: str, ddl: str, report: dict) -> None:
    """Create an index if it doesn't exist."""
    existing = {r[1] for r in conn.execute("PRAGMA index_list('lead_unlocks')").fetchall()}
    conn.execute(ddl)
    report["indexes_created"].append(name)


def migrate() -> dict:
    """Run the Titanium migration. Returns a structured report."""
    report = {
        "tables_created": [],
        "columns_added": [],
        "columns_skipped": [],
        "indexes_created": [],
        "data_backfills": [],
        "errors": [],
    }

    log.info("=" * 60)
    log.info("  TITANIUM MIGRATION")
    log.info("  Database: %s", DB_PATH)
    log.info("=" * 60)

    try:
        with get_db() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            tables = _get_tables(conn)

            # ── 1. Create lead_unlocks table ─────────────────────────
            if "lead_unlocks" not in tables:
                conn.execute("""
                    CREATE TABLE lead_unlocks (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id     TEXT NOT NULL REFERENCES users(user_id),
                        lead_id     TEXT NOT NULL REFERENCES assets(asset_id),
                        unlocked_at TEXT NOT NULL,
                        ip_address  TEXT,
                        plan_tier   TEXT,
                        UNIQUE(user_id, lead_id)
                    )
                """)
                report["tables_created"].append("lead_unlocks")
                log.info("  + Created table: lead_unlocks")
            else:
                log.info("  = Table lead_unlocks already exists")

            # ── 2. Add Titanium columns to assets ────────────────────
            if "assets" in tables:
                _add_column(conn, "assets", "winning_bid", "REAL DEFAULT 0.0", report)
                _add_column(conn, "assets", "total_debt", "REAL DEFAULT 0.0", report)
                _add_column(conn, "assets", "surplus_amount", "REAL DEFAULT 0.0", report)
                _add_column(conn, "assets", "claim_deadline", "TEXT", report)
                _add_column(conn, "assets", "vertex_processed", "INTEGER DEFAULT 0", report)

            # ── 3. Add attorney_status to users ──────────────────────
            if "users" in tables:
                _add_column(conn, "users", "attorney_status", "TEXT DEFAULT 'NONE'", report)
                _add_column(conn, "users", "attorney_verified_at", "TEXT", report)

            # ── 4. Add columns to assets_staging ─────────────────────
            if "assets_staging" in tables:
                _add_column(conn, "assets_staging", "pdf_path", "TEXT", report)
                _add_column(conn, "assets_staging", "status", "TEXT DEFAULT 'STAGED'", report)
                _add_column(conn, "assets_staging", "processed_at", "TEXT", report)
                _add_column(conn, "assets_staging", "engine_version", "TEXT", report)

            # ── 5. Create indexes ────────────────────────────────────
            idx_defs = [
                ("idx_lead_unlocks_user_lead", "CREATE INDEX IF NOT EXISTS idx_lead_unlocks_user_lead ON lead_unlocks(user_id, lead_id)"),
                ("idx_lead_unlocks_lead", "CREATE INDEX IF NOT EXISTS idx_lead_unlocks_lead ON lead_unlocks(lead_id)"),
                ("idx_assets_sale_date", "CREATE INDEX IF NOT EXISTS idx_assets_sale_date ON assets(sale_date)"),
                ("idx_assets_claim_deadline", "CREATE INDEX IF NOT EXISTS idx_assets_claim_deadline ON assets(claim_deadline)"),
                ("idx_assets_surplus", "CREATE INDEX IF NOT EXISTS idx_assets_surplus ON assets(surplus_amount)"),
            ]
            for name, ddl in idx_defs:
                try:
                    conn.execute(ddl)
                    report["indexes_created"].append(name)
                    log.info("  + Index: %s", name)
                except Exception:
                    pass  # Already exists

            # ── 6. Backfill claim_deadline from sale_date ────────────
            # C.R.S. § 38-38-111: 180-day window
            backfilled = conn.execute("""
                UPDATE assets
                SET claim_deadline = date(sale_date, '+180 days')
                WHERE sale_date IS NOT NULL
                  AND sale_date != ''
                  AND (claim_deadline IS NULL OR claim_deadline = '')
            """).rowcount
            if backfilled > 0:
                report["data_backfills"].append(f"claim_deadline: {backfilled} rows")
                log.info("  + Backfilled claim_deadline for %d assets", backfilled)

            # ── 7. Backfill surplus_amount = estimated_surplus ───────
            synced = conn.execute("""
                UPDATE assets
                SET surplus_amount = estimated_surplus
                WHERE surplus_amount = 0.0
                  AND estimated_surplus > 0.0
            """).rowcount
            if synced > 0:
                report["data_backfills"].append(f"surplus_amount sync: {synced} rows")
                log.info("  + Synced surplus_amount for %d assets", synced)

            # ── 8. Backfill total_debt = total_indebtedness ──────────
            synced2 = conn.execute("""
                UPDATE assets
                SET total_debt = total_indebtedness
                WHERE total_debt = 0.0
                  AND total_indebtedness > 0.0
            """).rowcount
            if synced2 > 0:
                report["data_backfills"].append(f"total_debt sync: {synced2} rows")
                log.info("  + Synced total_debt for %d assets", synced2)

            # ── 9. Migrate existing unlocks → lead_unlocks ───────────
            if "unlocks" in tables and "lead_unlocks" in (tables | set(report["tables_created"])):
                migrated = conn.execute("""
                    INSERT OR IGNORE INTO lead_unlocks (user_id, lead_id, unlocked_at, plan_tier)
                    SELECT user_id, asset_id, created_at, 'legacy'
                    FROM unlocks
                    WHERE user_id IS NOT NULL AND asset_id IS NOT NULL
                """).rowcount
                if migrated > 0:
                    report["data_backfills"].append(f"lead_unlocks migration: {migrated} rows")
                    log.info("  + Migrated %d unlocks → lead_unlocks", migrated)

            # ── 10. Log migration event ──────────────────────────────
            now = datetime.now(timezone.utc).isoformat()
            conn.execute("""
                INSERT INTO pipeline_events
                (asset_id, event_type, old_value, new_value, actor, reason, created_at)
                VALUES ('SYSTEM', 'TITANIUM_MIGRATION', ?, ?, 'migrate_titanium', 'Titanium schema upgrade', ?)
            """, [
                f"tables: {len(report['tables_created'])}, cols: {len(report['columns_added'])}",
                f"indexes: {len(report['indexes_created'])}, backfills: {len(report['data_backfills'])}",
                now,
            ])

    except Exception as e:
        report["errors"].append(str(e))
        log.error("Migration error: %s", e)
        raise

    # ── Summary ──────────────────────────────────────────────────
    log.info("")
    log.info("=" * 60)
    log.info("  MIGRATION COMPLETE")
    log.info("  Tables created:   %d", len(report["tables_created"]))
    log.info("  Columns added:    %d", len(report["columns_added"]))
    log.info("  Columns skipped:  %d (already exist)", len(report["columns_skipped"]))
    log.info("  Indexes created:  %d", len(report["indexes_created"]))
    log.info("  Data backfills:   %d", len(report["data_backfills"]))
    log.info("  Errors:           %d", len(report["errors"]))
    log.info("=" * 60)

    return report


if __name__ == "__main__":
    result = migrate()
    if result["errors"]:
        sys.exit(1)
