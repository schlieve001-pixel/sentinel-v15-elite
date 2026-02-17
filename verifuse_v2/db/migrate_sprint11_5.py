"""
VERIFUSE V2 — Sprint 11.5 Migration Script
=============================================
Idempotent schema changes for Sprint 11.5.

All ALTER TABLE commands check PRAGMA table_info first.
All CREATE INDEX use IF NOT EXISTS.

Usage:
    export VERIFUSE_DB_PATH=/path/to/verifuse_v2.db
    python -m verifuse_v2.db.migrate_sprint11_5
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


def _add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, typedef: str
) -> bool:
    """Add column if it doesn't exist. Returns True if added."""
    cols = _get_columns(conn, table)
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {typedef}")
        log.info("  Added column %s.%s (%s)", table, column, typedef)
        return True
    log.info("  Column %s.%s already exists — skipping", table, column)
    return False


def run_migration():
    """Execute all Sprint 11.5 migrations. Idempotent."""
    if not os.path.exists(DB_PATH):
        log.error("Database not found: %s", DB_PATH)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")

    log.info("=" * 60)
    log.info("  SPRINT 11.5 MIGRATION")
    log.info("  DB: %s", DB_PATH)
    log.info("  Time: %s", _now())
    log.info("=" * 60)

    # ── Task 1: pipeline_events — add metadata_json column ────────
    log.info("")
    log.info("Task 1: pipeline_events.metadata_json")
    _add_column_if_missing(conn, "pipeline_events", "metadata_json", "TEXT")
    conn.commit()

    # ── Task 2: pipeline_events — index on (event_type, time_col) ─
    log.info("")
    log.info("Task 2: pipeline_events index")

    pe_cols = _get_columns(conn, "pipeline_events")
    time_col = None
    if "created_at" in pe_cols:
        time_col = "created_at"
    elif "timestamp" in pe_cols:
        time_col = "timestamp"

    if time_col:
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_pipeline_events_type_time "
            f"ON pipeline_events(event_type, {time_col})"
        )
        log.info("  Created index on pipeline_events(event_type, %s)", time_col)
    else:
        log.warning("  No time column found in pipeline_events — skipping index")

    conn.commit()

    # ── Task 3: users — email verification columns ────────────────
    log.info("")
    log.info("Task 3: users email verification columns")
    _add_column_if_missing(conn, "users", "email_verified", "INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "users", "email_verify_code", "TEXT")
    _add_column_if_missing(conn, "users", "email_verify_sent_at", "TEXT")
    conn.commit()

    # ── Log migration event ───────────────────────────────────────
    try:
        conn.execute("""
            INSERT INTO pipeline_events
            (asset_id, event_type, old_value, new_value, actor, reason, created_at)
            VALUES ('SYSTEM', 'MIGRATION', 'sprint-11', 'sprint-11.5', 'migrate_sprint11_5.py',
                    'metadata_json + email verification columns', ?)
        """, [_now()])
        conn.commit()
    except Exception as e:
        log.warning("Could not log migration event: %s", e)

    # ── Summary ───────────────────────────────────────────────────
    log.info("")
    log.info("=" * 60)
    log.info("  SPRINT 11.5 MIGRATION COMPLETE")
    log.info("=" * 60)

    # Report current state
    try:
        total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        log.info("  Total leads: %d", total)
        user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        log.info("  Total users: %d", user_count)
    except Exception:
        pass

    log.info("=" * 60)
    conn.close()
    return True


if __name__ == "__main__":
    run_migration()
