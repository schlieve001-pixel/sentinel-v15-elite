"""
VERIFUSE V2 — create_superuser.py

Upserts the master admin account. Idempotent — safe to run multiple times.

Usage:
    export VERIFUSE_DB_PATH=/path/to/verifuse_v2.db
    python -m verifuse_v2.ops.create_superuser
"""

from __future__ import annotations

import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone

# ── Fail-fast ────────────────────────────────────────────────────────

DB_PATH = os.environ.get("VERIFUSE_DB_PATH")
if not DB_PATH:
    print("FATAL: VERIFUSE_DB_PATH not set.")
    sys.exit(1)

# ── Superuser credentials ────────────────────────────────────────────

SUPERUSER_EMAIL = "verifuse.tech@gmail.com"
SUPERUSER_PASSWORD = "#Roxies1badgirl"
SUPERUSER_TIER = "sovereign"
SUPERUSER_CREDITS = 999999


def create_superuser() -> dict:
    import bcrypt

    password_hash = bcrypt.hashpw(
        SUPERUSER_PASSWORD.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")

    now = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    try:
        # Check if user exists
        existing = conn.execute(
            "SELECT user_id FROM users WHERE email = ?", [SUPERUSER_EMAIL]
        ).fetchone()

        if existing:
            # UPDATE existing user to superuser
            conn.execute("""
                UPDATE users SET
                    password_hash = ?,
                    tier = ?,
                    credits_remaining = ?,
                    is_admin = 1,
                    is_active = 1,
                    attorney_status = 'VERIFIED',
                    last_login_at = ?
                WHERE email = ?
            """, [password_hash, SUPERUSER_TIER, SUPERUSER_CREDITS, now, SUPERUSER_EMAIL])
            user_id = existing["user_id"]
            action = "updated"
        else:
            # INSERT new superuser
            user_id = str(uuid.uuid4())
            conn.execute("""
                INSERT INTO users
                    (user_id, email, password_hash, full_name, firm_name,
                     tier, credits_remaining, credits_reset_at,
                     is_active, is_admin, attorney_status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 1, 'VERIFIED', ?)
            """, [
                user_id, SUPERUSER_EMAIL, password_hash,
                "VeriFuse Admin", "VeriFuse Tech",
                SUPERUSER_TIER, SUPERUSER_CREDITS, now, now,
            ])
            action = "created"

        # Log the event
        try:
            conn.execute("""
                INSERT INTO pipeline_events
                (asset_id, event_type, old_value, new_value, actor, reason, created_at)
                VALUES (?, 'SUPERUSER_UPSERT', '', ?, 'create_superuser.py', 'Master admin upsert', ?)
            """, [user_id, f"email={SUPERUSER_EMAIL} tier={SUPERUSER_TIER}", now])
        except Exception:
            pass

        conn.commit()

        print(f"\n{'='*60}")
        print(f"  SUPERUSER {action.upper()}")
        print(f"{'='*60}")
        print(f"  Email:    {SUPERUSER_EMAIL}")
        print(f"  Tier:     {SUPERUSER_TIER}")
        print(f"  Credits:  {SUPERUSER_CREDITS}")
        print(f"  Admin:    YES")
        print(f"  Attorney: VERIFIED")
        print(f"  User ID:  {user_id}")
        print(f"{'='*60}\n")

        return {"action": action, "user_id": user_id, "email": SUPERUSER_EMAIL}

    finally:
        conn.close()


if __name__ == "__main__":
    create_superuser()
