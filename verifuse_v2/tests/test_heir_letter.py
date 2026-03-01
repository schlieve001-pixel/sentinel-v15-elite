"""
VeriFuse — Heir Letter Endpoint Integration Tests
=================================================
Tests all HTTP response paths for POST /api/assets/{id}/heir-letter:

  CASE A: admin token                         → 200, PDF, NO credit deduction
  CASE B: attorney, unlocked, has 10 credits  → 200, PDF, credits drop by 5
  CASE C: attorney, unlocked, 0 credits       → 402 Insufficient credits
  CASE D: attorney, lead NOT unlocked         → 403 Lead must be unlocked first
  CASE E: public role (non-attorney)          → 403 Attorney or admin role required
  CASE F: no token                            → 401 Authentication required

Run: python3 -m verifuse_v2.tests.test_heir_letter
(API must be running: bin/vf api-start OR uvicorn manually on port 8000)
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

API = os.getenv("VERIFUSE_API", "http://localhost:8000")
DB_PATH = os.getenv(
    "VERIFUSE_DB_PATH",
    str(Path(__file__).resolve().parent.parent / "data" / "verifuse_v2.db"),
)

# A known GOLD/SILVER lead to test against
LEAD_ID = "5fc87625-0f10-42e3-aa1e-f1b77fd3370d"

ADMIN_EMAIL = "verifuse.tech@gmail.com"
ADMIN_PASSWORD = os.getenv("VERIFUSE_ADMIN_PASSWORD", "VeriFuse2024!")

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
WARN = "\033[33mWARN\033[0m"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    tag = PASS if ok else FAIL
    print(f"  [{tag}] {name}" + (f" — {detail}" if detail else ""))
    results.append((name, ok, detail))
    return ok


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _make_password_hash(pw: str) -> str:
    """bcrypt-compatible hash — use passlib if available, else SHA256 placeholder."""
    try:
        from passlib.hash import bcrypt  # type: ignore[import]
        return bcrypt.hash(pw)
    except ImportError:
        # Fallback: the API uses passlib bcrypt — this won't work for login
        # but we can still insert a known hash and use the token approach
        return hashlib.sha256(pw.encode()).hexdigest()


def _create_test_user(
    email: str,
    role: str = "approved_attorney",
    attorney_status: str = "VERIFIED",
    tier: str = "partner",
    credits: int = 0,
) -> str:
    """Insert a test user. Returns user_id."""
    conn = _db()
    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    try:
        # Use bcrypt if available
        try:
            from passlib.hash import bcrypt  # type: ignore[import]
            pw_hash = bcrypt.hash("TestPass123!")
        except ImportError:
            pw_hash = "$2b$12$placeholder_hash_for_testing_purposes_only_xxxxxx"

        conn.execute(
            """INSERT OR IGNORE INTO users
               (user_id, email, password_hash, full_name, role, attorney_status,
                tier, credits_remaining, is_admin, is_active, created_at,
                email_verified, verified_attorney)
               VALUES (?,?,?,?,?,?,?,?,0,1,?,1,1)""",
            [user_id, email, pw_hash, f"Test {role}", role, attorney_status,
             tier, credits, now],
        )

        # Seed ledger if credits > 0
        if credits > 0:
            ledger_id = str(uuid.uuid4())
            conn.execute(
                """INSERT OR IGNORE INTO unlock_ledger_entries
                   (id, user_id, source, qty_total, qty_remaining,
                    purchased_ts, expires_ts, tier_at_purchase)
                   VALUES (?, ?, 'subscription', ?, ?, ?, NULL, ?)""",
                [ledger_id, user_id, credits, credits,
                 int(time.time()), tier],
            )
    finally:
        conn.close()
    return user_id


def _cleanup_test_user(user_id: str) -> None:
    conn = _db()
    try:
        conn.execute("DELETE FROM unlock_spend_journal WHERE unlock_id IN "
                     "(SELECT id FROM asset_unlocks WHERE user_id=?)", [user_id])
        conn.execute("DELETE FROM asset_unlocks WHERE user_id=?", [user_id])
        conn.execute("DELETE FROM lead_unlocks WHERE user_id=?", [user_id])
        conn.execute("DELETE FROM unlock_ledger_entries WHERE user_id=?", [user_id])
        conn.execute("DELETE FROM transactions WHERE user_id=?", [user_id])
        conn.execute("DELETE FROM audit_log WHERE user_id=?", [user_id])
        conn.execute("DELETE FROM users WHERE user_id=?", [user_id])
    finally:
        conn.close()


def _unlock_lead_for_user(user_id: str, lead_id: str) -> None:
    """Insert an asset_unlocks row simulating a prior lead unlock."""
    conn = _db()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO asset_unlocks
               (id, user_id, asset_id, credits_spent, unlocked_at)
               VALUES (?, ?, ?, 1, ?)""",
            [str(uuid.uuid4()), user_id, lead_id, int(time.time())],
        )
    finally:
        conn.close()


def _ledger_balance(user_id: str) -> int:
    conn = _db()
    try:
        now = int(time.time())
        row = conn.execute(
            "SELECT COALESCE(SUM(qty_remaining), 0) FROM unlock_ledger_entries "
            "WHERE user_id = ? AND (expires_ts IS NULL OR expires_ts > ?)",
            [user_id, now],
        ).fetchone()
        return int(row[0])
    finally:
        conn.close()


def _journal_rows_for_user(user_id: str) -> int:
    """Count unlock_spend_journal rows that reference ledger entries owned by user."""
    conn = _db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM unlock_spend_journal usj "
            "JOIN unlock_ledger_entries ule ON ule.id = usj.ledger_entry_id "
            "WHERE ule.user_id = ?",
            [user_id],
        ).fetchone()
        return int(row[0])
    finally:
        conn.close()


def _transactions_count(user_id: str, txn_type: str = "premium_dossier") -> int:
    conn = _db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE user_id=? AND type=?",
            [user_id, txn_type],
        ).fetchone()
        return int(row[0])
    finally:
        conn.close()


def _get_token(email: str, password: str) -> str | None:
    """Login and return JWT token."""
    r = requests.post(f"{API}/api/auth/login",
                      json={"email": email, "password": password}, timeout=10)
    if r.status_code == 200:
        return r.json().get("access_token")
    return None


def _get_token_direct(user_id: str) -> str | None:
    """Generate a signed JWT matching the API's own signing logic (PyJWT, HS256).

    API uses: os.getenv("VERIFUSE_JWT_SECRET", "vf2-dev-secret-change-in-production")
    Payload: {"sub": user_id, ...}
    """
    try:
        import jwt as _pyjwt  # PyJWT — same library as api.py uses
    except ImportError as e:
        print(f"    [{WARN}] PyJWT not installed: {e}")
        return None

    # Mirror exactly how api.py reads the secret
    secret = os.getenv("VERIFUSE_JWT_SECRET", "vf2-dev-secret-change-in-production")
    # Also check env file in case it was set there but not exported
    if secret == "vf2-dev-secret-change-in-production":
        env_path = Path("/etc/verifuse/verifuse.env")
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("VERIFUSE_JWT_SECRET="):
                    secret = line.split("=", 1)[1].strip().strip('"').strip("'")

    try:
        payload = {
            "sub": user_id,
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        }
        token = _pyjwt.encode(payload, secret, algorithm="HS256")
        # PyJWT >= 2.x returns str; < 2.x returns bytes
        return token if isinstance(token, str) else token.decode()
    except Exception as e:
        print(f"    [{WARN}] Token generation failed: {e}")
        return None


# Unique test IPs — each test case uses a distinct IP to avoid shared rate limit bucket
_test_ip_counter = 0

def _next_test_ip() -> str:
    global _test_ip_counter
    _test_ip_counter += 1
    return f"10.254.{(_test_ip_counter >> 8) & 0xFF}.{_test_ip_counter & 0xFF}"


def post_heir_letter(
    token: str | None,
    lead_id: str,
    test_ip: str | None = None,
) -> requests.Response:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    # Use a unique X-Forwarded-For per test call so each call hits its own rate limit bucket
    headers["X-Forwarded-For"] = test_ip or _next_test_ip()
    return requests.post(
        f"{API}/api/assets/{lead_id}/heir-letter",
        headers=headers,
        timeout=30,
    )


# ════════════════════════════════════════════════════════════════════════════════
# Test Cases
# ════════════════════════════════════════════════════════════════════════════════

def test_case_f_no_token() -> None:
    print("\n── CASE F: No token → 401 ──")
    r = post_heir_letter(None, LEAD_ID)
    check("No token → 401", r.status_code == 401, f"got {r.status_code}")


def test_case_e_public_role() -> None:
    print("\n── CASE E: Public role (non-attorney) → 403 ──")
    # Create a public user with no attorney role
    uid = _create_test_user(
        f"test_public_{uuid.uuid4().hex[:8]}@verifuse-test.internal",
        role="public",
        attorney_status="NONE",
        credits=10,
    )
    token = _get_token_direct(uid)
    if not token:
        print(f"    [{WARN}] Could not generate token for public user — skipping CASE E")
        _cleanup_test_user(uid)
        return
    try:
        _unlock_lead_for_user(uid, LEAD_ID)
        r = post_heir_letter(token, LEAD_ID)
        check("Public role → 403", r.status_code == 403, f"got {r.status_code}")
        if r.status_code == 403:
            check("403 detail mentions role", "role" in r.text.lower() or "attorney" in r.text.lower(),
                  r.text[:120])
    finally:
        _cleanup_test_user(uid)


def test_case_d_locked_lead() -> None:
    print("\n── CASE D: Attorney, lead NOT unlocked → 403 ──")
    uid = _create_test_user(
        f"test_locked_{uuid.uuid4().hex[:8]}@verifuse-test.internal",
        role="approved_attorney",
        attorney_status="VERIFIED",
        credits=10,
    )
    token = _get_token_direct(uid)
    if not token:
        print(f"    [{WARN}] Could not generate token — skipping CASE D")
        _cleanup_test_user(uid)
        return
    try:
        # Intentionally do NOT call _unlock_lead_for_user
        r = post_heir_letter(token, LEAD_ID)
        check("Locked lead → 403", r.status_code == 403, f"got {r.status_code}")
        if r.status_code == 403:
            check("403 detail mentions unlock", "unlock" in r.text.lower(),
                  r.text[:120])
        # Confirm credits were NOT deducted (no deduction before unlock check)
        bal = _ledger_balance(uid)
        check("Credits unchanged after 403 (locked)", bal == 10, f"balance={bal}")
    finally:
        _cleanup_test_user(uid)


def test_case_c_no_credits() -> None:
    print("\n── CASE C: Attorney, unlocked, 0 credits → 402 ──")
    uid = _create_test_user(
        f"test_nocred_{uuid.uuid4().hex[:8]}@verifuse-test.internal",
        role="approved_attorney",
        attorney_status="VERIFIED",
        credits=0,  # ← zero credits
    )
    token = _get_token_direct(uid)
    if not token:
        print(f"    [{WARN}] Could not generate token — skipping CASE C")
        _cleanup_test_user(uid)
        return
    try:
        _unlock_lead_for_user(uid, LEAD_ID)
        r = post_heir_letter(token, LEAD_ID)
        check("No credits → 402", r.status_code == 402, f"got {r.status_code}")
        if r.status_code == 402:
            check("402 detail mentions credits", "credit" in r.text.lower(),
                  r.text[:120])
        # Confirm no journal rows written
        j_rows = _journal_rows_for_user(uid)
        check("No journal rows written on 402", j_rows == 0, f"journal_rows={j_rows}")
        t_rows = _transactions_count(uid)
        check("No transaction rows written on 402", t_rows == 0, f"txn_rows={t_rows}")
    finally:
        _cleanup_test_user(uid)


def test_case_b_attorney_with_credits() -> None:
    print("\n── CASE B: Attorney, unlocked, 10 credits → 200 + credit deduction ──")
    uid = _create_test_user(
        f"test_atty_{uuid.uuid4().hex[:8]}@verifuse-test.internal",
        role="approved_attorney",
        attorney_status="VERIFIED",
        credits=10,
    )
    token = _get_token_direct(uid)
    if not token:
        print(f"    [{WARN}] Could not generate token — skipping CASE B")
        _cleanup_test_user(uid)
        return
    try:
        _unlock_lead_for_user(uid, LEAD_ID)
        bal_before = _ledger_balance(uid)
        check("Balance before call = 10", bal_before == 10, f"bal={bal_before}")

        r = post_heir_letter(token, LEAD_ID)
        check("Attorney with credits → 200", r.status_code == 200,
              f"got {r.status_code} body={r.text[:200] if r.status_code != 200 else ''}")

        if r.status_code == 200:
            check("Response is PDF (content-type)",
                  "application/pdf" in r.headers.get("content-type", ""),
                  r.headers.get("content-type"))
            check("PDF has content (%PDF header)",
                  r.content[:4] == b"%PDF",
                  f"first_bytes={r.content[:8]!r}")
            check("Content-Disposition present",
                  "attachment" in r.headers.get("content-disposition", "").lower(),
                  r.headers.get("content-disposition"))
            check("Cache-Control: no-store",
                  "no-store" in r.headers.get("cache-control", "").lower(),
                  r.headers.get("cache-control"))

        # Credit deduction: 10 - 5 = 5
        bal_after = _ledger_balance(uid)
        check("Credits deducted: 10 → 5", bal_after == 5, f"bal_after={bal_after}")

        # unlock_spend_journal rows written
        j_rows = _journal_rows_for_user(uid)
        check("unlock_spend_journal row(s) written", j_rows >= 1, f"journal_rows={j_rows}")

        # transactions row written
        t_rows = _transactions_count(uid, "premium_dossier")
        check("transactions row written (premium_dossier)", t_rows == 1, f"txn_rows={t_rows}")

        # audit_log row written
        conn = _db()
        try:
            a_row = conn.execute(
                "SELECT action FROM audit_log WHERE user_id=? AND action='heir_letter_generated'",
                [uid],
            ).fetchone()
        finally:
            conn.close()
        check("audit_log row written", a_row is not None, str(a_row))

    finally:
        _cleanup_test_user(uid)


def test_case_b2_partial_credits() -> None:
    """Edge case: user has exactly 5 credits (boundary condition)."""
    print("\n── CASE B2: Exactly 5 credits (boundary) → 200, 0 credits left ──")
    uid = _create_test_user(
        f"test_exact5_{uuid.uuid4().hex[:8]}@verifuse-test.internal",
        role="approved_attorney",
        attorney_status="VERIFIED",
        credits=5,
    )
    token = _get_token_direct(uid)
    if not token:
        print(f"    [{WARN}] Could not generate token — skipping CASE B2")
        _cleanup_test_user(uid)
        return
    try:
        _unlock_lead_for_user(uid, LEAD_ID)
        r = post_heir_letter(token, LEAD_ID)
        check("Exactly 5 credits → 200", r.status_code == 200,
              f"got {r.status_code}")
        bal_after = _ledger_balance(uid)
        check("0 credits remaining after spend", bal_after == 0, f"bal={bal_after}")
    finally:
        _cleanup_test_user(uid)


def test_case_b3_four_credits() -> None:
    """Edge case: 4 credits (one short of required 5)."""
    print("\n── CASE B3: 4 credits (one short) → 402, balance unchanged ──")
    uid = _create_test_user(
        f"test_4cred_{uuid.uuid4().hex[:8]}@verifuse-test.internal",
        role="approved_attorney",
        attorney_status="VERIFIED",
        credits=4,
    )
    token = _get_token_direct(uid)
    if not token:
        print(f"    [{WARN}] Could not generate token — skipping CASE B3")
        _cleanup_test_user(uid)
        return
    try:
        _unlock_lead_for_user(uid, LEAD_ID)
        r = post_heir_letter(token, LEAD_ID)
        check("4 credits → 402", r.status_code == 402, f"got {r.status_code}")
        bal_after = _ledger_balance(uid)
        check("Balance unchanged after 402 (4 stays 4)", bal_after == 4,
              f"bal={bal_after}")
        j_rows = _journal_rows_for_user(uid)
        check("No journal rows on insufficient 402", j_rows == 0, f"journal_rows={j_rows}")
    finally:
        _cleanup_test_user(uid)


def test_case_a_admin() -> None:
    print("\n── CASE A: Admin token → 200, NO credit deduction ──")
    admin_token = _get_token(ADMIN_EMAIL, ADMIN_PASSWORD)
    if not admin_token:
        # Try direct token generation
        conn = _db()
        try:
            row = conn.execute(
                "SELECT user_id FROM users WHERE email=?", [ADMIN_EMAIL]
            ).fetchone()
        finally:
            conn.close()
        if row:
            admin_token = _get_token_direct(row["user_id"])

    if not admin_token:
        print(f"    [{WARN}] Cannot get admin token — skipping CASE A")
        return

    # Get admin user_id for balance check
    conn = _db()
    try:
        admin_row = conn.execute(
            "SELECT user_id FROM users WHERE email=?", [ADMIN_EMAIL]
        ).fetchone()
        admin_uid = admin_row["user_id"] if admin_row else None
    finally:
        conn.close()

    bal_before = _ledger_balance(admin_uid) if admin_uid else -1
    r = post_heir_letter(admin_token, LEAD_ID)
    check("Admin → 200", r.status_code == 200,
          f"got {r.status_code} body={r.text[:200] if r.status_code != 200 else ''}")

    if r.status_code == 200:
        check("Admin PDF content-type", "application/pdf" in r.headers.get("content-type", ""),
              r.headers.get("content-type"))
        check("Admin PDF %PDF header", r.content[:4] == b"%PDF",
              f"first={r.content[:8]!r}")

    if admin_uid and bal_before >= 0:
        bal_after = _ledger_balance(admin_uid)
        check("Admin: no credits deducted",
              bal_after == bal_before,
              f"before={bal_before} after={bal_after}")

    # Also confirm no premium_dossier transaction written for admin
    if admin_uid:
        # Count how many before (may be non-zero from prior runs)
        conn = _db()
        try:
            t_after = conn.execute(
                "SELECT COUNT(*) FROM transactions WHERE user_id=? AND type='premium_dossier'",
                [admin_uid],
            ).fetchone()[0]
        finally:
            conn.close()
        check("Admin: no premium_dossier transaction written", t_after == 0,
              f"txn_rows={t_after}")


def test_case_g_404_lead() -> None:
    print("\n── CASE G: Nonexistent lead → 404 ──")
    admin_token = _get_token(ADMIN_EMAIL, ADMIN_PASSWORD)
    if not admin_token:
        conn = _db()
        try:
            row = conn.execute("SELECT user_id FROM users WHERE email=?",
                               [ADMIN_EMAIL]).fetchone()
        finally:
            conn.close()
        if row:
            admin_token = _get_token_direct(row["user_id"])
    if not admin_token:
        print(f"    [{WARN}] Cannot get admin token — skipping CASE G")
        return
    r = requests.post(
        f"{API}/api/assets/FORECLOSURE:CO:FAKE:ZZZZZ9999/heir-letter",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10,
    )
    check("Nonexistent lead → 404", r.status_code == 404, f"got {r.status_code}")


# ════════════════════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════════════════════

def main() -> None:
    print("=" * 66)
    print("  VeriFuse — Heir Letter Endpoint Integration Tests")
    print(f"  API:  {API}")
    print(f"  DB:   {DB_PATH}")
    print(f"  Lead: {LEAD_ID}")
    print("=" * 66)

    # Quick API liveness check
    try:
        health = requests.get(f"{API}/health", timeout=5)
        if health.status_code != 200:
            print(f"\n[{FAIL}] API not responding at {API} — start with: bin/vf api-start")
            sys.exit(1)
        print(f"  API health: OK ({health.json()})")
    except Exception as e:
        print(f"\n[{FAIL}] Cannot reach API at {API}: {e}")
        print("  Start the API: bin/vf api-start (or: uvicorn verifuse_v2.server.api:app --port 8000)")
        sys.exit(1)

    # Run all test cases
    test_case_f_no_token()
    test_case_e_public_role(None)
    test_case_d_locked_lead()
    test_case_c_no_credits()
    test_case_b_attorney_with_credits()
    test_case_b2_partial_credits()
    test_case_b3_four_credits()
    test_case_a_admin()
    test_case_g_404_lead()

    # Summary
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    total = len(results)
    print(f"\n{'=' * 66}")
    print(f"  Results: {passed}/{total} PASS, {failed}/{total} FAIL")
    print(f"{'=' * 66}")

    if failed:
        print("\nFailed checks:")
        for name, ok, detail in results:
            if not ok:
                print(f"  [{FAIL}] {name}" + (f" — {detail}" if detail else ""))
        sys.exit(1)


if __name__ == "__main__":
    main()
