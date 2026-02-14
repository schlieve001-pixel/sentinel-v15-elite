"""
VERIFUSE V2 — Master Migration Utility

Idempotent migration that inspects DB schema before touching it.
Uses PRAGMA table_info() before each ALTER TABLE — additive only, never destructive.

Usage:
  python -m verifuse_v2.db.migrate_master
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from verifuse_v2.db import database as db

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)


# ── Expected schema ──────────────────────────────────────────────────

REQUIRED_TABLES = [
    "assets", "legal_status", "statute_authority", "pipeline_events",
    "users", "unlocks", "tiers", "scraper_registry", "blacklist",
    "assets_staging",
]

ASSETS_STAGING_DDL = """
CREATE TABLE IF NOT EXISTS assets_staging (
    staging_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    county          TEXT,
    case_number     TEXT,
    property_address TEXT,
    owner_of_record TEXT,
    sale_date       TEXT,
    raw_data_json   TEXT,
    source_file     TEXT,
    pdf_path        TEXT,
    status          TEXT DEFAULT 'STAGED',
    processed_at    TEXT,
    engine_version  TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

# Columns to add if missing: (table, column_name, column_def)
COLUMN_MIGRATIONS = [
    ("assets_staging", "pdf_path", "TEXT"),
    ("assets_staging", "status", "TEXT DEFAULT 'STAGED'"),
    ("assets_staging", "processed_at", "TEXT"),
    ("assets_staging", "engine_version", "TEXT"),
    ("assets", "winning_bid", "REAL DEFAULT 0.0"),
    ("assets", "vertex_processed", "INTEGER DEFAULT 0"),
]

REQUIRED_INDEXES = [
    ("idx_assets_county", "assets", "county"),
    ("idx_assets_grade", "assets", "data_grade"),
    ("idx_assets_surplus", "assets", "estimated_surplus"),
    ("idx_legal_class", "legal_status", "record_class"),
    ("idx_legal_grade", "legal_status", "data_grade"),
    ("idx_events_asset", "pipeline_events", "asset_id"),
    ("idx_unlocks_user", "unlocks", "user_id"),
    ("idx_unlocks_asset", "unlocks", "asset_id"),
    ("idx_users_email", "users", "email"),
    ("idx_staging_status", "assets_staging", "status"),
]


def _get_existing_tables(conn) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {r[0] for r in rows}


def _get_existing_columns(conn, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


def _get_existing_indexes(conn) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
    ).fetchall()
    return {r[0] for r in rows}


def run_migration() -> dict:
    """Run the full idempotent migration. Returns a report dict."""
    report = {
        "tables_created": [],
        "tables_present": [],
        "columns_added": [],
        "columns_present": [],
        "indexes_created": [],
        "indexes_present": [],
        "errors": [],
    }

    # Step 0: Initialize base schema
    db.init_db()

    with db.get_db() as conn:
        # ── Step 1: Check tables ──────────────────────────────────────
        existing_tables = _get_existing_tables(conn)

        # Create assets_staging if missing
        if "assets_staging" not in existing_tables:
            try:
                conn.executescript(ASSETS_STAGING_DDL)
                report["tables_created"].append("assets_staging")
                log.info("CREATED table: assets_staging")
            except Exception as e:
                report["errors"].append(f"Failed to create assets_staging: {e}")
                log.error("Failed to create assets_staging: %s", e)

        # Refresh table list
        existing_tables = _get_existing_tables(conn)

        for table in REQUIRED_TABLES:
            if table in existing_tables:
                report["tables_present"].append(table)
            else:
                report["errors"].append(f"Missing table: {table}")
                log.warning("MISSING table: %s", table)

        # ── Step 2: Add missing columns ───────────────────────────────
        for table, col_name, col_def in COLUMN_MIGRATIONS:
            if table not in existing_tables:
                continue

            existing_cols = _get_existing_columns(conn, table)

            if col_name in existing_cols:
                report["columns_present"].append(f"{table}.{col_name}")
            else:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
                    report["columns_added"].append(f"{table}.{col_name}")
                    log.info("ADDED column: %s.%s (%s)", table, col_name, col_def)
                except Exception as e:
                    report["errors"].append(f"Failed to add {table}.{col_name}: {e}")
                    log.error("Failed to add %s.%s: %s", table, col_name, e)

        # ── Step 3: Verify indexes ────────────────────────────────────
        existing_indexes = _get_existing_indexes(conn)

        for idx_name, table, column in REQUIRED_INDEXES:
            if idx_name in existing_indexes:
                report["indexes_present"].append(idx_name)
            else:
                try:
                    conn.execute(
                        f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({column})"
                    )
                    report["indexes_created"].append(idx_name)
                    log.info("CREATED index: %s ON %s(%s)", idx_name, table, column)
                except Exception as e:
                    report["errors"].append(f"Failed to create index {idx_name}: {e}")
                    log.error("Failed to create index %s: %s", idx_name, e)

        # ── Step 4: Log migration event ───────────────────────────────
        now = datetime.now(timezone.utc).isoformat()
        changes = report["tables_created"] + report["columns_added"] + report["indexes_created"]
        conn.execute("""
            INSERT INTO pipeline_events
            (asset_id, event_type, old_value, new_value, actor, reason, created_at)
            VALUES ('SYSTEM', 'MIGRATION', 'migrate_master', ?, 'migrate_master.py', ?, ?)
        """, [
            f"{len(changes)} changes applied",
            f"Tables: {len(report['tables_created'])}, Cols: {len(report['columns_added'])}, Idx: {len(report['indexes_created'])}",
            now,
        ])

    return report


def print_report(report: dict) -> None:
    """Print a structured migration report."""
    print()
    print("=" * 60)
    print("  VERIFUSE V2 — MIGRATION REPORT")
    print("=" * 60)

    print(f"\n  Tables present:  {len(report['tables_present'])}/{len(REQUIRED_TABLES)}")
    print(f"  Tables created:  {len(report['tables_created'])}")
    if report["tables_created"]:
        for t in report["tables_created"]:
            print(f"    + {t}")

    print(f"\n  Columns present: {len(report['columns_present'])}")
    print(f"  Columns added:   {len(report['columns_added'])}")
    if report["columns_added"]:
        for c in report["columns_added"]:
            print(f"    + {c}")

    print(f"\n  Indexes present: {len(report['indexes_present'])}")
    print(f"  Indexes created: {len(report['indexes_created'])}")
    if report["indexes_created"]:
        for i in report["indexes_created"]:
            print(f"    + {i}")

    if report["errors"]:
        print(f"\n  ERRORS: {len(report['errors'])}")
        for e in report["errors"]:
            print(f"    ! {e}")
    else:
        print("\n  STATUS: ALL CHECKS PASSED")

    print("=" * 60)


if __name__ == "__main__":
    report = run_migration()
    print_report(report)
    if report["errors"]:
        sys.exit(1)
