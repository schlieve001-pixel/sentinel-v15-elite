"""
VERIFUSE V2 — Attorney Onboarding Script
==========================================
Atomically onboard a verified attorney: update user, set verified status, grant credits.

Usage:
    python -m verifuse_v2.scripts.onboard_attorney \
        --email foo@bar.com --firm_name "Smith Law" \
        --bar_number 12345 --credits 25 --verify

    python -m verifuse_v2.scripts.onboard_attorney --email foo@bar.com --list
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = os.environ.get(
    "VERIFUSE_DB_PATH",
    str(Path(__file__).resolve().parent.parent / "data" / "verifuse_v2.db"),
)


def onboard_attorney(
    email: str,
    firm_name: str = "",
    firm_address: str = "",
    bar_number: str = "",
    credits: int = 25,
    verify: bool = False,
) -> dict:
    """Onboard or update an attorney user.

    Atomically: updates user row, sets verified_attorney=1, grants credits.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")

    try:
        user = conn.execute(
            "SELECT * FROM users WHERE email = ?", [email.lower()]
        ).fetchone()

        if not user:
            print(f"ERROR: No user found with email '{email}'")
            print("Register the user first via the API or directly in the database.")
            return {"error": "user_not_found"}

        user = dict(user)
        now = datetime.now(timezone.utc).isoformat()

        conn.execute("BEGIN IMMEDIATE")

        updates = []
        params = []

        if firm_name:
            updates.append("firm_name = ?")
            params.append(firm_name)

        if firm_address:
            updates.append("firm_address = ?")
            params.append(firm_address)

        if bar_number:
            updates.append("bar_number = ?")
            params.append(bar_number)

        if verify:
            updates.append("attorney_status = 'VERIFIED'")
            updates.append("attorney_verified_at = ?")
            params.append(now)
            updates.append("verified_attorney = 1")
            updates.append("bar_verified_at = ?")
            params.append(now)

        if credits > 0:
            updates.append("credits_remaining = credits_remaining + ?")
            params.append(credits)

        if not updates:
            print("Nothing to update. Use --verify, --firm_name, --bar_number, or --credits.")
            conn.execute("ROLLBACK")
            return {"status": "no_changes"}

        params.append(user["user_id"])
        sql = f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?"
        conn.execute(sql, params)

        # Log the event
        conn.execute("""
            INSERT INTO pipeline_events
            (asset_id, event_type, old_value, new_value, actor, reason, created_at)
            VALUES (?, 'ATTORNEY_ONBOARD', ?, ?, 'onboard_attorney.py', ?, ?)
        """, [
            user["user_id"],
            f"attorney_status={user.get('attorney_status', 'NONE')}",
            f"attorney_status={'VERIFIED' if verify else user.get('attorney_status', 'NONE')}, credits+={credits}",
            f"firm={firm_name}, bar={bar_number}",
            now,
        ])

        conn.execute("COMMIT")

        # Re-fetch and display
        updated = dict(conn.execute(
            "SELECT * FROM users WHERE user_id = ?", [user["user_id"]]
        ).fetchone())

        print("=" * 50)
        print("  ATTORNEY ONBOARDED")
        print("=" * 50)
        print(f"  Email:          {updated['email']}")
        print(f"  User ID:        {updated['user_id']}")
        print(f"  Firm:           {updated.get('firm_name', 'N/A')}")
        print(f"  Bar Number:     {updated.get('bar_number', 'N/A')}")
        print(f"  Firm Address:   {updated.get('firm_address', 'N/A')}")
        print(f"  Attorney Status: {updated.get('attorney_status', 'NONE')}")
        print(f"  Verified:       {bool(updated.get('verified_attorney', 0))}")
        print(f"  Credits:        {updated.get('credits_remaining', 0)}")
        print(f"  Tier:           {updated.get('tier', 'recon')}")
        print("=" * 50)

        return {
            "status": "ok",
            "user_id": updated["user_id"],
            "email": updated["email"],
            "verified": bool(updated.get("verified_attorney", 0)),
            "credits": updated.get("credits_remaining", 0),
        }

    except Exception as e:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        print(f"ERROR: {e}")
        return {"error": str(e)}
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Onboard/verify an attorney user")
    parser.add_argument("--email", required=True, help="User email address")
    parser.add_argument("--firm_name", default="", help="Law firm name")
    parser.add_argument("--firm_address", default="", help="Firm mailing address")
    parser.add_argument("--bar_number", default="", help="Bar number")
    parser.add_argument("--credits", type=int, default=25, help="Credits to grant (default: 25)")
    parser.add_argument("--verify", action="store_true", help="Set attorney_status=VERIFIED")
    parser.add_argument("--list", action="store_true", help="List all users")
    args = parser.parse_args()

    if args.list:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT email, firm_name, bar_number, attorney_status, verified_attorney, "
            "credits_remaining, tier FROM users ORDER BY email"
        ).fetchall()
        for r in rows:
            r = dict(r)
            print(f"  {r['email']:30s} | {r.get('attorney_status', 'NONE'):10s} | "
                  f"verified={r.get('verified_attorney', 0)} | credits={r.get('credits_remaining', 0)} | "
                  f"tier={r.get('tier', '?')}")
        conn.close()
        return

    onboard_attorney(
        email=args.email,
        firm_name=args.firm_name,
        firm_address=args.firm_address,
        bar_number=args.bar_number,
        credits=args.credits,
        verify=args.verify,
    )


if __name__ == "__main__":
    main()
