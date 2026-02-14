"""
VERIFUSE V2 — Database Abstraction Layer

SQLite now, Supabase later. One config change to swap.
All queries go through this module.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "verifuse_v2.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

# When you switch to Supabase, set these env vars and change get_connection()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Connection management ────────────────────────────────────────────

def get_connection() -> sqlite3.Connection:
    """Get a database connection. Returns SQLite for now."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Initialize the database schema."""
    schema_sql = SCHEMA_PATH.read_text()
    with get_db() as conn:
        conn.executescript(schema_sql)
    log.info("Database initialized at %s", DB_PATH)


# ── Deduplication ────────────────────────────────────────────────────

def deduplicate_assets() -> dict:
    """Remove duplicate records per case_number, keeping the most complete one.

    Duplicate pattern: denver_foreclosure_surplus_* and denver_excess_* for same case.
    Keeps the record with more non-null fields and higher confidence.
    """
    stats = {"duplicates_found": 0, "records_removed": 0}

    with get_db() as conn:
        # Find case_numbers that appear more than once
        dupes = conn.execute("""
            SELECT case_number, COUNT(*) as cnt
            FROM assets
            WHERE case_number IS NOT NULL AND case_number != ''
            GROUP BY case_number
            HAVING COUNT(*) > 1
        """).fetchall()

        stats["duplicates_found"] = len(dupes)

        for row in dupes:
            case_num = row[0]
            # Get all records for this case, ordered by completeness
            records = conn.execute("""
                SELECT asset_id, completeness_score, confidence_score,
                       total_indebtedness, sale_date, owner_of_record,
                       property_address, estimated_surplus
                FROM assets
                WHERE case_number = ?
                ORDER BY completeness_score DESC, confidence_score DESC,
                         estimated_surplus DESC
            """, [case_num]).fetchall()

            if len(records) <= 1:
                continue

            # Keep the first (most complete), remove the rest
            keep_id = records[0][0]
            for rec in records[1:]:
                remove_id = rec[0]
                conn.execute("DELETE FROM legal_status WHERE asset_id = ?", [remove_id])
                conn.execute("DELETE FROM unlocks WHERE asset_id = ?", [remove_id])
                conn.execute("DELETE FROM assets WHERE asset_id = ?", [remove_id])
                stats["records_removed"] += 1
                log.info("DEDUP: Removed %s (kept %s) for case %s",
                         remove_id, keep_id, case_num)

        # Log the dedup event
        if stats["records_removed"] > 0:
            conn.execute("""
                INSERT INTO pipeline_events
                (asset_id, event_type, old_value, new_value, actor, reason, created_at)
                VALUES ('SYSTEM', 'DEDUP', ?, ?, 'database.deduplicate_assets', 'Remove duplicate case records', ?)
            """, [
                f"{stats['duplicates_found']} duplicate case_numbers",
                f"{stats['records_removed']} records removed",
                _now_iso(),
            ])

    log.info("Dedup complete: %d duplicates found, %d records removed",
             stats["duplicates_found"], stats["records_removed"])
    return stats


# ── Admin queries ────────────────────────────────────────────────────

def upgrade_to_admin(email: str, credits: int = 9999) -> bool:
    """Upgrade a user to admin with sovereign tier and max credits."""
    with get_db() as conn:
        # Ensure is_admin column exists
        try:
            conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
        except Exception:
            pass  # Column already exists

        result = conn.execute("""
            UPDATE users SET tier = 'sovereign', credits_remaining = ?,
                is_admin = 1, is_active = 1
            WHERE email = ?
        """, [credits, email])
        return result.rowcount > 0


def is_admin(user: dict) -> bool:
    """Check if a user has admin privileges."""
    return bool(user.get("is_admin", 0))


def get_all_users() -> list[dict]:
    """Get all users (admin only)."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT user_id, email, full_name, firm_name, bar_number, tier,
                   credits_remaining, is_active, is_admin, created_at, last_login_at
            FROM users ORDER BY created_at DESC
        """).fetchall()
        return [dict(r) for r in rows]


def get_all_leads_raw(limit: int = 500) -> list[dict]:
    """Get all leads with raw unobfuscated data (admin only)."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT a.*, ls.record_class, ls.work_status, ls.promoted_at, ls.close_reason
            FROM assets a
            JOIN legal_status ls ON a.asset_id = ls.asset_id
            ORDER BY a.estimated_surplus DESC
            LIMIT ?
        """, [limit]).fetchall()
        return [dict(r) for r in rows]


# ── Asset queries ────────────────────────────────────────────────────

def get_leads(
    county: Optional[str] = None,
    min_surplus: float = 0.0,
    grade: Optional[str] = None,
    record_class: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Get leads with filters. Returns dicts with joined asset + legal_status."""
    query = """
        SELECT a.*, ls.record_class, ls.work_status, ls.promoted_at, ls.close_reason
        FROM assets a
        JOIN legal_status ls ON a.asset_id = ls.asset_id
        WHERE 1=1
    """
    params: list[Any] = []

    if county:
        query += " AND a.county = ?"
        params.append(county)
    if min_surplus > 0:
        query += " AND a.estimated_surplus >= ?"
        params.append(min_surplus)
    if grade:
        query += " AND ls.data_grade = ?"
        params.append(grade)
    if record_class:
        query += " AND ls.record_class = ?"
        params.append(record_class)

    query += " ORDER BY a.estimated_surplus DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_lead_by_id(asset_id: str) -> Optional[dict]:
    """Get a single lead by asset_id."""
    query = """
        SELECT a.*, ls.record_class, ls.work_status, ls.promoted_at, ls.close_reason
        FROM assets a
        JOIN legal_status ls ON a.asset_id = ls.asset_id
        WHERE a.asset_id = ?
    """
    with get_db() as conn:
        row = conn.execute(query, [asset_id]).fetchone()
        return dict(row) if row else None


def get_lead_stats() -> dict:
    """Get summary statistics for the dashboard.

    Only counts assets with >= $1,000 surplus (quality filter).
    """
    MIN_SURPLUS = 1000.0
    with get_db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM assets WHERE estimated_surplus >= ?",
            [MIN_SURPLUS],
        ).fetchone()[0]

        gold = conn.execute("""
            SELECT COUNT(*) FROM assets a
            JOIN legal_status ls ON a.asset_id = ls.asset_id
            WHERE ls.data_grade = 'GOLD' AND a.estimated_surplus >= ?
        """, [MIN_SURPLUS]).fetchone()[0]

        total_surplus = conn.execute(
            "SELECT COALESCE(SUM(estimated_surplus), 0) FROM assets WHERE estimated_surplus >= ?",
            [MIN_SURPLUS],
        ).fetchone()[0]

        counties = conn.execute("""
            SELECT a.county, COUNT(*) as cnt, COALESCE(SUM(a.estimated_surplus), 0) as total
            FROM assets a
            WHERE a.estimated_surplus >= ?
            GROUP BY a.county ORDER BY total DESC
        """, [MIN_SURPLUS]).fetchall()

        # Count staged records waiting for enrichment
        staged = 0
        try:
            staged = conn.execute("SELECT COUNT(*) FROM assets_staging").fetchone()[0]
        except Exception:
            pass

        return {
            "total_assets": total,
            "attorney_ready": total,  # All remaining are quality
            "gold_grade": gold,
            "total_claimable_surplus": round(total_surplus, 2),
            "counties": [dict(r) for r in counties],
            "staged_for_enrichment": staged,
        }


# ── User queries ─────────────────────────────────────────────────────

def create_user(
    user_id: str, email: str, password_hash: str,
    full_name: str = "", firm_name: str = "", bar_number: str = "",
    tier: str = "recon",
) -> dict:
    """Create a new user."""
    now = _now_iso()
    credits = {"recon": 5, "operator": 25, "sovereign": 100}.get(tier, 5)
    with get_db() as conn:
        conn.execute("""
            INSERT INTO users (user_id, email, password_hash, full_name, firm_name,
                               bar_number, tier, credits_remaining, credits_reset_at,
                               is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        """, [user_id, email, password_hash, full_name, firm_name,
              bar_number, tier, credits, now, now])
    return get_user_by_id(user_id)


def get_user_by_email(email: str) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", [email]).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: str) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", [user_id]).fetchone()
        return dict(row) if row else None


def update_user_login(user_id: str) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET last_login_at = ? WHERE user_id = ?",
            [_now_iso(), user_id],
        )


def update_user_stripe(user_id: str, customer_id: str, subscription_id: str) -> None:
    with get_db() as conn:
        conn.execute("""
            UPDATE users SET stripe_customer_id = ?, stripe_subscription_id = ?
            WHERE user_id = ?
        """, [customer_id, subscription_id, user_id])


def update_user_tier(user_id: str, tier: str) -> None:
    credits = {"recon": 5, "operator": 25, "sovereign": 100}.get(tier, 5)
    with get_db() as conn:
        conn.execute("""
            UPDATE users SET tier = ?, credits_remaining = ?, credits_reset_at = ?
            WHERE user_id = ?
        """, [tier, credits, _now_iso(), user_id])


# ── Unlock / credit queries ─────────────────────────────────────────

def record_unlock(user_id: str, asset_id: str) -> bool:
    """Deduct a credit and record the unlock. Returns False if no credits."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT credits_remaining, tier FROM users WHERE user_id = ?",
            [user_id],
        ).fetchone()
        if not row or row["credits_remaining"] <= 0:
            return False

        conn.execute(
            "UPDATE users SET credits_remaining = credits_remaining - 1 WHERE user_id = ?",
            [user_id],
        )
        conn.execute(
            "INSERT INTO unlocks (user_id, asset_id, unlock_type, created_at) VALUES (?, ?, 'full', ?)",
            [user_id, asset_id, _now_iso()],
        )
        return True


def has_unlocked(user_id: str, asset_id: str) -> bool:
    """Check if a user already unlocked this asset."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM unlocks WHERE user_id = ? AND asset_id = ?",
            [user_id, asset_id],
        ).fetchone()
        return row is not None


def get_user_unlocks(user_id: str) -> list[dict]:
    """Get all assets a user has unlocked."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT u.*, a.county, a.owner_of_record, a.estimated_surplus, a.property_address
            FROM unlocks u
            JOIN assets a ON u.asset_id = a.asset_id
            WHERE u.user_id = ?
            ORDER BY u.created_at DESC
        """, [user_id]).fetchall()
        return [dict(r) for r in rows]


# ── County / statute queries ──────────────────────────────────────

def get_statute_authority(county: Optional[str] = None) -> list[dict]:
    """Get statute authority rules for counties."""
    with get_db() as conn:
        if county:
            rows = conn.execute(
                "SELECT * FROM statute_authority WHERE county = ?", [county]
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM statute_authority ORDER BY county"
            ).fetchall()
        return [dict(r) for r in rows]


def get_county_summary() -> list[dict]:
    """Get per-county lead counts and surplus totals (quality assets only)."""
    MIN_SURPLUS = 1000.0
    with get_db() as conn:
        rows = conn.execute("""
            SELECT
                a.county,
                COUNT(*) as lead_count,
                COALESCE(SUM(a.estimated_surplus), 0) as total_surplus,
                COALESCE(AVG(a.estimated_surplus), 0) as avg_surplus,
                COALESCE(MAX(a.estimated_surplus), 0) as max_surplus,
                SUM(CASE WHEN ls.data_grade = 'GOLD' THEN 1 ELSE 0 END) as gold_count,
                SUM(CASE WHEN ls.record_class = 'ATTORNEY' THEN 1 ELSE 0 END) as attorney_count
            FROM assets a
            JOIN legal_status ls ON a.asset_id = ls.asset_id
            WHERE a.estimated_surplus >= ?
            GROUP BY a.county
            ORDER BY total_surplus DESC
        """, [MIN_SURPLUS]).fetchall()
        return [dict(r) for r in rows]


# ── Pipeline event logging ────────────────────────────────────────

def log_pipeline_event(
    asset_id: str,
    event_type: str,
    old_value: str = "",
    new_value: str = "",
    actor: str = "system",
    reason: str = "",
) -> None:
    """Record an audit event in the pipeline_events table."""
    with get_db() as conn:
        conn.execute("""
            INSERT INTO pipeline_events
            (asset_id, event_type, old_value, new_value, actor, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, [asset_id, event_type, old_value, new_value, actor, reason, _now_iso()])
