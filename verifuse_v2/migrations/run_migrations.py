#!/usr/bin/env python3
"""
VeriFuse Migration Runner — Omega v4.7

Applies SQL migrations idempotently with file locking.
Handles:
  - Schema creation (002_omega_hardening.sql)
  - Users table evolution (add missing columns)
  - Wallet backfill from users.credits_remaining
  - Tier rename (recon → scout)
  - Lead deduplication (county + case_number)

Usage:
    python3 verifuse_v2/migrations/run_migrations.py [--db PATH]
"""

from __future__ import annotations

import argparse
import fcntl
import logging
import os
import sqlite3
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("migrate")

LOCK_PATH = "/tmp/verifuse_migrate.lock"
DEFAULT_DB = os.getenv(
    "VERIFUSE_DB_PATH",
    str(Path(__file__).resolve().parent.parent / "data" / "verifuse_v2.db"),
)
MIGRATIONS_DIR = Path(__file__).resolve().parent


def _harden(conn: sqlite3.Connection) -> None:
    """Apply SQLite hardening pragmas."""
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")


def _get_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Return set of column names for a table."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [table]
    ).fetchone()
    return row is not None


def _index_exists(conn: sqlite3.Connection, index_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", [index_name]
    ).fetchone()
    return row is not None


def evolve_users(conn: sqlite3.Connection) -> None:
    """Add missing columns to users table (safe ALTER ADD)."""
    existing = _get_columns(conn, "users")
    additions = {
        "stripe_customer_id": "TEXT",
        "stripe_subscription_id": "TEXT",
        "subscription_status": "TEXT DEFAULT 'none'",
        "current_period_end": "TEXT",
        "founders_pricing": "INTEGER DEFAULT 0",
        "attorney_status": "TEXT DEFAULT 'NONE'",
        "bar_number": "TEXT",
        "bar_state": "TEXT DEFAULT 'CO'",
        "firm_name": "TEXT",
        "verification_url": "TEXT",
        "email_verified": "INTEGER DEFAULT 0",
    }
    for col, typedef in additions.items():
        if col not in existing:
            log.info("  ADD COLUMN users.%s %s", col, typedef)
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} {typedef}")

    # Rename tier 'recon' → 'scout'
    updated = conn.execute(
        "UPDATE users SET tier = 'scout' WHERE tier = 'recon'"
    ).rowcount
    if updated:
        log.info("  Renamed tier recon→scout for %d users", updated)

    # Update default tier (can't ALTER DEFAULT in SQLite, but new inserts
    # will use the application-level default 'scout')


def apply_sql_file(conn: sqlite3.Connection, path: Path) -> None:
    """Execute a .sql file. Statements separated by ';'."""
    sql = path.read_text()
    log.info("Applying %s ...", path.name)
    conn.executescript(sql)
    log.info("  Done.")


def deduplicate_leads(conn: sqlite3.Connection) -> None:
    """Remove duplicate leads (same county + case_number), keeping newest."""
    dupes = conn.execute(
        "SELECT county, case_number, COUNT(*) as cnt "
        "FROM leads WHERE case_number IS NOT NULL "
        "GROUP BY county, case_number HAVING cnt > 1"
    ).fetchall()
    if not dupes:
        log.info("  No duplicate leads found.")
        return
    for county, case_number, cnt in dupes:
        # Keep the row with the latest sale_date (or highest rowid as tiebreaker)
        conn.execute(
            "DELETE FROM leads WHERE rowid NOT IN ("
            "  SELECT rowid FROM leads "
            "  WHERE county = ? AND case_number = ? "
            "  ORDER BY sale_date DESC, rowid DESC LIMIT 1"
            ") AND county = ? AND case_number = ?",
            [county, case_number, county, case_number],
        )
        log.info("  Deduped leads: %s / %s (%d → 1)", county, case_number, cnt)


def make_county_case_unique(conn: sqlite3.Connection) -> None:
    """Upgrade idx_leads_county_case to UNIQUE (after dedup)."""
    # Drop the old non-unique index if it exists
    if _index_exists(conn, "idx_leads_county_case"):
        conn.execute("DROP INDEX idx_leads_county_case")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_county_case "
        "ON leads(county, case_number)"
    )
    log.info("  idx_leads_county_case is now UNIQUE")


def backfill_wallet(conn: sqlite3.Connection) -> None:
    """Create wallet rows from users.credits_remaining for existing users."""
    if not _table_exists(conn, "wallet"):
        log.warning("  wallet table not found — skipping backfill")
        return
    inserted = conn.execute(
        "INSERT OR IGNORE INTO wallet (user_id, subscription_credits, purchased_credits, tier, updated_at) "
        "SELECT user_id, MAX(COALESCE(credits_remaining, 0), 0), 0, "
        "  COALESCE(NULLIF(tier, ''), 'scout'), datetime('now') "
        "FROM users"
    ).rowcount
    log.info("  Wallet backfill: %d rows inserted", inserted)


def run(db_path: str) -> None:
    log.info("Migration target: %s", db_path)

    if not os.path.exists(db_path):
        log.error("Database not found: %s", db_path)
        sys.exit(1)

    # File lock — fail fast if another migration is running
    lock_fd = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.error("Another migration is running (lock: %s)", LOCK_PATH)
        sys.exit(1)

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        _harden(conn)

        log.info("=== Phase 1: Users table evolution ===")
        evolve_users(conn)
        conn.commit()

        log.info("=== Phase 2: Lead deduplication ===")
        deduplicate_leads(conn)
        conn.commit()

        log.info("=== Phase 3: Apply 002_omega_hardening.sql ===")
        sql_file = MIGRATIONS_DIR / "002_omega_hardening.sql"
        if sql_file.exists():
            apply_sql_file(conn, sql_file)
        else:
            log.warning("SQL file not found: %s", sql_file)

        log.info("=== Phase 4: Unique county+case index ===")
        make_county_case_unique(conn)
        conn.commit()

        log.info("=== Phase 5: Wallet backfill ===")
        backfill_wallet(conn)
        conn.commit()

        # Verify
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()]
        log.info("=== Migration complete. Tables: %s ===", ", ".join(tables))

        conn.close()
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
        try:
            os.unlink(LOCK_PATH)
        except OSError:
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VeriFuse Migration Runner")
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to SQLite database")
    args = parser.parse_args()
    run(args.db)
