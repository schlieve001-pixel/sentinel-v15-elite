"""
VERIFUSE V2 — Titanium API (leads-native)

All queries hit the `leads` table via VERIFUSE_DB_PATH.
SafeAsset fields are Optional[float] = None (Black Screen fix).

Gates:
  RESTRICTED → is_verified_attorney + (OPERATOR or SOVEREIGN)
  ACTIONABLE → any paid user with credits
  EXPIRED    → locked, cannot unlock

Atomic: credit deduction uses BEGIN IMMEDIATE.

Sprint 11.5: Preview endpoint, zombie/reject filters, email verification,
mobile-safe download headers, Stripe guard.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import hmac
import json
import logging
import os
import random
import sqlite3
import string
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# ── Fail-fast: VERIFUSE_DB_PATH ────────────────────────────────────

VERIFUSE_DB_PATH = os.environ.get("VERIFUSE_DB_PATH")
if not VERIFUSE_DB_PATH:
    raise RuntimeError(
        "FATAL: VERIFUSE_DB_PATH not set. "
        "export VERIFUSE_DB_PATH=/path/to/verifuse_v2.db"
    )

# ── Vault root (evidence document storage) — Gate 7 ─────────────────
VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", "/var/lib/verifuse/vault/govsoft"))

# ── API Key for machine-to-machine auth (admin/scraper endpoints) ────
VERIFUSE_API_KEY = os.environ.get("VERIFUSE_API_KEY", "")

# ── Stripe guard (mode-aware key selection) ──────────────────────────
STRIPE_MODE = (os.environ.get("STRIPE_MODE") or "test").lower()
if STRIPE_MODE == "live":
    STRIPE_SECRET_KEY = os.environ.get("STRIPE_LIVE_SECRET_KEY") or os.environ.get("STRIPE_SECRET_KEY")
    STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_LIVE_PUBLISHABLE_KEY") or ""
    STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_LIVE_WEBHOOK_SECRET") or os.environ.get("STRIPE_WEBHOOK_SECRET")
else:
    STRIPE_SECRET_KEY = os.environ.get("STRIPE_TEST_SECRET_KEY") or os.environ.get("STRIPE_SECRET_KEY")
    STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_TEST_PUBLISHABLE_KEY") or ""
    STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_TEST_WEBHOOK_SECRET") or os.environ.get("STRIPE_WEBHOOK_SECRET")

# ── HMAC Secret for preview_key (fail-fast) ─────────────────────────
_PREVIEW_HMAC_SECRET = os.environ.get("PREVIEW_HMAC_SECRET") or os.environ.get("VERIFUSE_JWT_SECRET")
if not _PREVIEW_HMAC_SECRET:
    import sys
    logging.basicConfig(level=logging.CRITICAL)
    logging.getLogger(__name__).critical(
        "FATAL: No PREVIEW_HMAC_SECRET or VERIFUSE_JWT_SECRET set. "
        "Preview keys will be unstable across deploys."
    )
    raise RuntimeError("HMAC secret required — set PREVIEW_HMAC_SECRET or VERIFUSE_JWT_SECRET")

log = logging.getLogger(__name__)

# ── Dev environment flag (NEVER true in production) ──────────────────
# Set VERIFUSE_ENV=development in .env to enable dev-only bypasses.
# Production must not set this variable (defaults to non-development).
_IS_DEV = os.environ.get("VERIFUSE_ENV", "production").lower() == "development"

# ── Pricing & entitlements (canonical source) ─────────────────────────
from verifuse_v2.server.pricing import (
    FOUNDERS_MAX_SLOTS,
    STARTER_PACK,
    build_price_map,
    get_monthly_credits,
    get_daily_limit,
)

EXPECTED_CURRENCY = "usd"
EXPECTED_LIVEMODE = STRIPE_MODE == "live"
_price_prefix = "STRIPE_LIVE_PRICE_" if STRIPE_MODE == "live" else "STRIPE_TEST_PRICE_"

# Map Stripe price_id → {tier, monthly_credits, kind}
# Built at startup via build_price_map()
_PRICE_MAP: dict[str, dict] = {}

# ── Build ID (git short hash at import time) ─────────────────────────
_BUILD_ID = "dev"
try:
    import subprocess
    _BUILD_ID = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        stderr=subprocess.DEVNULL,
    ).decode().strip() or "dev"
except Exception:
    pass

# ── Database connection (strict VERIFUSE_DB_PATH) ───────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(VERIFUSE_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


# ── ThreadPoolExecutor for non-blocking DB access ───────────────────

DB_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=min(32, (os.cpu_count() or 1) * 4),
    thread_name_prefix="vf-db",
)

# ── ThreadPoolExecutor for CPU-bound PDF generation ──────────────────
# Separate from DB_EXECUTOR so PDF renders never block DB threads.

PDF_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=max(2, (os.cpu_count() or 2) // 2),
    thread_name_prefix="vf-pdf",
)


def _thread_conn() -> sqlite3.Connection:
    """Open a hardened SQLite connection for use inside DB_EXECUTOR threads."""
    conn = sqlite3.connect(VERIFUSE_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        result = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        if result != "wal":
            log.warning("[db] journal_mode=WAL not set — got %r (read-only or in-memory?)", result)
    except Exception as exc:
        log.warning("[db] Failed to set WAL mode: %s", exc)
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


async def _run_in_db(fn):
    """Run a synchronous callable in DB_EXECUTOR, off the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(DB_EXECUTOR, fn)


# ── Module-level compat flags (set at startup) ────────────────────────
# True once asset_unlocks / lead_unlocks tables are confirmed present.
_USE_ASSET_UNLOCKS_FOR_LOOKUP: bool = False
_HAS_LEAD_UNLOCKS: bool = False


# ── Epoch + FIFO ledger helpers ──────────────────────────────────────

def _epoch_now() -> int:
    """Current UTC time as a Unix epoch integer."""
    return int(datetime.now(timezone.utc).timestamp())


def _ledger_balance(conn: sqlite3.Connection, user_id: str) -> int:
    """Sum qty_remaining of all non-expired ledger entries for user."""
    row = conn.execute(
        "SELECT COALESCE(SUM(qty_remaining), 0) FROM unlock_ledger_entries "
        "WHERE user_id = ? AND (expires_ts IS NULL OR expires_ts > ?)",
        [user_id, _epoch_now()],
    ).fetchone()
    return int(row[0])


def _fifo_spend(
    conn: sqlite3.Connection,
    user_id: str,
    cost: int,
) -> list[dict] | None:
    """Deduct `cost` credits using FIFO ordering (expires soonest first).

    SAFETY: checks total with SUM() BEFORE any UPDATE.
    Never partially decrements — atomic or returns None.

    SQLite compat: ORDER BY (expires_ts IS NULL) ASC places NULLs last
    without relying on NULLS LAST (unsupported in older SQLite).

    Returns: list of {entry_id, spent} dicts on success, None if insufficient.
    """
    now = _epoch_now()

    # Pre-flight: verify total before touching any rows
    total_row = conn.execute(
        "SELECT COALESCE(SUM(qty_remaining), 0) FROM unlock_ledger_entries "
        "WHERE user_id = ? AND qty_remaining > 0 AND (expires_ts IS NULL OR expires_ts > ?)",
        [user_id, now],
    ).fetchone()
    if int(total_row[0]) < cost:
        return None  # Insufficient — no writes made

    # Fetch ordered entries (expires soonest, NULLs last, oldest purchase within bucket)
    entries = conn.execute(
        "SELECT id, qty_remaining FROM unlock_ledger_entries "
        "WHERE user_id = ? AND qty_remaining > 0 AND (expires_ts IS NULL OR expires_ts > ?) "
        "ORDER BY (expires_ts IS NULL) ASC, expires_ts ASC, purchased_ts ASC",
        [user_id, now],
    ).fetchall()

    # Deduct — total pre-verified so loop always succeeds
    debits: list[dict] = []
    remaining = cost
    for e in entries:
        if remaining <= 0:
            break
        spend = min(e["qty_remaining"], remaining)
        conn.execute(
            "UPDATE unlock_ledger_entries SET qty_remaining = qty_remaining - ? WHERE id = ?",
            [spend, e["id"]],
        )
        debits.append({"entry_id": e["id"], "spent": spend})
        remaining -= spend
    return debits


def _audit_log(conn: sqlite3.Connection, user_id: str, action: str, meta: dict = None, ip: str = "") -> None:
    """Insert an audit log entry. Never logs PII/tokens/passwords."""
    import uuid
    meta_json = json.dumps(meta) if meta else None
    conn.execute(
        "INSERT INTO audit_log (id, user_id, action, meta_json, created_at, ip) "
        "VALUES (?, ?, ?, ?, datetime('now'), ?)",
        [str(uuid.uuid4()), user_id, action, meta_json, ip],
    )


def _get_client_ip(request: Request) -> str:
    """Extract client IP from X-Forwarded-For or direct connection."""
    ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not ip and request.client:
        ip = request.client.host
    return ip


def _purge_stale_rate_limits() -> None:
    """Purge rate_limits entries older than 24 hours. Called periodically."""
    try:
        conn = _get_conn()
        conn.execute("DELETE FROM rate_limits WHERE ts < (strftime('%s','now') - 86400)")
        conn.commit()
        conn.close()
    except Exception:
        pass


def _try_founders_redemption(user_id: str) -> bool:
    """Race-safe founders pricing redemption. Returns True if slot claimed."""
    conn = _get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        count = conn.execute("SELECT COUNT(*) FROM founders_redemptions").fetchone()[0]
        if count >= FOUNDERS_MAX_SLOTS:
            conn.execute("ROLLBACK")
            return False
        # Check if already redeemed
        existing = conn.execute(
            "SELECT 1 FROM founders_redemptions WHERE user_id = ?", [user_id]
        ).fetchone()
        if existing:
            conn.execute("ROLLBACK")
            return True  # Already has it
        conn.execute(
            "INSERT INTO founders_redemptions (user_id, redeemed_at) VALUES (?, datetime('now'))",
            [user_id],
        )
        conn.execute(
            "UPDATE users SET founders_pricing = 1 WHERE user_id = ?", [user_id]
        )
        conn.execute("COMMIT")
        log.info("Founders slot claimed: user=%s (slot %d/%d)", user_id, count + 1, FOUNDERS_MAX_SLOTS)
        return True
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        return False
    finally:
        conn.close()


def _send_email(to: str, subject: str, body: str) -> None:
    """Send email via SES → SMTP → log fallback.

    Reads VERIFUSE_EMAIL_MODE env var:
      ses  — AWS SES (primary); falls through to SMTP on failure
      smtp — SMTP directly; falls through to log on failure
      log  — log only (default / dev)

    Always sends from support@verifuse.tech in us-west-2.
    """
    FROM = "support@verifuse.tech"
    REGION = os.environ.get("AWS_REGION", "us-west-2")
    mode = os.environ.get("VERIFUSE_EMAIL_MODE", "log").lower()

    if mode == "ses":
        try:
            import boto3
            boto3.client("ses", region_name=REGION).send_email(
                Source=FROM,
                Destination={"ToAddresses": [to]},
                Message={
                    "Subject": {"Data": subject},
                    "Body": {"Text": {"Data": body}},
                },
            )
            return
        except Exception as e:
            log.error("SES send failed: %s — falling back to SMTP", e)

    if mode in ("ses", "smtp"):
        try:
            import smtplib
            from email.mime.text import MIMEText
            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = FROM
            msg["To"] = to
            smtp_host = os.environ.get("SMTP_HOST", "")
            smtp_port = int(os.environ.get("SMTP_PORT", 587))
            smtp_user = os.environ.get("SMTP_USER", "")
            smtp_pass = os.environ.get("SMTP_PASS", "")
            if not smtp_host:
                raise RuntimeError("SMTP_HOST not configured")
            with smtplib.SMTP(smtp_host, smtp_port) as s:
                s.starttls()
                if smtp_user:
                    s.login(smtp_user, smtp_pass)
                s.send_message(msg)
            return
        except Exception as e:
            log.error("SMTP send failed: %s — falling back to log", e)

    log.info("EMAIL [%s → %s] %s | %s", FROM, to, subject, body[:300])


# ── Evidence document family labels (display names) ─────────────────
DOC_FAMILY_LABELS: dict[str, str] = {
    "OB":      "Overbid Voucher",
    "BID":     "Bid Sheet",
    "COP":     "Certificate of Purchase",
    "NED":     "Notice of Election to Defend",
    "PTD":     "Partial Tax Deed",
    "NOTICE":  "Notice Document",
    "INVOICE": "Financial Invoice",
    "OTHER":   "Supporting Document",
}

# ── SafeAsset model (NULL-safe: every numeric field is Optional) ────

class SafeAsset(BaseModel):
    """Public projection. All floats are Optional = None (Black Screen fix).

    Field names MUST match the frontend Lead interface in api.ts.
    """
    asset_id: Optional[str] = None
    county: Optional[str] = None
    state: Optional[str] = "CO"
    case_number: Optional[str] = None
    asset_type: Optional[str] = "FORECLOSURE_SURPLUS"
    estimated_surplus: Optional[float] = None
    surplus_verified: Optional[bool] = None
    data_grade: Optional[str] = None
    record_class: Optional[str] = None
    sale_date: Optional[str] = None
    claim_deadline: Optional[str] = None
    days_to_claim: Optional[int] = None
    deadline_passed: Optional[bool] = None
    # C.R.S. § 38-38-111 restriction period
    restriction_status: Optional[str] = None
    restriction_end_date: Optional[str] = None
    blackout_end_date: Optional[str] = None
    days_until_actionable: Optional[int] = None
    address_hint: Optional[str] = None
    owner_img: Optional[str] = None
    completeness_score: Optional[float] = None
    confidence_score: Optional[float] = None
    data_age_days: Optional[int] = None
    preview_key: Optional[str] = None    # HMAC key for sample dossier (null if not eligible)
    unlocked_by_me: bool = False         # True if requesting user has unlocked this lead
    registry_asset_id: Optional[str] = None  # Canonical FORECLOSURE:CO:{county}:{case} key
    # Gate 7 equity resolution fields (populated when equity_resolution row exists)
    gross_surplus_cents: Optional[int] = None
    net_owner_equity_cents: Optional[int] = None
    classification: Optional[str] = None
    # Domain model: enriched status fields
    sale_status: Optional[str] = None      # PRE_SALE | POST_SALE_HOLDING | ACTIONABLE | ESCROW_ENDED | UNKNOWN
    ready_to_file: Optional[bool] = None   # True only when all required fields present + ACTIONABLE
    grade_reasons: Optional[list] = None   # Human-readable explanations of current grade


class FullAsset(SafeAsset):
    """Unlocked projection with PII."""
    owner_name: Optional[str] = None
    property_address: Optional[str] = None
    winning_bid: Optional[float] = None
    total_debt: Optional[float] = None
    total_indebtedness: Optional[float] = None
    surplus_amount: Optional[float] = None
    overbid_amount: Optional[float] = None
    days_remaining: Optional[int] = None
    statute_window: Optional[str] = None
    recorder_link: Optional[str] = None
    source_doc_count: Optional[int] = None


class PreviewLead(BaseModel):
    """Public preview — ZERO PII, ZERO internal IDs, ZERO exact amounts.
    Returns only banded surplus to enforce the monetization wall.
    """
    preview_key: str  # HMAC hash for React key ONLY — not usable for lookups
    county: Optional[str] = None
    sale_month: Optional[str] = None  # YYYY-MM only (anti-triangulation)
    data_grade: Optional[str] = None
    surplus_band: Optional[str] = None  # Banded range — never exact amount


# ── Helpers ──────────────────────────────────────────────────────────

# C.R.S. § 38-38-111: Trustee holds for SIX CALENDAR MONTHS (not 180 days).
# Using relativedelta for legally precise calendar month arithmetic.
try:
    from dateutil.relativedelta import relativedelta
    RESTRICTION_DELTA = relativedelta(months=6)
except ImportError:
    # Fallback if dateutil not installed (182 days ≈ 6 months)
    RESTRICTION_DELTA = timedelta(days=182)


def _compute_restriction_end(sale_date_str: str) -> date | None:
    """Compute the end of the 6 calendar month restriction period."""
    try:
        sale_dt = date.fromisoformat(str(sale_date_str)[:10])
        return sale_dt + RESTRICTION_DELTA
    except (ValueError, TypeError):
        return None


def _compute_status(row: dict) -> str:
    """Dynamic status from UTC dates. NEVER stored."""
    today = datetime.now(timezone.utc).date()

    deadline = row.get("claim_deadline")
    if deadline:
        try:
            if today > date.fromisoformat(deadline):
                return "EXPIRED"
        except (ValueError, TypeError):
            pass

    sale = row.get("sale_date")
    if sale:
        restriction_end = _compute_restriction_end(sale)
        if restriction_end and today < restriction_end:
            return "RESTRICTED"
        if restriction_end:
            return "ACTIONABLE"

    return "UNKNOWN"


def _compute_sale_status(row: dict) -> str:
    """Extended status distinguishing pre-sale from post-sale phases."""
    today = datetime.now(timezone.utc).date()
    sale = row.get("sale_date")
    if not sale:
        return "PRE_SALE"
    try:
        sale_dt = date.fromisoformat(str(sale)[:10])
    except (ValueError, TypeError):
        return "UNKNOWN"
    if sale_dt > today:
        return "PRE_SALE"
    restriction_end = _compute_restriction_end(sale)
    deadline = row.get("claim_deadline")
    if deadline:
        try:
            if today > date.fromisoformat(str(deadline)[:10]):
                return "ESCROW_ENDED"
        except (ValueError, TypeError):
            pass
    if restriction_end and today < restriction_end:
        return "POST_SALE_HOLDING"
    return "ACTIONABLE"


def _compute_confidence(row: dict) -> float:
    """Compute a 0.0–1.0 confidence score from available fields.
    Score is capped at 0.50 when total_debt is absent (unverified math)."""
    pts = 0
    if row.get("sale_date"):
        pts += 20
    surplus = _safe_float(row.get("overbid_amount")) or _safe_float(row.get("surplus_amount")) or _safe_float(row.get("estimated_surplus"))
    if surplus and surplus > 0:
        pts += 20
    debt = _safe_float(row.get("total_debt"))
    if debt and debt > 0:
        pts += 30
    if row.get("property_address"):
        pts += 15
    if row.get("owner_name"):
        pts += 15
    if not debt or debt <= 0:
        return min(pts, 50) / 100.0
    return min(pts, 100) / 100.0


def _compute_ready_to_file(row: dict) -> bool:
    """True only when all required fields are present AND status is ACTIONABLE."""
    required = [
        row.get("sale_date"),
        _safe_float(row.get("overbid_amount")) or _safe_float(row.get("surplus_amount")),
        row.get("owner_name"),
        row.get("property_address"),
    ]
    if any(not v for v in required):
        return False
    return _compute_status(row) == "ACTIONABLE"


def _compute_grade_reasons(row: dict) -> list:
    """Human-readable list explaining why a lead has its current grade."""
    reasons = []
    if not row.get("sale_date"):
        reasons.append("Sale date not available")
    debt = _safe_float(row.get("total_debt"))
    if not debt or debt <= 0:
        reasons.append("Total indebtedness not extracted — confidence capped at 50%")
    if not row.get("owner_name"):
        reasons.append("Owner name not retrieved")
    if not row.get("property_address"):
        reasons.append("Property address not retrieved")
    return reasons


def _assert_ready_to_file(row: dict) -> None:
    """Raise HTTP 422 if required fields are missing for filing."""
    missing = []
    if not row.get("owner_name"):
        missing.append("owner_name")
    if not row.get("property_address"):
        missing.append("property_address")
    if not row.get("sale_date"):
        missing.append("sale_date")
    if not (_safe_float(row.get("overbid_amount")) or _safe_float(row.get("surplus_amount"))):
        missing.append("surplus_amount")
    if missing:
        raise HTTPException(422, detail=f"Missing required fields: {', '.join(missing)}")


def _safe_float(val) -> Optional[float]:
    """Safely convert DB value to float, returning None for NULL/invalid."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _extract_city(address: Optional[str], county: Optional[str]) -> str:
    if not address:
        return f"{county or 'CO'}, CO"
    parts = [p.strip() for p in address.split(",")]
    if len(parts) >= 2:
        return ", ".join(parts[-2:]).strip()
    return f"{county or 'CO'}, CO"


def _round_surplus(amount: Optional[float]) -> Optional[float]:
    if amount is None or amount <= 0:
        return 0.0
    return round(amount / 100) * 100


def is_preview_eligible(row: dict) -> bool:
    """Single source of truth for preview eligibility. Uses only raw DB fields."""
    surplus = _safe_float(row.get("estimated_surplus")) or _safe_float(row.get("surplus_amount")) or _safe_float(row.get("overbid_amount")) or 0.0
    if surplus <= 100:
        return False
    grade = (row.get("data_grade") or "").upper()
    if grade == "REJECT":
        return False
    # Expiration check — string-safe, FAIL-CLOSED on non-NULL unparseable
    deadline = row.get("claim_deadline")
    if deadline is not None:
        s = str(deadline).strip()
        if not s:
            return False  # Empty string/whitespace = unparseable = ineligible
        try:
            s = s.split("T")[0].split(" ")[0]  # Strip timestamps safely
            if datetime.now(timezone.utc).date() > date.fromisoformat(s):
                return False
        except (ValueError, TypeError):
            return False  # FAIL-CLOSED: unparseable = ineligible
    # NULL deadline = pending (eligible) — consistent with _EXPIRED_FILTER
    return True


def _compute_preview_key(row: dict) -> str:
    """HMAC-SHA256 preview key. Uses ONLY leads.id + secret. Stable across re-grading. 24 hex chars (96-bit)."""
    lead_id = row.get("id") or ""
    return hmac.new(
        _PREVIEW_HMAC_SECRET.encode(), lead_id.encode(), hashlib.sha256
    ).hexdigest()[:24]


def _row_to_safe(row: dict) -> dict:
    """Convert a leads row to SafeAsset dict. NULL-safe."""
    surplus = _safe_float(row.get("surplus_amount")) or _safe_float(row.get("estimated_surplus")) or _safe_float(row.get("overbid_amount")) or 0.0
    bid = _safe_float(row.get("winning_bid")) or 0.0
    debt = _safe_float(row.get("total_debt")) or 0.0
    conf = _compute_confidence(row)
    status = _compute_status(row)
    sale_status = _compute_sale_status(row)
    today = datetime.now(timezone.utc).date()

    # Claim deadline tracking
    days_to_claim = None
    deadline_passed = None
    deadline = row.get("claim_deadline")
    if deadline:
        try:
            dl = date.fromisoformat(deadline)
            days_to_claim = (dl - today).days
            deadline_passed = days_to_claim < 0
        except (ValueError, TypeError):
            pass

    # Restriction period tracking
    restriction_end = None
    days_until_actionable = None
    blackout_end = None
    sale = row.get("sale_date")
    if sale:
        restriction_end = _compute_restriction_end(sale)
        if restriction_end:
            days_until_actionable = (restriction_end - today).days if restriction_end > today else 0
            # Blackout: 2 years after transfer to State Treasurer (C.R.S. § 38-13-1304)
            try:
                blackout_end = restriction_end + timedelta(days=730)
            except Exception:
                pass

    # Data age
    data_age_days = None
    updated = row.get("updated_at")
    if updated:
        try:
            updated_dt = date.fromisoformat(str(updated)[:10])
            data_age_days = (today - updated_dt).days
        except (ValueError, TypeError):
            pass

    data_grade = (row.get("data_grade") or "").upper()
    # REJECT leads: zero out surplus so they never appear claimable
    if data_grade == "REJECT":
        surplus = 0.0
    verified = data_grade in ("GOLD", "SILVER") and conf >= 0.7

    pk = _compute_preview_key(row) if is_preview_eligible(row) else None
    ready = _compute_ready_to_file(row)
    grade_reasons = _compute_grade_reasons(row)

    return SafeAsset(
        asset_id=row.get("id"),
        county=row.get("county"),
        state="CO",
        case_number=row.get("case_number"),
        asset_type="FORECLOSURE_SURPLUS",
        estimated_surplus=_round_surplus(surplus),
        surplus_verified=verified,
        data_grade=row.get("data_grade"),
        record_class=row.get("record_class"),
        sale_date=sale,
        claim_deadline=deadline,
        days_to_claim=days_to_claim,
        deadline_passed=deadline_passed,
        restriction_status=status,
        restriction_end_date=restriction_end.isoformat() if restriction_end else None,
        blackout_end_date=blackout_end.isoformat() if blackout_end else None,
        days_until_actionable=max(0, days_until_actionable) if days_until_actionable is not None else None,
        address_hint=_extract_city(row.get("property_address"), row.get("county")),
        owner_img=None,
        completeness_score=_safe_float(row.get("completeness_score")),
        confidence_score=round(conf, 2),
        data_age_days=data_age_days,
        preview_key=pk,
        # registry_asset_id: derived from county + case_number if both present
        registry_asset_id=(
            f"FORECLOSURE:CO:{row['county'].upper()}:{row['case_number']}"
            if row.get("county") and row.get("case_number") else None
        ),
        sale_status=sale_status,
        ready_to_file=ready,
        grade_reasons=grade_reasons,
    ).model_dump()


def _row_to_full(row: dict) -> dict:
    """Convert a leads row to FullAsset dict. NULL-safe."""
    safe = _row_to_safe(row)
    # Exact (unrounded) surplus for authenticated users — override the $100-rounded preview value
    exact_surplus = (
        _safe_float(row.get("surplus_amount"))
        or _safe_float(row.get("estimated_surplus"))
        or _safe_float(row.get("overbid_amount"))
        or 0.0
    )
    safe.update({
        "estimated_surplus": round(exact_surplus, 2),
        "owner_name": row.get("owner_name"),
        "property_address": row.get("property_address"),
        "winning_bid": _safe_float(row.get("winning_bid")),
        "total_debt": _safe_float(row.get("total_debt")),
        "total_indebtedness": _safe_float(row.get("total_debt")),
        "surplus_amount": _safe_float(row.get("surplus_amount")),
        "overbid_amount": _safe_float(row.get("overbid_amount")),
        "recorder_link": row.get("recorder_link"),
    })
    return safe


def surplus_band(cents: int) -> str:
    """Return human-readable surplus band for preview display. Never exposes exact amount."""
    dollars = cents / 100
    if dollars < 50_000:
        return "0–50K"
    if dollars < 150_000:
        return "50K–150K"
    if dollars < 500_000:
        return "150K–500K"
    return "500K+"


def _row_to_preview(row: dict) -> dict:
    """Convert a leads row to PreviewLead dict.
    ZERO PII, ZERO internal IDs, ZERO exact surplus amounts.
    """
    county = row.get("county")
    sale_date_raw = row.get("sale_date")
    data_grade = row.get("data_grade")
    # Convert DB dollars (float) → cents for banding
    surplus_dollars = _safe_float(row.get("estimated_surplus")) or _safe_float(row.get("surplus_amount")) or _safe_float(row.get("overbid_amount")) or 0.0
    surplus_cents = int(round(surplus_dollars * 100))

    # Truncate to YYYY-MM (anti-triangulation)
    sale_month = (sale_date_raw or "")[:7] if sale_date_raw else None

    # HMAC preview_key — stable, id-only salt (24 hex chars)
    preview_key = _compute_preview_key(row)
    # Pop id so it's not in output
    row.pop("id", None)

    return PreviewLead(
        preview_key=preview_key,
        county=county,
        sale_month=sale_month,
        data_grade=data_grade,
        surplus_band=surplus_band(surplus_cents),
    ).model_dump()


# ── Auth helpers (inline, using VERIFUSE_DB_PATH) ───────────────────

def _get_user_from_request(request: Request) -> Optional[dict]:
    """Extract JWT and look up user. Returns None if unauthenticated."""
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return None
    token = auth.split(" ", 1)[1]
    try:
        import jwt as pyjwt
        secret = os.getenv("VERIFUSE_JWT_SECRET", "vf2-dev-secret-change-in-production")
        payload = pyjwt.decode(token, secret, algorithms=["HS256"])
    except Exception:
        return None
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", [payload.get("sub")]).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _require_user(request: Request) -> dict:
    """Like _get_user but raises 401 if not authenticated."""
    user = _get_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account deactivated.")
    return user


def _is_verified_attorney(user: dict) -> bool:
    return user.get("attorney_status") == "VERIFIED"


def _is_admin(user: dict) -> bool:
    return bool(user.get("is_admin", 0))


def _is_simulating_user(request: Request, user: dict) -> bool:
    if not _is_admin(user):
        return False
    return request.headers.get("X-Verifuse-Simulate", "").lower() == "user"


def _effective_admin(user: dict, request: Request = None) -> bool:
    if not _is_admin(user):
        return False
    if request and _is_simulating_user(request, user):
        return False
    return True


def _require_api_key(request: Request) -> None:
    """Check x-verifuse-api-key header for admin/scraper endpoints."""
    if not VERIFUSE_API_KEY:
        return  # No key configured (dev mode)
    key = request.headers.get("x-verifuse-api-key", "")
    if key != VERIFUSE_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing API key.")


def _require_admin_or_api_key(request: Request) -> None:
    """Check API key OR JWT admin flag. For admin endpoints that accept either."""
    # Try API key first
    key = request.headers.get("x-verifuse-api-key", "")
    if VERIFUSE_API_KEY and key == VERIFUSE_API_KEY:
        return
    # Try JWT admin
    user = _get_user_from_request(request)
    if user and _is_admin(user):
        return
    raise HTTPException(status_code=403, detail="Admin access required.")


def _check_email_verified(user: dict, request: Request = None) -> None:
    """Check email verification. Raises 403 if not verified and not admin.

    DEV-ONLY BYPASS: In development (VERIFUSE_ENV=development), admin and
    sovereign roles are allowed through without email verification so that
    local testing is not blocked by SMTP. This bypass is compile-time gated
    by _IS_DEV — it is physically unreachable in production.
    """
    if _IS_DEV and user.get("role") in ("admin", "sovereign"):
        return
    if not user.get("email_verified") and not _effective_admin(user, request):
        raise HTTPException(
            status_code=403,
            detail="Please verify your email before unlocking leads.",
        )


# ── Rate Limiter ────────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])

# ── App ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="VeriFuse V2 — Titanium API",
    version="4.1.0",
    description="Colorado Surplus Intelligence Platform — Sprint 11.5",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://verifuse.tech",
        "https://www.verifuse.tech",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "x-verifuse-api-key", "X-Verifuse-Simulate"],
    expose_headers=["Content-Disposition"],
)


@app.middleware("http")
async def add_vary_header(request: Request, call_next):
    response = await call_next(request)
    existing = response.headers.get("Vary", "")
    existing_tokens = {t.strip().lower() for t in existing.split(",") if t.strip()}
    new_tokens = ["Authorization", "X-Verifuse-Simulate"]
    to_add = [t for t in new_tokens if t.lower() not in existing_tokens]
    if to_add:
        combined = f"{existing}, {', '.join(to_add)}" if existing else ", ".join(to_add)
        response.headers["Vary"] = combined
    return response


def _needs_nocache(path: str) -> bool:
    """Determine if a path requires no-cache headers.

    Uses exact match for the leads listing route and prefix match for
    subroutes to avoid false positives on unrelated paths.
    Must NOT apply to /api/webhooks/*, /api/health, /api/public-config.
    """
    return (
        path.startswith("/api/auth/")
        or path == "/api/leads"
        or path.startswith("/api/leads/")
        or path.startswith("/api/lead/")
        or path.startswith("/api/dossier/")
        or path.startswith("/api/assets/")
        or path.startswith("/api/evidence/")
    )


@app.middleware("http")
async def bfcache_hardening(request: Request, call_next):
    """Inject no-cache headers on authenticated/sensitive routes.

    Prevents BFCache from serving stale authenticated pages after logout.
    Explicitly excludes webhooks, health, and public-config endpoints.
    """
    response = await call_next(request)
    path = request.url.path
    if _needs_nocache(path) and not path.startswith("/api/webhooks/"):
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, proxy-revalidate"
        )
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# ── Legal constants ────────────────────────────────────────────────
LEGAL_DISCLAIMER = (
    "Forensic information service only. Not a debt collection or asset recovery agency. "
    "Subscriber responsible for all legal compliance under C.R.S. § 38-38-111."
)

UNLOCK_DISCLAIMER = (
    "I certify I am a licensed legal professional and understand "
    "C.R.S. § 38-38-111 restrictions on inducing compensation agreements "
    "during the six calendar month holding period."
)

# ── Preview SQL setup (dynamic column detection) ────────────────────
# Module-level cache — populated at startup
_LEADS_COLUMNS: set[str] = set()
_PREVIEW_SELECT = ""
_EXPIRED_FILTER = ""
_PREVIEW_LOOKUP: dict[str, str] = {}  # preview_key -> leads.id
_claim_deadline_expr = "NULL AS claim_deadline"  # Set at startup


# ── Startup ─────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    """Log DB identity on boot + detect lead columns for preview SQL + build preview lookup."""
    global _LEADS_COLUMNS, _PREVIEW_SELECT, _EXPIRED_FILTER, _PREVIEW_LOOKUP, _claim_deadline_expr
    global _USE_ASSET_UNLOCKS_FOR_LOOKUP, _HAS_LEAD_UNLOCKS

    db_path = Path(VERIFUSE_DB_PATH)
    inode = "N/A"
    sha = "N/A"
    rows = "N/A"
    try:
        stat = db_path.stat()
        inode = stat.st_ino
        sha = hashlib.sha256(db_path.read_bytes()[:8192]).hexdigest()[:16]
        conn = _get_conn()
        try:
            rows = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]

            # Detect columns
            col_rows = conn.execute("PRAGMA table_info(leads)").fetchall()
            _LEADS_COLUMNS = {r[1] for r in col_rows}
        finally:
            conn.close()
    except Exception as e:
        log.warning("Startup DB check: %s", e)

    # Build dynamic preview SELECT
    claim_deadline_expr = "claim_deadline" if "claim_deadline" in _LEADS_COLUMNS else "NULL AS claim_deadline"
    _claim_deadline_expr = claim_deadline_expr
    statute_status_expr = "statute_window_status" if "statute_window_status" in _LEADS_COLUMNS else "NULL AS statute_window_status"
    _PREVIEW_SELECT = (
        f"SELECT id, county, sale_date, data_grade, confidence_score, "
        f"ROUND(COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0), 2) as estimated_surplus, "
        f"{claim_deadline_expr}, {statute_status_expr} "
        f"FROM leads"
    )

    # Build expired filter
    if "statute_window_status" in _LEADS_COLUMNS:
        _EXPIRED_FILTER = " AND (statute_window_status IS NULL OR statute_window_status != 'EXPIRED')"
    elif "claim_deadline" in _LEADS_COLUMNS:
        _EXPIRED_FILTER = (
            " AND (claim_deadline IS NULL OR TRIM(claim_deadline) = '' "
            "OR date(NULLIF(TRIM(claim_deadline), '')) IS NULL "
            "OR date(NULLIF(TRIM(claim_deadline), '')) >= date('now'))"
        )
    else:
        _EXPIRED_FILTER = ""

    # Build preview lookup — O(1) preview_key -> leads.id
    _PREVIEW_LOOKUP = {}
    try:
        conn = _get_conn()
        try:
            q = ("SELECT id, "
                 "ROUND(COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0), 2) as estimated_surplus, "
                 f"data_grade, {claim_deadline_expr} "
                 "FROM leads WHERE COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0) > 100 "
                 f"AND data_grade != 'REJECT' {_EXPIRED_FILTER}")
            for row in conn.execute(q).fetchall():
                r = dict(row)
                if is_preview_eligible(r):  # STRICT gate — single source of truth
                    pk = _compute_preview_key(r)
                    _PREVIEW_LOOKUP[pk] = r["id"]
        finally:
            conn.close()
    except Exception as e:
        log.warning("Preview lookup build failed: %s", e)
    log.info("Preview lookup built: %d entries", len(_PREVIEW_LOOKUP))

    # Build PRICE_MAP
    global _PRICE_MAP
    _PRICE_MAP = build_price_map(STRIPE_MODE)
    log.info("PRICE_MAP built: %d entries (mode=%s)", len(_PRICE_MAP), STRIPE_MODE)

    # Detect vNEXT tables for compat flags
    try:
        chk = _get_conn()
        try:
            def _tbl(name: str) -> bool:
                return bool(chk.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [name]
                ).fetchone())
            _USE_ASSET_UNLOCKS_FOR_LOOKUP = _tbl("asset_unlocks")
            _HAS_LEAD_UNLOCKS = _tbl("lead_unlocks")
            ledger_count = chk.execute(
                "SELECT COUNT(*) FROM unlock_ledger_entries"
            ).fetchone()[0] if _tbl("unlock_ledger_entries") else 0
            registry_count = chk.execute(
                "SELECT COUNT(*) FROM asset_registry"
            ).fetchone()[0] if _tbl("asset_registry") else 0
            log.info(
                "vNEXT tables: asset_unlocks=%s lead_unlocks=%s ledger_entries=%d registry=%d",
                _USE_ASSET_UNLOCKS_FOR_LOOKUP, _HAS_LEAD_UNLOCKS, ledger_count, registry_count,
            )
        finally:
            chk.close()
    except Exception as e:
        log.warning("vNEXT table detection failed: %s", e)

    # Email mode
    email_mode = os.environ.get("VERIFUSE_EMAIL_MODE", "log").lower()
    log.info("Email mode: %s", email_mode)

    # Stripe status
    log.info("Stripe mode: %s | secret_key: %s", STRIPE_MODE, "set" if STRIPE_SECRET_KEY else "NOT SET")

    # Founders status
    try:
        conn2 = _get_conn()
        founders_count = conn2.execute("SELECT COUNT(*) FROM founders_redemptions").fetchone()[0]
        conn2.close()
        log.info("Founders: %d/%d slots claimed", founders_count, FOUNDERS_MAX_SLOTS)
    except Exception:
        pass

    log.info(
        "Omega v4.7 BOOT — DB: %s | inode: %s | sha256: %s | leads: %s | columns: %d | build: %s",
        VERIFUSE_DB_PATH, inode, sha, rows, len(_LEADS_COLUMNS), _BUILD_ID,
    )


@app.on_event("shutdown")
async def _shutdown_db_executor():
    DB_EXECUTOR.shutdown(wait=True)
    PDF_EXECUTOR.shutdown(wait=False)  # PDF renders are non-critical at exit


# ── Health ──────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Public health check — no internal data exposed."""
    return {"status": "ok"}


@app.get("/api/admin/health")
async def admin_health(request: Request):
    """Full health diagnostics — admin/API-key only."""
    _require_admin_or_api_key(request)
    conn = _get_conn()
    try:
        total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]

        # WAL status
        wal_info = conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        wal_pages = wal_info[1] if wal_info else 0

        # Scoreboard by data_grade
        scoreboard_rows = conn.execute("""
            SELECT data_grade,
                   COUNT(*) as lead_count,
                   COALESCE(SUM(COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0)), 0) as verified_surplus
            FROM leads
            GROUP BY data_grade
            ORDER BY verified_surplus DESC
        """).fetchall()
        scoreboard = [
            {
                "data_grade": r["data_grade"] or "UNGRADED",
                "lead_count": r["lead_count"],
                "verified_surplus": round(r["verified_surplus"], 2),
            }
            for r in scoreboard_rows
        ]

        # Quarantine count
        quarantined = 0
        try:
            quarantined = conn.execute(
                "SELECT COUNT(*) FROM leads_quarantine"
            ).fetchone()[0]
        except Exception:
            pass

        # Verified total
        verified_total = conn.execute(
            "SELECT COALESCE(SUM(COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0)), 0) FROM leads WHERE COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0) > 0"
        ).fetchone()[0]

    finally:
        conn.close()

    return {
        "status": "ok",
        "engine": "titanium_api_v4.1",
        "db": VERIFUSE_DB_PATH,
        "wal_pages": wal_pages,
        "total_leads": total,
        "scoreboard": scoreboard,
        "quarantined": quarantined,
        "verified_total": round(verified_total, 2),
        "legal_disclaimer": LEGAL_DISCLAIMER,
    }


# ── GET /api/public-config — Runtime configuration (no auth) ─────────

@app.get("/api/public-config")
async def public_config():
    """Public runtime config. No auth. No secrets. Cache-Control: no-store."""
    return JSONResponse(
        content={
            "stripe_mode": STRIPE_MODE,
            "stripe_publishable_key": STRIPE_PUBLISHABLE_KEY,
            "stripe_configured": bool(STRIPE_SECRET_KEY),
            "build_id": _BUILD_ID,
        },
        headers={"Cache-Control": "no-store"},
    )


# ── GET /api/preview/leads — Zero-PII public preview ────────────────

@app.get("/api/preview/leads")
@limiter.limit("30/minute")
async def preview_leads(
    request: Request,
    county: Optional[str] = Query(None),
    grade: Optional[str] = Query(None),
    limit: int = Query(25, ge=1, le=50),
    offset: int = Query(0, ge=0, le=500),
):
    """Public preview — no auth required. ZERO PII, ZERO internal IDs."""
    def _run():
        conn = _thread_conn()
        try:
            where = " WHERE COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0) > 100"
            where += " AND data_grade != 'REJECT'"
            where += _EXPIRED_FILTER
            params: list = []

            if county:
                where += " AND county = ?"
                params.append(county)
            if grade:
                where += " AND data_grade = ?"
                params.append(grade)

            # Total count (independent query for stable pagination)
            count_q = f"SELECT COUNT(*) FROM leads{where}"
            total = conn.execute(count_q, params).fetchone()[0]

            # Data query
            order = " ORDER BY COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0) DESC, sale_date DESC, county ASC, id ASC"
            data_q = f"{_PREVIEW_SELECT}{where}{order} LIMIT ? OFFSET ?"
            rows = conn.execute(data_q, params + [limit, offset]).fetchall()
        finally:
            conn.close()

        leads = []
        for row in rows:
            try:
                leads.append(_row_to_preview(dict(row)))
            except Exception as e:
                log.warning("Preview projection error: %s", e)
                continue

        return {
            "total": total,
            "count": len(leads),
            "leads": leads,
        }

    return await _run_in_db(_run)


# ── GET /api/leads — Paginated, NULL-safe ───────────────────────────

@app.get("/api/leads")
@limiter.limit("100/minute")
async def get_leads(
    request: Request,
    county: Optional[str] = Query(None),
    min_surplus: float = Query(0.0, ge=0),
    grade: Optional[str] = Query(None),
    include_expired: bool = Query(False),
    include_zombies: bool = Query(False),
    include_reject: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Return paginated leads as SafeAsset. Handles NULLs gracefully.

    Zombies (surplus<=100), REJECT, and EXPIRED hidden by default.
    """
    # Auth resolve happens here (sync, fast — header decode + small user lookup)
    user = _get_user_from_request(request)
    is_admin_user = user and _is_admin(user)
    is_eff_admin = user and _effective_admin(user, request)
    user_id = user["user_id"] if user else None

    def _run():
        conn = _thread_conn()
        try:
            where = " WHERE 1=1"
            params: list = []

            if not include_zombies:
                where += " AND COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0) > 100"
            if not include_reject or not is_admin_user:
                where += " AND data_grade != 'REJECT'"
            if county:
                where += " AND county = ?"
                params.append(county)
            if min_surplus > 0:
                where += " AND COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0) >= ?"
                params.append(min_surplus)
            if grade:
                where += " AND data_grade = ?"
                params.append(grade)

            # Count for pagination
            total = conn.execute(f"SELECT COUNT(*) FROM leads{where}", params).fetchone()[0]

            query = f"SELECT *, {_claim_deadline_expr} FROM leads{where}"
            query += " ORDER BY COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0) DESC, sale_date DESC, county ASC, id ASC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = conn.execute(query, params).fetchall()

            # Determine which leads the current user has unlocked (paginated set only)
            lead_ids = [dict(row)["id"] for row in rows]
            unlocked_ids: set[str] = set()
            if user_id and lead_ids:
                placeholders = ",".join(["?"] * len(lead_ids))
                u_rows = conn.execute(
                    f"SELECT lead_id FROM lead_unlocks WHERE user_id = ? AND lead_id IN ({placeholders})",
                    [user_id] + lead_ids
                ).fetchall()
                unlocked_ids = {r["lead_id"] for r in u_rows}

            leads = []
            for row in rows:
                try:
                    r = dict(row)
                    safe = _row_to_safe(r)
                    is_unlocked = r["id"] in unlocked_ids
                    safe["unlocked_by_me"] = is_unlocked
                    # Exact cents for admins and unlocked leads — override the $100-rounded preview value
                    if is_unlocked or is_eff_admin:
                        exact = (
                            _safe_float(r.get("surplus_amount"))
                            or _safe_float(r.get("estimated_surplus"))
                            or _safe_float(r.get("overbid_amount"))
                            or 0.0
                        )
                        safe["estimated_surplus"] = round(exact, 2)
                    # Mask PII for non-unlocked, non-admin users
                    if not is_unlocked and not is_eff_admin:
                        safe["case_number"] = None
                    # Filter out EXPIRED unless explicitly requested
                    if not include_expired and safe.get("restriction_status") == "EXPIRED":
                        continue
                    leads.append(safe)
                except Exception as e:
                    log.warning("Lead projection error: %s", e)
                    continue

            return {
                "count": len(leads),
                "total": total,
                "limit": limit,
                "offset": offset,
                "leads": leads,
            }
        finally:
            conn.close()

    return await _run_in_db(_run)


# ── POST /api/leads/{id}/unlock — FIFO Ledger + Double-Spend Safe ───

@app.post("/api/leads/{lead_id}/unlock")
@limiter.limit("30/minute")
async def unlock_lead(lead_id: str, request: Request):
    """Unlock a lead using the FIFO unlock ledger.

    Gates:
      EXPIRED    → 410
      role gate  → 403 if not approved_attorney and not admin
      RESTRICTED → requires approved_attorney + OPERATOR/SOVEREIGN tier
    Credit accounting:
      Phase 0: cost = 1 (hardcoded; get_credit_cost reserved for Phase 1)
      Double-spend guard: INSERT OR IGNORE asset_unlocks, check rowcount
      FIFO: spend soonest-expiring entries first (NULLs = never-expire last)
      Dispute proof: unlock_spend_journal row per ledger entry consumed
      Compat dual-write: lead_unlocks table (if present)
    """
    import uuid as _uuid_mod
    user = _require_user(request)
    _check_email_verified(user, request)
    ip = _get_client_ip(request)
    user_id = user["user_id"]

    # ── Role gate ────────────────────────────────────────────────
    role = user.get("role", "public")
    if role not in ("approved_attorney", "admin") and not _effective_admin(user, request):
        raise HTTPException(
            status_code=403,
            detail="Only verified attorneys can unlock leads.",
        )

    # ── Admin bypass (records unlock for audit, no credit spend) ─
    if _effective_admin(user, request):
        conn = _get_conn()
        try:
            row = conn.execute("SELECT * FROM leads WHERE id = ?", [lead_id]).fetchone()
        finally:
            conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Lead not found.")

        conn2 = _get_conn()
        try:
            conn2.execute("BEGIN IMMEDIATE")
            unlock_id = str(_uuid_mod.uuid4())
            now_epoch = _epoch_now()
            now_iso = datetime.now(timezone.utc).isoformat()
            conn2.execute(
                "INSERT OR IGNORE INTO asset_unlocks "
                "(id, user_id, asset_id, credits_spent, unlocked_at, ip_address, tier_at_unlock) "
                "VALUES (?, ?, ?, 0, ?, ?, ?)",
                [unlock_id, user_id, lead_id, now_epoch, ip, user.get("tier")],
            )
            if _HAS_LEAD_UNLOCKS:
                try:
                    conn2.execute(
                        "INSERT OR IGNORE INTO lead_unlocks "
                        "(user_id, lead_id, unlocked_at, ip_address, plan_tier) "
                        "VALUES (?, ?, ?, ?, ?)",
                        [user_id, lead_id, now_iso, ip, user.get("tier")],
                    )
                except sqlite3.IntegrityError:
                    pass
            _audit_log(conn2, user_id, "admin_unlock_bypass", {"lead_id": lead_id}, ip)
            conn2.execute("COMMIT")
        except Exception as e:
            try:
                conn2.execute("ROLLBACK")
            except Exception:
                pass
            log.warning("Admin unlock audit write failed: %s", e)
        finally:
            conn2.close()

        result = _row_to_full(dict(row))
        # Phase 5: source_doc_count for UI evidence lock
        try:
            _sc2 = _get_conn()
            _county2 = dict(row).get("county", "")
            _case2 = dict(row).get("case_number", "")
            _asset_key2 = f"FORECLOSURE:CO:{_county2.upper()}:{_case2.upper()}"
            _snap_ct2 = _sc2.execute("SELECT COUNT(*) FROM html_snapshots WHERE asset_id=?", [_asset_key2]).fetchone()[0]
            _pdf_ct2 = _sc2.execute("SELECT COUNT(*) FROM evidence_documents WHERE asset_id=?", [_asset_key2]).fetchone()[0]
            result["source_doc_count"] = _snap_ct2 + _pdf_ct2
            _sc2.close()
        except Exception:
            result["source_doc_count"] = 0
        result["ok"] = True
        result["credits_remaining"] = -1
        result["credits_spent"] = 0
        return result

    # ── Fetch lead ───────────────────────────────────────────────
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", [lead_id]).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found.")

    lead = dict(row)
    status = _compute_status(lead)

    if status == "EXPIRED" and not _effective_admin(user, request):
        raise HTTPException(
            status_code=410,
            detail="This lead has expired. Claim deadline has passed.",
        )

    if status == "RESTRICTED" and not _effective_admin(user, request):
        if not _is_verified_attorney(user):
            raise HTTPException(
                status_code=403,
                detail="RESTRICTED lead requires verified attorney status.",
            )
        if user.get("tier") not in ("operator", "sovereign"):
            raise HTTPException(
                status_code=403,
                detail="RESTRICTED lead requires OPERATOR or SOVEREIGN tier.",
            )

    # Phase 0: cost is always 1 (get_credit_cost reserved for Phase 1)
    cost = 1
    now_epoch = _epoch_now()
    now_iso = datetime.now(timezone.utc).isoformat()

    conn = _get_conn()
    credits_after = 0
    try:
        conn.execute("BEGIN IMMEDIATE")

        # ── Step 1: INSERT OR IGNORE asset_unlocks — double-spend guard ──
        unlock_id = str(_uuid_mod.uuid4())
        cursor = conn.execute(
            "INSERT OR IGNORE INTO asset_unlocks "
            "(id, user_id, asset_id, credits_spent, unlocked_at, ip_address, tier_at_unlock) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [unlock_id, user_id, lead_id, cost, now_epoch, ip, user.get("tier")],
        )

        if cursor.rowcount == 0:
            # Already unlocked — return full asset, no credit spend
            balance = _ledger_balance(conn, user_id)
            conn.execute("COMMIT")
            result = _row_to_full(lead)
            # Phase 5: source_doc_count for UI evidence lock
            try:
                _county3 = lead.get("county", "")
                _case3 = lead.get("case_number", "")
                _asset_key3 = f"FORECLOSURE:CO:{_county3.upper()}:{_case3.upper()}"
                _snap_ct3 = conn.execute("SELECT COUNT(*) FROM html_snapshots WHERE asset_id=?", [_asset_key3]).fetchone()[0]
                _pdf_ct3 = conn.execute("SELECT COUNT(*) FROM evidence_documents WHERE asset_id=?", [_asset_key3]).fetchone()[0]
                result["source_doc_count"] = _snap_ct3 + _pdf_ct3
            except Exception:
                result["source_doc_count"] = 0
            result["ok"] = True
            result["credits_remaining"] = balance
            result["credits_spent"] = 0
            return result

        # ── Step 2: FIFO spend — safe pre-checked ──────────────────────
        balance = _ledger_balance(conn, user_id)
        if balance < cost:
            conn.execute("ROLLBACK")
            raise HTTPException(
                status_code=402,
                detail=f"Insufficient credits. Need {cost}, have {balance}. Upgrade your plan.",
            )

        debits = _fifo_spend(conn, user_id, cost)
        if debits is None:
            conn.execute("ROLLBACK")
            raise HTTPException(
                status_code=402,
                detail=f"Insufficient credits. Need {cost}, have {balance}. Upgrade your plan.",
            )

        # ── Step 3: Spend journal (dispute-proof) ──────────────────────
        for d in debits:
            conn.execute(
                "INSERT INTO unlock_spend_journal "
                "(id, unlock_id, ledger_entry_id, credits_consumed) "
                "VALUES (?, ?, ?, ?)",
                [str(_uuid_mod.uuid4()), unlock_id, d["entry_id"], d["spent"]],
            )

        # ── Step 4: Compat dual-write to lead_unlocks ──────────────────
        if _HAS_LEAD_UNLOCKS:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO lead_unlocks "
                    "(user_id, lead_id, unlocked_at, ip_address, plan_tier) "
                    "VALUES (?, ?, ?, ?, ?)",
                    [user_id, lead_id, now_iso, ip, user.get("tier")],
                )
            except sqlite3.IntegrityError:
                pass

        # ── Step 5: Transaction record ──────────────────────────────────
        conn.execute(
            "INSERT INTO transactions "
            "(id, user_id, type, amount, credits, balance_after, idempotency_key, created_at) "
            "VALUES (?, ?, 'unlock', 0, ?, ?, ?, ?)",
            [str(_uuid_mod.uuid4()), user_id, -cost, balance - cost,
             f"unlock:{user_id}:{lead_id}", now_iso],
        )

        # ── Step 6: Audit log + commit ──────────────────────────────────
        _audit_log(conn, user_id, "lead_unlock", {
            "lead_id": lead_id, "cost": cost, "balance_after": balance - cost,
            "tier": user.get("tier"), "status": status,
        }, ip)
        conn.execute("COMMIT")
        credits_after = balance - cost

    except HTTPException:
        raise
    except Exception as e:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        log.error("Unlock failed: %s", e)
        raise HTTPException(status_code=500, detail="Unlock failed.")
    finally:
        conn.close()

    result = _row_to_full(lead)
    # Phase 5: source_doc_count for UI evidence lock
    try:
        _sc = _get_conn()
        _county = lead.get("county", "")
        _case = lead.get("case_number", "")
        _asset_key = f"FORECLOSURE:CO:{_county.upper()}:{_case.upper()}"
        _snap_ct = _sc.execute("SELECT COUNT(*) FROM html_snapshots WHERE asset_id=?", [_asset_key]).fetchone()[0]
        _pdf_ct = _sc.execute("SELECT COUNT(*) FROM evidence_documents WHERE asset_id=?", [_asset_key]).fetchone()[0]
        result["source_doc_count"] = _snap_ct + _pdf_ct
        _sc.close()
    except Exception:
        result["source_doc_count"] = 0
    result["ok"] = True
    result["credits_remaining"] = credits_after
    result["credits_spent"] = cost
    return result


# ── POST /api/billing/upgrade — Tier upgrade + credit refill ────────

@app.post("/api/billing/upgrade")
async def billing_upgrade(request: Request):
    """Update tier and refill credits."""
    user = _require_user(request)
    body = await request.json()
    new_tier = body.get("tier", "").lower()

    from verifuse_v2.server.pricing import TIERS
    valid_tiers = list(TIERS.keys())

    if new_tier not in valid_tiers:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid tier. Choose from: {valid_tiers}",
        )

    credits = get_monthly_credits(new_tier)
    now = datetime.now(timezone.utc).isoformat()

    conn = _get_conn()
    try:
        conn.execute("""
            UPDATE users SET tier = ?, credits_remaining = ?, credits_reset_at = ?
            WHERE user_id = ?
        """, [new_tier, credits, now, user["user_id"]])
        conn.commit()
    finally:
        conn.close()

    return {
        "status": "ok",
        "user_id": user["user_id"],
        "tier": new_tier,
        "credits_remaining": credits,
    }


# ── GET /api/stats — Public dashboard stats ────────────────────────

@app.get("/api/stats")
async def get_stats():
    def _run():
        conn = _thread_conn()
        try:
            total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
            # attorney_ready: excludes REJECT — only actionable pipeline leads
            with_surplus = conn.execute(
                "SELECT COUNT(*) FROM leads WHERE data_grade != 'REJECT' AND COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0) > 1000"
            ).fetchone()[0]
            gold_count = conn.execute(
                "SELECT COUNT(*) FROM leads WHERE data_grade = 'GOLD'"
            ).fetchone()[0]
            # total_claimable_surplus: excludes REJECT — only actionable pipeline
            total_surplus = conn.execute(
                "SELECT COALESCE(SUM(COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0)), 0) FROM leads WHERE data_grade != 'REJECT' AND COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0) > 0"
            ).fetchone()[0]
            counties = conn.execute("""
                SELECT county, COUNT(*) as cnt,
                       COALESCE(SUM(COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0)), 0) as total
                FROM leads
                WHERE data_grade != 'REJECT' AND COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0) > 0
                GROUP BY county ORDER BY total DESC
            """).fetchall()
            # Surplus stream breakdown
            stream_rows = conn.execute("""
                SELECT COALESCE(surplus_stream, 'FORECLOSURE_OVERBID') as stream, COUNT(*) as cnt,
                       COALESCE(SUM(COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0)), 0) as total
                FROM leads
                WHERE data_grade != 'REJECT' AND COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0) > 0
                GROUP BY stream
            """).fetchall()
            stream_breakdown = [dict(r) for r in stream_rows]

            # Verified pipeline: GOLD+SILVER+BRONZE, surplus > 100, not expired
            vp_row = conn.execute(f"""
                SELECT COUNT(*) as cnt,
                       COALESCE(SUM(COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0)), 0) as total
                FROM leads
                WHERE data_grade IN ('GOLD', 'SILVER', 'BRONZE')
                  AND COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0) > 100
                  {_EXPIRED_FILTER}
            """).fetchone()

            # Total raw volume: ALL leads
            raw_row = conn.execute("""
                SELECT COUNT(*) as cnt,
                       COALESCE(SUM(COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0)), 0) as total
                FROM leads
            """).fetchone()

            # Grade breakdown: SILVER, BRONZE, REJECT
            silver_count = conn.execute(
                "SELECT COUNT(*) FROM leads WHERE data_grade = 'SILVER'"
            ).fetchone()[0]
            bronze_count = conn.execute(
                "SELECT COUNT(*) FROM leads WHERE data_grade = 'BRONZE'"
            ).fetchone()[0]
            reject_count = conn.execute(
                "SELECT COUNT(*) FROM leads WHERE data_grade = 'REJECT'"
            ).fetchone()[0]

            # Pre-sale pipeline: upcoming auctions not yet sold
            pre_sale_count = conn.execute(
                "SELECT COUNT(*) FROM leads WHERE processing_status = 'PRE_SALE'"
            ).fetchone()[0]
            pre_sale_surplus = conn.execute(
                "SELECT COALESCE(SUM(COALESCE(pre_sale_estimated_surplus, opening_bid, 0)), 0) "
                "FROM leads WHERE processing_status = 'PRE_SALE' AND opening_bid > 0"
            ).fetchone()[0]

            # County list from county_profiles (active counties in platform)
            county_rows = conn.execute(
                "SELECT county FROM county_profiles ORDER BY county"
            ).fetchall()
            county_list = [r[0].replace("_", " ").title() for r in county_rows] if county_rows else []
        finally:
            conn.close()

        return {
            "total_leads": total,
            "total_assets": vp_row["cnt"],  # pipeline: GOLD/SILVER/BRONZE, surplus>100
            "attorney_ready": with_surplus,
            "with_surplus": with_surplus,
            "gold_grade": gold_count,
            "silver_grade": silver_count,
            "bronze_grade": bronze_count,
            "reject_grade": reject_count,
            "county_list": county_list,
            "total_claimable_surplus": round(total_surplus, 2),
            "counties": [dict(r) for r in counties],
            "stream_breakdown": stream_breakdown,
            "verified_pipeline": vp_row["cnt"],
            "verified_pipeline_surplus": round(vp_row["total"], 2),
            "total_raw_volume": raw_row["cnt"],
            "total_raw_volume_surplus": round(raw_row["total"], 2),
            "pre_sale_count": pre_sale_count,
            "pre_sale_pipeline_surplus": round(pre_sale_surplus, 2),
        }

    return await _run_in_db(_run)


# ── Auth endpoints (delegate to auth module) ────────────────────────

@app.post("/api/auth/register")
@limiter.limit("5/minute")
async def api_register(request: Request):
    from verifuse_v2.server.auth import register_user
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")
    email = body.get("email", "").strip().lower()
    password = body.get("password", "")
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password required.")
    bar_number = body.get("bar_number", "").strip()
    user, token = register_user(
        email=email, password=password,
        full_name=body.get("full_name", ""),
        firm_name=body.get("firm_name", ""),
        bar_number=bar_number,
        tier=body.get("tier", "scout"),
    )
    # Founders cap check
    _try_founders_redemption(user["user_id"])
    # If bar_number was supplied at registration, auto-queue attorney verification
    if bar_number:
        conn2 = _get_conn()
        try:
            conn2.execute(
                "UPDATE users SET attorney_status = 'PENDING' WHERE user_id = ? AND attorney_status = 'NONE'",
                [user["user_id"]],
            )
            conn2.commit()
        finally:
            conn2.close()
    conn = _get_conn()
    try:
        balance = _ledger_balance(conn, user["user_id"])
    finally:
        conn.close()
    return {"token": token, "user": {
        "user_id": user["user_id"], "email": user["email"],
        "tier": user["tier"],
        "credits_remaining": balance,
        "ledger_balance": balance,
        "role": user.get("role", "public"),
    }}


@app.post("/api/auth/login")
@limiter.limit("10/minute")
async def api_login(request: Request):
    from verifuse_v2.server.auth import login_user
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")
    email = body.get("email", "").strip().lower()
    password = body.get("password", "")
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password required.")
    user, token = login_user(email=email, password=password)
    conn = _get_conn()
    try:
        balance = _ledger_balance(conn, user["user_id"])
    finally:
        conn.close()
    return {"token": token, "user": {
        "user_id": user["user_id"], "email": user["email"],
        "tier": user["tier"],
        "credits_remaining": balance,
        "ledger_balance": balance,
        "role": user.get("role", "public"),
    }}


@app.get("/api/auth/me")
async def api_me(request: Request):
    user = _require_user(request)
    conn = _get_conn()
    try:
        balance = _ledger_balance(conn, user["user_id"])
    finally:
        conn.close()
    from verifuse_v2.server.pricing import get_monthly_credits
    monthly_grant = get_monthly_credits(user["tier"])
    credits_pct = round(balance / max(monthly_grant, 1) * 100, 1)
    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "full_name": user.get("full_name", ""),
        "firm_name": user.get("firm_name", ""),
        "tier": user["tier"],
        "credits_remaining": balance,
        "ledger_balance": balance,
        "credits_pct_remaining": credits_pct,
        "upgrade_recommended": credits_pct < 20.0,
        "monthly_grant": monthly_grant,
        "role": user.get("role", "public"),
        "attorney_status": user.get("attorney_status", "NONE"),
        "is_admin": bool(user.get("is_admin", 0)),
        "email_verified": bool(user.get("email_verified", 0)),
        "founders_pricing": bool(user.get("founders_pricing", 0)),
    }


# ── Email Verification ──────────────────────────────────────────────

@app.post("/api/auth/send-verification")
@limiter.limit("3/minute")
async def send_verification(request: Request):
    """Send a 6-digit verification code to the user's email."""
    user = _require_user(request)

    code = "".join(random.choices(string.digits, k=6))
    now = datetime.now(timezone.utc).isoformat()

    # DEV-ONLY: log the code when SMTP is not configured (email mode = log).
    # NEVER logs in production — _IS_DEV is False unless VERIFUSE_ENV=development.
    if _IS_DEV and os.environ.get("VERIFUSE_EMAIL_MODE", "log").lower() == "log":
        log.info("[DEV] Verification code for %s: %s", user["email"], code)
        # print() goes directly to stdout → systemd journal (log.info is swallowed
        # without a configured handler in uvicorn's log setup)
        print(f"[DEV] Verification code for {user['email']}: {code}", flush=True)

    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE users SET email_verify_code = ?, email_verify_sent_at = ? WHERE user_id = ?",
            [code, now, user["user_id"]],
        )
        conn.commit()
    finally:
        conn.close()

    email_mode = os.environ.get("VERIFUSE_EMAIL_MODE", "log").lower()
    _send_email(
        to=user["email"],
        subject="VeriFuse Email Verification",
        body=f"Your VeriFuse verification code is: {code}\n\nThis code expires in 10 minutes.",
    )
    log.info("Verification email dispatched to %s (mode=%s)", user["email"], email_mode)

    # When email delivery is not configured, return the code in the response so the
    # user can verify without needing an inbox. In production (ses/smtp mode) this
    # field is omitted and the code is only delivered via email.
    resp: dict = {"ok": True, "message": "Verification code sent."}
    if email_mode == "log":
        resp["dev_code"] = code
        resp["message"] = "Email delivery not configured — use dev_code to verify."
    return resp


@app.post("/api/auth/verify-email")
@limiter.limit("10/minute")
async def verify_email(request: Request):
    """Verify email with 6-digit code. Code expires after 10 minutes."""
    user = _require_user(request)
    body = await request.json()
    code = body.get("code", "").strip()

    if not code:
        raise HTTPException(status_code=400, detail="Verification code required.")

    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT email_verify_code, email_verify_sent_at FROM users WHERE user_id = ?",
            [user["user_id"]],
        ).fetchone()

        if not row or not row[0]:
            raise HTTPException(status_code=400, detail="No verification code pending. Request a new one.")

        stored_code = row[0]
        sent_at = row[1]

        # Check expiry (10 minutes)
        if sent_at:
            try:
                sent_dt = datetime.fromisoformat(sent_at)
                if datetime.now(timezone.utc) - sent_dt > timedelta(minutes=10):
                    raise HTTPException(status_code=400, detail="Code expired. Request a new one.")
            except (ValueError, TypeError):
                pass

        if code != stored_code:
            raise HTTPException(status_code=400, detail="Invalid code.")

        # Success — verify and clear
        conn.execute(
            "UPDATE users SET email_verified = 1, email_verify_code = NULL, email_verify_sent_at = NULL WHERE user_id = ?",
            [user["user_id"]],
        )
        conn.commit()
    finally:
        conn.close()

    return {"ok": True, "email_verified": True}


# ── GET /api/counties — County breakdown ───────────────────────────

# ── GET /api/lead/{id} — Single lead detail (frontend compat) ─────

@app.get("/api/lead/{lead_id}")
@limiter.limit("100/minute")
async def get_lead_detail(lead_id: str, request: Request):
    """Return a single lead as SafeAsset. Frontend calls GET /api/lead/{id}."""
    user = _get_user_from_request(request)
    is_eff_admin = user and _effective_admin(user, request)
    user_id = user["user_id"] if user else None
    tier = user.get("tier", "scout") if user else None
    daily_limit = (get_daily_limit(tier) or 100) if tier else 100

    def _run():
        conn = _thread_conn()
        try:
            row = conn.execute(
                f"SELECT *, {_claim_deadline_expr} FROM leads WHERE id = ?", [lead_id]
            ).fetchone()
            if not row:
                return None

            result = _row_to_safe(dict(row))

            # ── Equity resolution fields (Gate 7) ────────────────────────────
            registry_asset_id = result.get("registry_asset_id")
            if registry_asset_id:
                try:
                    eq_row = conn.execute(
                        """SELECT gross_surplus_cents, net_owner_equity_cents, classification
                           FROM equity_resolution WHERE asset_id = ?""",
                        [registry_asset_id],
                    ).fetchone()
                    if eq_row:
                        result["gross_surplus_cents"]    = eq_row["gross_surplus_cents"]
                        result["net_owner_equity_cents"] = eq_row["net_owner_equity_cents"]
                        result["classification"]         = eq_row["classification"]
                except Exception:
                    pass  # Equity data is supplemental

            # ── Admin auto-unlock: return full PII data without click ────────
            if is_eff_admin:
                full = _row_to_full(dict(row))
                result.update(full)
                result["unlocked_by_me"] = True
                is_unlocked = True
            else:
                # ── Check unlock status ───────────────────────────────────────────
                is_unlocked = False
                if user_id:
                    u_row = conn.execute(
                        "SELECT 1 FROM lead_unlocks WHERE user_id = ? AND lead_id = ?",
                        [user_id, lead_id]
                    ).fetchone()
                    is_unlocked = bool(u_row)
                result["unlocked_by_me"] = is_unlocked

            # ── Forensic audit data (Phase 4 — unlocked leads only) ──────────
            # surplus_math_audit: math proof behind the GOLD grade
            # equity_resolution.notes: provenance citation (snapshot_id / doc_id)
            if is_unlocked and registry_asset_id:
                try:
                    audit_row = conn.execute(
                        """SELECT html_overbid, successful_bid, total_indebtedness,
                                  computed_surplus, voucher_overbid, voucher_doc_id,
                                  match_html_math, match_voucher,
                                  data_grade AS audit_grade, notes AS audit_notes,
                                  snapshot_id, doc_id
                           FROM surplus_math_audit
                           WHERE asset_id = ?
                           ORDER BY audit_ts DESC LIMIT 1""",
                        [registry_asset_id],
                    ).fetchone()
                    if audit_row:
                        result["surplus_math_audit"] = dict(audit_row)
                except Exception:
                    pass  # Supplemental — never block the lead response

                try:
                    eq_notes_row = conn.execute(
                        "SELECT notes FROM equity_resolution WHERE asset_id = ?",
                        [registry_asset_id],
                    ).fetchone()
                    if eq_notes_row and eq_notes_row["notes"]:
                        result["equity_resolution_notes"] = eq_notes_row["notes"]
                except Exception:
                    pass  # Supplemental — never block the lead response

            # ── Daily view rate limiting (BEGIN IMMEDIATE) ────────────────────
            if user_id and not is_unlocked and not is_eff_admin:
                today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    existing = conn.execute(
                        "SELECT count(*) as n FROM user_daily_lead_views "
                        "WHERE user_id=? AND day=? AND lead_id=?",
                        [user_id, today_str, lead_id]
                    ).fetchone()["n"]
                    if existing == 0:
                        conn.execute(
                            "INSERT INTO user_daily_lead_views (user_id, day, lead_id) VALUES (?,?,?)",
                            [user_id, today_str, lead_id]
                        )
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise

                count_row = conn.execute(
                    "SELECT COUNT(*) FROM user_daily_lead_views WHERE user_id = ? AND day = ?",
                    [user_id, today_str],
                ).fetchone()
                view_count = count_row[0] if count_row else 0
                if view_count > daily_limit:
                    return ("RATE_LIMIT", daily_limit, tier)

            # Mask PII for non-unlocked, non-admin users
            if not is_unlocked and not is_eff_admin:
                result["case_number"] = None

            return result
        finally:
            conn.close()

    result = await _run_in_db(_run)
    if result is None:
        raise HTTPException(status_code=404, detail="Lead not found.")
    if isinstance(result, tuple) and result[0] == "RATE_LIMIT":
        _, lim, t = result
        raise HTTPException(
            status_code=429,
            detail=f"Daily view limit reached ({lim} unique leads/day for {t} tier). Upgrade to view more.",
        )
    return result


# ── POST /api/unlock/{id} — Frontend-compatible unlock ──────────

@app.post("/api/unlock/{lead_id}")
@limiter.limit("10/minute")
async def unlock_lead_compat(lead_id: str, request: Request):
    """Frontend calls POST /api/unlock/{id}. Delegates to unlock logic."""
    return await unlock_lead(lead_id, request)


# ── POST /api/unlock-restricted/{id} — Restricted unlock ────────

@app.post("/api/unlock-restricted/{lead_id}")
@limiter.limit("10/minute")
async def unlock_restricted_lead(lead_id: str, request: Request):
    """Unlock a RESTRICTED lead with disclaimer acceptance.

    Requires verified attorney + OPERATOR/SOVEREIGN tier.
    Body: { "disclaimer_accepted": true }
    """
    user = _require_user(request)
    _check_email_verified(user, request)
    body = await request.json()
    if not body.get("disclaimer_accepted"):
        raise HTTPException(
            status_code=400,
            detail=f"You must accept the legal disclaimer: {UNLOCK_DISCLAIMER}",
        )

    # Verify attorney status
    if not _effective_admin(user, request) and not _is_verified_attorney(user):
        raise HTTPException(
            status_code=403,
            detail="RESTRICTED leads require verified attorney status.",
        )
    if not _effective_admin(user, request) and user.get("tier") not in ("operator", "sovereign"):
        raise HTTPException(
            status_code=403,
            detail="RESTRICTED leads require OPERATOR or SOVEREIGN tier.",
        )

    # Delegate to the main unlock handler
    result = await unlock_lead(lead_id, request)
    result["disclaimer_accepted"] = True
    result["attorney_exemption"] = "C.R.S. § 38-13-1302(5)"
    return result


# ── GET /api/dossier/{id} — Text dossier download ────────────────

@app.get("/api/dossier/{lead_id}")
async def get_dossier(lead_id: str, request: Request):
    """Generate and serve a text dossier for an unlocked lead."""
    from fastapi.responses import FileResponse

    user = _require_user(request)

    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", [lead_id]).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Lead not found.")

    lead = dict(row)

    # Check if user has unlocked this lead (or is admin)
    if not _effective_admin(user, request):
        conn = _get_conn()
        try:
            unlock = conn.execute(
                "SELECT 1 FROM lead_unlocks WHERE user_id = ? AND lead_id = ?",
                [user["user_id"], lead_id],
            ).fetchone()
        finally:
            conn.close()
        if not unlock:
            raise HTTPException(
                status_code=403,
                detail="You must unlock this lead before downloading the dossier.",
            )

    surplus = _safe_float(lead.get("surplus_amount")) or 0.0
    bid = _safe_float(lead.get("winning_bid")) or 0.0

    dossier_dir = Path(__file__).resolve().parent.parent / "data" / "dossiers"
    dossier_dir.mkdir(parents=True, exist_ok=True)
    filename = f"dossier_{lead_id[:12]}.txt"
    filepath = dossier_dir / filename

    with open(filepath, "w") as f:
        f.write("=" * 60 + "\n")
        f.write("  VERIFUSE — INTELLIGENCE DOSSIER\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Case Number:      {lead.get('case_number', 'N/A')}\n")
        f.write(f"County:           {lead.get('county', 'N/A')}\n")
        f.write(f"Owner:            {lead.get('owner_name', 'N/A')}\n")
        f.write(f"Property Address: {lead.get('property_address', 'N/A')}\n")
        f.write(f"Sale Date:        {lead.get('sale_date', 'N/A')}\n")
        f.write(f"Claim Deadline:   {lead.get('claim_deadline', 'N/A')}\n\n")
        f.write(f"Winning Bid:      ${bid:,.2f}\n")
        f.write(f"Total Debt:       ${_safe_float(lead.get('total_debt')) or 0:,.2f}\n")
        f.write(f"Surplus Amount:   ${surplus:,.2f}\n")
        f.write(f"Data Grade:       {lead.get('data_grade', 'N/A')}\n")
        f.write(f"Confidence:       {_safe_float(lead.get('confidence_score')) or 0:.0%}\n\n")
        f.write("=" * 60 + "\n")
        f.write("  DISCLAIMER: For informational purposes only.\n")
        f.write("  Verify all figures with the County Public Trustee.\n")
        f.write("=" * 60 + "\n")

    return FileResponse(
        str(filepath),
        media_type="text/plain",
        filename=filename,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


# ── POST /api/billing/checkout — Stripe checkout session ─────────

@app.post("/api/billing/checkout")
async def billing_checkout(request: Request):
    """Create a Stripe checkout session. Frontend calls POST /api/billing/checkout."""
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Billing not configured. Contact admin.")

    user = _require_user(request)
    body = await request.json()
    tier = body.get("tier", "").lower()
    billing_period = body.get("billing_period", "monthly").lower()
    if billing_period not in ("monthly", "annual"):
        billing_period = "monthly"

    if tier not in ("associate", "partner", "sovereign"):
        raise HTTPException(
            status_code=400,
            detail="Invalid tier. Choose from: associate, partner, sovereign",
        )

    try:
        from verifuse_v2.server.billing import create_checkout_session
        import inspect as _inspect
        _ccs_sig = _inspect.signature(create_checkout_session)
        _kwargs = dict(user_id=user["user_id"], email=user["email"], tier=tier)
        if "billing_period" in _ccs_sig.parameters:
            _kwargs["billing_period"] = billing_period
        checkout_url = create_checkout_session(**_kwargs)
        return {"checkout_url": checkout_url}
    except HTTPException:
        raise
    except Exception as e:
        log.error("Checkout failed: %s", e)
        raise HTTPException(status_code=503, detail="Billing service unavailable.")


# ── POST /api/billing/one-time — Any one-time pack purchase ─────────

_ONE_TIME_SKUS = {
    "starter":          {"env_key": "STARTER",          "credits": 10, "name": "Starter Pack"},
    "investigation":    {"env_key": "INVESTIGATION",     "credits": 25, "name": "Investigation Pack"},
    "filing_pack":      {"env_key": "FILING_PACK",       "credits": 3,  "name": "Filing Pack"},
    "premium_dossier":  {"env_key": "PREMIUM_DOSSIER",   "credits": 5,  "name": "Premium Dossier"},
}

@app.post("/api/billing/one-time")
@limiter.limit("10/minute")
async def billing_one_time(request: Request):
    """Create a Stripe checkout session for any one-time product (starter, investigation, filing_pack, premium_dossier)."""
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Billing not configured.")
    user = _require_user(request)
    body = await request.json()
    sku = body.get("sku", "").lower()
    meta = _ONE_TIME_SKUS.get(sku)
    if not meta:
        raise HTTPException(status_code=400, detail=f"Unknown SKU '{sku}'. Choose: {list(_ONE_TIME_SKUS.keys())}")

    price_id = os.environ.get(f"{_price_prefix}{meta['env_key']}", "")
    if not price_id:
        raise HTTPException(status_code=503, detail=f"{meta['name']} not configured in Stripe.")

    try:
        import stripe as _stripe
        _stripe.api_key = STRIPE_SECRET_KEY
        session = _stripe.checkout.Session.create(
            mode="payment",
            payment_method_types=["card"],
            customer_email=user["email"],
            client_reference_id=user["user_id"],
            metadata={
                "sku": sku,
                "user_id": user["user_id"],
                "price_id": price_id,
                "credits": str(meta["credits"]),
            },
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{os.environ.get('VERIFUSE_BASE_URL', 'https://verifuse.tech')}/dashboard?pack=success",
            cancel_url=f"{os.environ.get('VERIFUSE_BASE_URL', 'https://verifuse.tech')}/pricing",
        )
        return {"checkout_url": session.url}
    except Exception as e:
        log.error("One-time checkout failed: %s", e)
        raise HTTPException(status_code=503, detail="Billing service unavailable.")


# ── POST /api/billing/starter — Starter Pack one-time purchase ──────

@app.post("/api/billing/starter")
async def billing_starter(request: Request):
    """Create a Stripe checkout session for the $19 Starter Pack (10 credits)."""
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Billing not configured.")

    user = _require_user(request)

    starter_price_id = os.environ.get(f"{_price_prefix}STARTER", "")
    if not starter_price_id or starter_price_id == "price_PLACEHOLDER":
        raise HTTPException(status_code=503, detail="Starter pack not configured.")

    try:
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
        session = stripe.checkout.Session.create(
            mode="payment",
            payment_method_types=["card"],
            customer_email=user["email"],
            client_reference_id=user["user_id"],
            metadata={
                "sku": "starter_pack",
                "user_id": user["user_id"],
                "price_id": starter_price_id,
                "credits": str(STARTER_PACK["credits"]),
            },
            line_items=[{"price": starter_price_id, "quantity": 1}],
            success_url=f"{os.environ.get('VERIFUSE_BASE_URL', 'https://verifuse.tech')}/dashboard?starter=success",
            cancel_url=f"{os.environ.get('VERIFUSE_BASE_URL', 'https://verifuse.tech')}/pricing",
        )
        return {"checkout_url": session.url}
    except Exception as e:
        log.error("Starter checkout failed: %s", e)
        raise HTTPException(status_code=503, detail="Billing service unavailable.")


# ── POST /api/webhook — Stripe webhook (belt + suspenders) ──────────

@app.post("/api/webhook")
async def stripe_webhook(request: Request):
    """Stripe webhook handler with idempotency and strict validation.

    Handles:
      - checkout.session.completed (starter pack crediting)
      - invoice.payment_succeeded (subscription cycle/create)
      - customer.subscription.deleted (cancellation)
    """
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    # Verify signature
    if STRIPE_WEBHOOK_SECRET:
        try:
            import stripe
            event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid signature.")
    else:
        event = json.loads(payload)

    event_id = event.get("id", "")
    event_type = event.get("type", "")
    data_obj = event.get("data", {}).get("object", {})

    # Idempotency: check if we've already processed this event
    conn = _get_conn()
    try:
        existing = conn.execute(
            "SELECT 1 FROM stripe_events WHERE event_id = ?", [event_id]
        ).fetchone()
        if existing:
            return {"status": "already_processed"}
        conn.execute(
            "INSERT INTO stripe_events (event_id, type, received_at) VALUES (?, ?, datetime('now'))",
            [event_id, event_type],
        )
        conn.commit()
    finally:
        conn.close()

    if event_type == "checkout.session.completed":
        _handle_checkout_session(data_obj)
    elif event_type == "invoice.payment_succeeded":
        _handle_invoice_payment(data_obj)
    elif event_type == "customer.subscription.deleted":
        _handle_subscription_cancelled(data_obj)
    else:
        log.debug("Unhandled Stripe event: %s", event_type)

    return {"status": "ok"}


def _handle_checkout_session(session: dict) -> None:
    """Handle checkout.session.completed — starter pack crediting."""
    metadata = session.get("metadata", {})
    sku = metadata.get("sku", "")

    if sku == "starter_pack":
        # Starter pack validation — ALL must pass
        if session.get("mode") != "payment":
            log.warning("Starter: mode != payment")
            return
        if session.get("payment_status") != "paid":
            log.warning("Starter: payment_status != paid")
            return
        user_id = metadata.get("user_id", "")
        if not user_id:
            log.warning("Starter: no user_id in metadata")
            return
        if session.get("client_reference_id") != user_id:
            log.warning("Starter: client_reference_id mismatch")
            return
        credits_str = metadata.get("credits", "")
        if credits_str != str(STARTER_PACK["credits"]):
            log.warning("Starter: credits mismatch (got %s, expected %s)", credits_str, STARTER_PACK["credits"])
            return
        amount_total = session.get("amount_total", 0)
        if amount_total <= 0:
            log.warning("Starter: amount_total <= 0")
            return
        currency = (session.get("currency") or "").lower()
        if currency != EXPECTED_CURRENCY:
            log.warning("Starter: currency mismatch (got %s)", currency)
            return

        # Credit the starter pack via FIFO ledger (30-day expiry)
        import uuid as _uuid_mod
        session_id = session.get("id", "")
        credits = STARTER_PACK["credits"]
        expiry_days = STARTER_PACK.get("expiry_days", 30)
        expires_ts = _epoch_now() + expiry_days * 86400

        conn = _get_conn()
        try:
            try:
                conn.execute(
                    "INSERT INTO unlock_ledger_entries "
                    "(id, user_id, source, qty_total, qty_remaining, purchased_ts, expires_ts, stripe_event_id) "
                    "VALUES (?, ?, 'starter', ?, ?, ?, ?, ?)",
                    [str(_uuid_mod.uuid4()), user_id, credits, credits,
                     _epoch_now(), expires_ts, session_id],
                )
            except sqlite3.IntegrityError:
                log.info("Starter pack already credited (stripe_event_id dup): %s", session_id)
                return
            _audit_log(conn, user_id, "starter_pack_credited", {
                "credits": credits, "amount_total": amount_total,
                "session_id": session_id, "expires_ts": expires_ts,
            })
            conn.commit()
            log.info("Starter pack credited: user=%s credits=%d expires=%d", user_id, credits, expires_ts)
        finally:
            conn.close()
    else:
        # Subscription checkout — record customer/subscription IDs only.
        # Credits are granted atomically by the invoice.payment_succeeded event.
        user_id = metadata.get("user_id", "")
        tier = metadata.get("tier", "scout")
        customer_id = session.get("customer", "")
        subscription_id = session.get("subscription", "")

        if not user_id:
            log.warning("Subscription checkout: no user_id")
            return

        conn = _get_conn()
        try:
            conn.execute(
                "UPDATE users SET stripe_customer_id = ?, stripe_subscription_id = ?, "
                "subscription_status = 'active', tier = ? WHERE user_id = ?",
                [customer_id, subscription_id, tier, user_id],
            )
            _audit_log(conn, user_id, "subscription_activated", {
                "tier": tier, "customer_id": customer_id,
            })
            conn.commit()
            log.info("Subscription activated: user=%s tier=%s (credits via invoice event)", user_id, tier)
        finally:
            conn.close()


def _handle_invoice_payment(invoice: dict) -> None:
    """Handle invoice.payment_succeeded — subscription cycle crediting.

    STRICTEST validation: all checks must pass before crediting.
    """
    # Basic invoice validation
    if not invoice.get("paid"):
        return
    if invoice.get("status") != "paid":
        return
    amount_paid = invoice.get("amount_paid", 0)
    if amount_paid <= 0:
        return
    amount_due = invoice.get("amount_due", 0)
    if amount_paid < amount_due:
        return
    customer_id = invoice.get("customer", "")
    subscription_id = invoice.get("subscription", "")
    if not customer_id or not subscription_id:
        return
    currency = (invoice.get("currency") or "").lower()
    if currency != EXPECTED_CURRENCY:
        log.warning("Invoice: currency mismatch (got %s)", currency)
        return

    # Map invoice → user
    conn = _get_conn()
    try:
        user_row = conn.execute(
            "SELECT user_id, stripe_subscription_id, tier FROM users WHERE stripe_customer_id = ?",
            [customer_id],
        ).fetchone()
        if not user_row:
            _audit_log(conn, "", "unknown_customer", {"customer_id": customer_id})
            conn.commit()
            log.warning("Invoice: unknown customer %s", customer_id)
            return

        user_id = user_row["user_id"]
        existing_sub = user_row["stripe_subscription_id"]

        # Subscription ID validation
        if existing_sub and existing_sub != subscription_id:
            _audit_log(conn, user_id, "subscription_mismatch", {
                "expected": existing_sub, "got": subscription_id,
            })
            conn.commit()
            log.warning("Invoice: subscription mismatch for user %s", user_id)
            return
        if not existing_sub:
            conn.execute(
                "UPDATE users SET stripe_subscription_id = ? WHERE user_id = ?",
                [subscription_id, user_id],
            )

        # Line-item extraction — find valid subscription line
        lines = invoice.get("lines", {}).get("data", [])
        valid_line = None
        for line in lines:
            price_id = line.get("price", {}).get("id", "")
            if price_id not in _PRICE_MAP:
                continue
            if _PRICE_MAP[price_id]["kind"] != "subscription":
                continue
            if line.get("proration", False):
                continue
            if line.get("amount", 0) <= 0:
                continue
            valid_line = line
            break

        if not valid_line:
            _audit_log(conn, user_id, "no_valid_subscription_line", {
                "line_count": len(lines),
            })
            conn.commit()
            log.warning("Invoice: no valid subscription line for user %s", user_id)
            return

        price_id = valid_line["price"]["id"]
        price_info = _PRICE_MAP[price_id]
        billing_reason = invoice.get("billing_reason", "")

        import uuid as _uuid_mod
        new_tier = price_info["tier"]
        monthly = price_info["monthly_credits"]

        if billing_reason == "subscription_update":
            # Tier sync only — NO credits; handled separately from invoice
            # TIER_RANK guard: never allow Stripe to downgrade a user
            _TIER_RANK = {"scout": 0, "operator": 1, "sovereign": 2}
            cur_row = conn.execute(
                "SELECT tier FROM users WHERE user_id = ?", [user_id]
            ).fetchone()
            current_tier = (cur_row["tier"] if cur_row else None) or "scout"
            if _TIER_RANK.get(new_tier, 0) >= _TIER_RANK.get(current_tier, 0):
                conn.execute(
                    "UPDATE users SET tier = ?, subscription_status = 'active' WHERE user_id = ?",
                    [new_tier, user_id],
                )
                _audit_log(conn, user_id, "subscription_tier_sync", {"tier": new_tier})
            else:
                _audit_log(conn, user_id, "subscription_downgrade_blocked",
                           {"attempted": new_tier, "current": current_tier})
        elif billing_reason in ("subscription_cycle", "subscription_create"):
            # Determine period end (subscription expiry)
            # invoice.lines[0].period.end is the most reliable source
            period_end_ts = None
            for line in lines:
                period = line.get("period", {})
                pe = period.get("end")
                if pe:
                    try:
                        period_end_ts = int(pe)
                    except (ValueError, TypeError):
                        pass
                    break

            rollover = 0
            rollover_entries = []

            # Rollover: Month 1 only (subscription_create)
            if billing_reason == "subscription_create":
                now_ts = _epoch_now()
                cutoff_ts = now_ts - 7 * 86400
                starter_rows = conn.execute(
                    "SELECT id, qty_remaining FROM unlock_ledger_entries "
                    "WHERE user_id = ? AND source = 'starter' AND qty_remaining > 0 "
                    "AND purchased_ts >= ? AND (expires_ts IS NULL OR expires_ts > ?)",
                    [user_id, cutoff_ts, now_ts],
                ).fetchall()
                for s in starter_rows:
                    rollover += s["qty_remaining"]
                    rollover_entries.append(s["id"])

            total_credits = monthly + rollover

            # INSERT subscription ledger entry (idempotent via stripe_event_id)
            try:
                conn.execute(
                    "INSERT INTO unlock_ledger_entries "
                    "(id, user_id, source, qty_total, qty_remaining, purchased_ts, expires_ts, "
                    "stripe_event_id, tier_at_purchase) "
                    "VALUES (?, ?, 'subscription', ?, ?, ?, ?, ?, ?)",
                    [str(_uuid_mod.uuid4()), user_id, total_credits, total_credits,
                     _epoch_now(), period_end_ts, event_id, new_tier],
                )
            except sqlite3.IntegrityError:
                log.info("Invoice already processed (stripe_event_id dup): %s", event_id)
                conn.commit()
                return

            # Zero out rolled-over starter entries
            if rollover_entries:
                for entry_id in rollover_entries:
                    conn.execute(
                        "UPDATE unlock_ledger_entries SET qty_remaining = 0 WHERE id = ?",
                        [entry_id],
                    )
                _audit_log(conn, user_id, "starter_rollover", {
                    "rollover_credits": rollover, "entry_ids": rollover_entries,
                })

            # Update users.tier + subscription_status
            conn.execute(
                "UPDATE users SET tier = ?, subscription_status = 'active' WHERE user_id = ?",
                [new_tier, user_id],
            )
            _audit_log(conn, user_id, "subscription_credits_granted", {
                "tier": new_tier, "credits": monthly, "rollover": rollover,
                "total": total_credits, "reason": billing_reason,
            })
            log.info("Credits granted: user=%s tier=%s monthly=%d rollover=%d total=%d reason=%s",
                     user_id, new_tier, monthly, rollover, total_credits, billing_reason)
        else:
            log.debug("Invoice: unhandled billing_reason=%s for user %s", billing_reason, user_id)

        conn.commit()
    finally:
        conn.close()


def _handle_subscription_cancelled(subscription: dict) -> None:
    """Handle customer.subscription.deleted — cancel subscription."""
    customer_id = subscription.get("customer", "")
    if not customer_id:
        return

    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE users SET subscription_status = 'canceled' WHERE stripe_customer_id = ?",
            [customer_id],
        )
        user_row = conn.execute(
            "SELECT user_id FROM users WHERE stripe_customer_id = ?", [customer_id]
        ).fetchone()
        if user_row:
            _audit_log(conn, user_row["user_id"], "subscription_cancelled", {
                "customer_id": customer_id,
            })
        conn.commit()
        log.info("Subscription cancelled: customer=%s", customer_id)
    finally:
        conn.close()


# ── GET /api/counties — County breakdown ───────────────────────────

@app.get("/api/counties")
async def get_counties():
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT county, COUNT(*) as lead_count,
                   COALESCE(SUM(COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0)), 0) as total_surplus,
                   COALESCE(AVG(COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0)), 0) as avg_surplus,
                   COALESCE(MAX(COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0)), 0) as max_surplus
            FROM leads
            WHERE COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0) > 0
            GROUP BY county ORDER BY total_surplus DESC
        """).fetchall()
    finally:
        conn.close()

    return {
        "count": len(rows),
        "counties": [dict(r) for r in rows],
    }


# ── GET /api/inventory_health — Vault status ──────────────────────

@app.get("/api/inventory_health")
async def inventory_health():
    """Public inventory health summary for dashboard."""
    conn = _get_conn()
    try:
        total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        active = conn.execute(
            "SELECT COUNT(*) FROM leads WHERE COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0) > 100 "
            f"AND data_grade != 'REJECT' {_EXPIRED_FILTER}"
        ).fetchone()[0]
        new_7d = conn.execute(
            "SELECT COUNT(*) FROM leads WHERE sale_date >= date('now', '-7 days')"
        ).fetchone()[0]
        # Completeness: leads with surplus > 0 and non-null owner_name
        complete = conn.execute(
            "SELECT COUNT(*) FROM leads WHERE COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0) > 0 "
            "AND owner_name IS NOT NULL AND TRIM(owner_name) != ''"
        ).fetchone()[0]
        completeness_pct = round(complete / total * 100, 1) if total > 0 else 0
    finally:
        conn.close()
    return {
        "active_leads": active,
        "total_leads": total,
        "new_last_7d": new_7d,
        "completeness_pct": completeness_pct,
    }


# ── Admin endpoints ──────────────────────────────────────────────────

@app.get("/api/admin/leads")
async def admin_leads(
    request: Request,
    limit: int = Query(100, ge=1, le=1000),
    grade: str = Query("", alias="grade"),
    county: str = Query("", alias="county"),
    surplus_stream: str = Query("", alias="surplus_stream"),
):
    """Get all leads with raw data (admin only). Supports JWT admin or API key auth."""
    _require_admin_or_api_key(request)
    conn = _get_conn()
    try:
        filters = []
        params: list = []
        if grade:
            filters.append("data_grade = ?")
            params.append(grade.upper())
        if county:
            filters.append("lower(county) = lower(?)")
            params.append(county)
        if surplus_stream:
            filters.append("surplus_stream = ?")
            params.append(surplus_stream.upper())
        where = ("WHERE " + " AND ".join(filters)) if filters else ""
        params.append(limit)
        rows = conn.execute(
            f"SELECT * FROM leads {where} "
            "ORDER BY COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0) DESC LIMIT ?",
            params,
        ).fetchall()
    finally:
        conn.close()
    return {"count": len(rows), "leads": [dict(r) for r in rows]}


@app.get("/api/admin/quarantine")
async def admin_quarantine(request: Request):
    """Get all quarantined leads (admin only)."""
    _require_api_key(request)
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM leads_quarantine ORDER BY quarantined_at DESC"
        ).fetchall()
    except Exception:
        return {"count": 0, "quarantined": []}
    finally:
        conn.close()
    return {"count": len(rows), "quarantined": [dict(r) for r in rows]}


@app.get("/api/admin/users")
async def admin_users(
    request: Request,
    attorney_status: str = Query("", alias="attorney_status"),
):
    """Get all users (admin only). Supports JWT admin or API key auth."""
    _require_admin_or_api_key(request)
    conn = _get_conn()
    try:
        where = ""
        params: list = []
        if attorney_status:
            where = "WHERE upper(attorney_status) = upper(?)"
            params.append(attorney_status)
        rows = conn.execute(
            f"SELECT user_id, email, full_name, firm_name, bar_number, bar_state, "
            f"tier, credits_remaining, attorney_status, role, "
            f"is_admin, is_active, email_verified, created_at, last_login_at FROM users {where}",
            params,
        ).fetchall()
    finally:
        conn.close()
    return {"count": len(rows), "users": [dict(r) for r in rows]}


@app.get("/api/admin/coverage")
async def admin_coverage(request: Request):
    """Scraper coverage report (admin only). Returns JSON array."""
    _require_admin_or_api_key(request)
    from verifuse_v2.scripts.coverage_report import generate_report
    report = generate_report()
    return {"count": len(report), "counties": report}


@app.get("/api/admin/system-stats")
async def admin_system_stats(request: Request):
    """Comprehensive system stats for admin System tab (admin only)."""
    _require_admin_or_api_key(request)

    import os as _os

    conn = _get_conn()
    try:
        # DB file size
        db_size_bytes = 0
        try:
            db_size_bytes = _os.path.getsize(VERIFUSE_DB_PATH)
        except Exception:
            pass

        # WAL info
        wal_pages = 0
        try:
            wal_info = conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
            wal_pages = wal_info[1] if wal_info else 0
        except Exception:
            pass

        # Leads scoreboard
        scoreboard_rows = conn.execute("""
            SELECT data_grade,
                   COUNT(*) as lead_count,
                   COALESCE(SUM(COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0)), 0) as total_surplus
            FROM leads
            GROUP BY data_grade
            ORDER BY CASE data_grade
                WHEN 'GOLD' THEN 1 WHEN 'SILVER' THEN 2
                WHEN 'BRONZE' THEN 3 WHEN 'REJECT' THEN 4 ELSE 5
            END
        """).fetchall()
        scoreboard = [
            {
                "data_grade": r["data_grade"] or "UNGRADED",
                "lead_count": r["lead_count"],
                "total_surplus": round(r["total_surplus"], 2),
            }
            for r in scoreboard_rows
        ]

        # Total leads
        total_leads = sum(r["lead_count"] for r in scoreboard)

        # Verified pipeline (GOLD+SILVER, surplus > 0)
        vp_row = conn.execute(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0)), 0) as total "
            "FROM leads WHERE data_grade IN ('GOLD','SILVER') AND COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0) > 0"
        ).fetchone()

        # Recent audit log
        audit_rows = []
        try:
            audit_rows = conn.execute("""
                SELECT al.id, al.user_id, al.action, al.meta_json, al.created_at, al.ip,
                       u.email as user_email
                FROM audit_log al
                LEFT JOIN users u ON u.user_id = al.user_id
                ORDER BY al.created_at DESC
                LIMIT 50
            """).fetchall()
        except Exception:
            pass

        recent_audit = []
        for r in audit_rows:
            entry = {
                "id": r["id"],
                "user_email": r["user_email"] or r["user_id"] or "system",
                "action": r["action"],
                "created_at": r["created_at"],
                "ip": r["ip"],
            }
            if r["meta_json"]:
                try:
                    entry["meta"] = json.loads(r["meta_json"])
                except Exception:
                    entry["meta"] = {}
            recent_audit.append(entry)

        # User counts
        user_counts = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN attorney_status='VERIFIED' THEN 1 ELSE 0 END) as verified_attorneys,
                SUM(CASE WHEN attorney_status='PENDING' THEN 1 ELSE 0 END) as pending_attorneys,
                SUM(CASE WHEN tier='sovereign' THEN 1 ELSE 0 END) as sovereign_users,
                SUM(CASE WHEN tier='partner' THEN 1 ELSE 0 END) as partner_users,
                SUM(CASE WHEN tier='associate' THEN 1 ELSE 0 END) as associate_users
            FROM users
        """).fetchone()

    finally:
        conn.close()

    # Stripe status
    stripe_configured = bool(STRIPE_SECRET_KEY)
    stripe_publishable_configured = bool(STRIPE_PUBLISHABLE_KEY)

    return {
        "db_path": VERIFUSE_DB_PATH,
        "db_size_mb": round(db_size_bytes / 1024 / 1024, 2),
        "wal_pages": wal_pages,
        "total_leads": total_leads,
        "scoreboard": scoreboard,
        "verified_pipeline_count": vp_row["cnt"],
        "verified_pipeline_surplus": round(vp_row["total"], 2),
        "recent_audit": recent_audit,
        "user_counts": dict(user_counts) if user_counts else {},
        "stripe_configured": stripe_configured,
        "stripe_publishable_configured": stripe_publishable_configured,
        "stripe_mode": STRIPE_MODE,
        "build_id": _BUILD_ID,
        "verifuse_env": os.environ.get("VERIFUSE_ENV", "production"),
        "api_key_configured": bool(VERIFUSE_API_KEY),
    }


_TIER_MONTHLY_CENTS = {"associate": 14900, "partner": 39900, "sovereign": 89900}


@app.get("/api/admin/revenue-metrics")
async def admin_revenue_metrics(request: Request):
    """MRR/ARR, tier breakdown, credit utilization, churn (admin only)."""
    _require_admin_or_api_key(request)
    conn = _get_conn()
    try:
        # Active subscriptions by tier
        tier_rows = conn.execute(
            "SELECT tier, COUNT(*) as cnt FROM users WHERE is_active=1 "
            "AND tier IN ('associate','partner','sovereign') GROUP BY tier"
        ).fetchall()
        by_tier: dict = {}
        mrr_cents = 0
        for r in tier_rows:
            price = _TIER_MONTHLY_CENTS.get(r["tier"], 0)
            by_tier[r["tier"]] = {"count": r["cnt"], "mrr_cents": price * r["cnt"]}
            mrr_cents += price * r["cnt"]

        # New subscribers last 30 days (audit_log events)
        new_30d = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE action='subscription_activated' "
            "AND created_at > datetime('now','-30 days')"
        ).fetchone()[0]

        # Churn last 30 days
        churn_30d = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE action IN ('subscription_cancelled','subscription_canceled') "
            "AND created_at > datetime('now','-30 days')"
        ).fetchone()[0]

        # Credit utilization — total granted vs total consumed
        total_credits_granted = conn.execute(
            "SELECT COALESCE(SUM(qty_total), 0) FROM unlock_ledger_entries"
        ).fetchone()[0] or 0
        total_credits_remaining = conn.execute(
            "SELECT COALESCE(SUM(qty_remaining), 0) FROM unlock_ledger_entries"
        ).fetchone()[0] or 0
        total_credits_used = total_credits_granted - total_credits_remaining
        utilization_pct = round(total_credits_used / max(total_credits_granted, 1) * 100, 1)

        # Founding attorneys (founders_pricing flag)
        founding_count = conn.execute(
            "SELECT COUNT(*) FROM users WHERE founders_pricing = 1"
        ).fetchone()[0]

    finally:
        conn.close()

    return {
        "mrr_cents": mrr_cents,
        "arr_cents": mrr_cents * 12,
        "active_subscriptions": sum(v["count"] for v in by_tier.values()),
        "by_tier": by_tier,
        "new_subscribers_30d": new_30d,
        "churn_30d": churn_30d,
        "credit_utilization_pct": utilization_pct,
        "total_credits_granted": total_credits_granted,
        "total_credits_used": total_credits_used,
        "founding_spots_claimed": founding_count,
        "founding_spots_total": 10,
    }


@app.get("/api/admin/audit-log")
async def admin_audit_log(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action: str = Query(""),
    user_email: str = Query(""),
):
    """Paginated audit log for admin (admin only)."""
    _require_admin_or_api_key(request)
    conn = _get_conn()
    try:
        wheres = []
        params: list = []
        if action:
            wheres.append("al.action LIKE ?")
            params.append(f"%{action}%")
        if user_email:
            wheres.append("LOWER(u.email) LIKE ?")
            params.append(f"%{user_email.lower()}%")
        where_sql = f"WHERE {' AND '.join(wheres)}" if wheres else ""
        rows = conn.execute(f"""
            SELECT al.id, al.user_id, al.action, al.meta_json, al.created_at, al.ip,
                   u.email as user_email
            FROM audit_log al
            LEFT JOIN users u ON u.user_id = al.user_id
            {where_sql}
            ORDER BY al.created_at DESC
            LIMIT ? OFFSET ?
        """, params + [limit, offset]).fetchall()
        total = conn.execute(f"""
            SELECT COUNT(*) FROM audit_log al
            LEFT JOIN users u ON u.user_id = al.user_id
            {where_sql}
        """, params).fetchone()[0]
    finally:
        conn.close()

    entries = []
    for r in rows:
        entry = {
            "id": r["id"],
            "user_email": r["user_email"] or r["user_id"] or "system",
            "action": r["action"],
            "created_at": r["created_at"],
            "ip": r["ip"],
        }
        if r["meta_json"]:
            try:
                entry["meta"] = json.loads(r["meta_json"])
            except Exception:
                entry["meta"] = {}
        entries.append(entry)

    return {"total": total, "entries": entries, "limit": limit, "offset": offset}


@app.get("/api/admin/lead-audit/{lead_id}")
async def admin_lead_audit(lead_id: str, request: Request):
    """Full forensic audit trail for a single lead (admin only).

    Returns all DB records touching this lead:
    - lead row (all raw fields)
    - surplus_math_audit record
    - equity_resolution record
    - pipeline_events for this asset
    - field_evidence records
    - audit_log entries that reference this lead_id
    - unlock history (asset_unlocks)
    """
    _require_admin_or_api_key(request)
    conn = _get_conn()
    try:
        # Lead row (all fields)
        lead_row = conn.execute("SELECT * FROM leads WHERE id = ?", [lead_id]).fetchone()
        if not lead_row:
            conn.close()
            raise HTTPException(status_code=404, detail="Lead not found.")
        lead = dict(lead_row)

        county = lead.get("county", "")
        case_number = lead.get("case_number", "")
        asset_id_canonical = f"FORECLOSURE:CO:{county.upper()}:{case_number}" if county and case_number else None

        # Surplus math audit
        math_audit = None
        if asset_id_canonical:
            row = conn.execute(
                "SELECT * FROM surplus_math_audit WHERE asset_id = ? ORDER BY audit_ts DESC LIMIT 1",
                [asset_id_canonical],
            ).fetchone()
            if row:
                math_audit = dict(row)

        # Equity resolution
        equity = None
        if asset_id_canonical:
            row = conn.execute(
                "SELECT * FROM equity_resolution WHERE asset_id = ?",
                [asset_id_canonical],
            ).fetchone()
            if row:
                equity = dict(row)

        # Field evidence — join via evidence_documents to get asset_id
        field_evidence = []
        if asset_id_canonical:
            try:
                rows = conn.execute(
                    """SELECT fe.* FROM field_evidence fe
                       JOIN evidence_documents ed ON ed.id = fe.evidence_doc_id
                       WHERE ed.asset_id = ?
                       ORDER BY fe.created_ts DESC""",
                    [asset_id_canonical],
                ).fetchall()
                field_evidence = [dict(r) for r in rows]
            except Exception:
                pass

        # Evidence documents
        evidence_docs = []
        if asset_id_canonical:
            try:
                rows = conn.execute(
                    "SELECT id, asset_id, filename, doc_family, bytes, retrieved_ts FROM evidence_documents WHERE asset_id = ? ORDER BY retrieved_ts DESC",
                    [asset_id_canonical],
                ).fetchall()
                evidence_docs = []
                for r in rows:
                    d = dict(r)
                    d["doc_family_label"] = DOC_FAMILY_LABELS.get(d.get("doc_family", ""), d.get("doc_family") or "Supporting Document")
                    evidence_docs.append(d)
            except Exception:
                pass

        # Pipeline events
        pipeline_events = []
        if asset_id_canonical:
            try:
                tc = conn.execute("PRAGMA table_info(pipeline_events)").fetchall()
                col_names = [c[1] for c in tc]
                time_col = "created_at" if "created_at" in col_names else "timestamp"
                rows = conn.execute(
                    f"SELECT * FROM pipeline_events WHERE asset_id = ? OR asset_id LIKE ? ORDER BY {time_col} DESC LIMIT 50",
                    [asset_id_canonical, f"%{case_number}%"],
                ).fetchall()
                pipeline_events = [dict(r) for r in rows]
            except Exception:
                pass

        # Audit log entries for this lead
        audit_entries = []
        try:
            rows = conn.execute(
                """SELECT al.*, u.email as user_email FROM audit_log al
                   LEFT JOIN users u ON u.user_id = al.user_id
                   WHERE al.meta_json LIKE ?
                   ORDER BY al.created_at DESC LIMIT 50""",
                [f"%{lead_id}%"],
            ).fetchall()
            for r in rows:
                entry = dict(r)
                if entry.get("meta_json"):
                    try:
                        entry["meta"] = json.loads(entry["meta_json"])
                    except Exception:
                        pass
                audit_entries.append(entry)
        except Exception:
            pass

        # Unlock history
        unlock_history = []
        try:
            rows = conn.execute(
                """SELECT au.*, u.email as user_email FROM asset_unlocks au
                   LEFT JOIN users u ON u.user_id = au.user_id
                   WHERE au.asset_id = ?
                   ORDER BY au.unlocked_at DESC""",
                [lead_id],
            ).fetchall()
            unlock_history = [dict(r) for r in rows]
        except Exception:
            pass

    finally:
        conn.close()

    # Add computed status
    status = _compute_status(lead)
    lead["_computed_status"] = status
    lead["_asset_id_canonical"] = asset_id_canonical

    return {
        "lead": lead,
        "math_audit": math_audit,
        "equity_resolution": equity,
        "field_evidence": field_evidence,
        "evidence_docs": evidence_docs,
        "pipeline_events": pipeline_events[:20],
        "audit_entries": audit_entries,
        "unlock_history": unlock_history,
    }


# ── Attorney Verification Endpoints ──────────────────────────────

@app.post("/api/attorney/verify")
@limiter.limit("5/minute")
async def attorney_verify(request: Request):
    """Submit attorney verification (bar number + state). Sets status to 'pending'."""
    user = _require_user(request)
    body = await request.json()
    bar_number = (body.get("bar_number") or "").strip()
    bar_state = (body.get("bar_state") or "CO").strip().upper()

    if not bar_number:
        raise HTTPException(status_code=400, detail="Bar number required.")

    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE users SET bar_number = ?, bar_state = ?, attorney_status = 'PENDING' WHERE user_id = ?",
            [bar_number, bar_state, user["user_id"]],
        )
        _audit_log(conn, user["user_id"], "attorney_verify_submitted", {
            "bar_number": bar_number, "bar_state": bar_state,
        }, _get_client_ip(request))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "attorney_status": "PENDING"}


@app.get("/api/admin/attorney/lookup")
async def admin_attorney_lookup(request: Request):
    """Admin: look up any user's attorney status and bar number by email or user_id."""
    admin = _require_user(request)
    if not _is_admin(admin):
        raise HTTPException(status_code=403, detail="Admin required.")
    params = dict(request.query_params)
    email = params.get("email", "").strip().lower()
    user_id = params.get("user_id", "").strip()
    if not email and not user_id:
        raise HTTPException(status_code=400, detail="Provide ?email= or ?user_id=")
    conn = _get_conn()
    try:
        if email:
            row = conn.execute(
                """SELECT user_id, email, full_name, firm_name, bar_number, bar_state,
                          attorney_status, attorney_verified_at, role, tier, is_admin, is_active
                   FROM users WHERE lower(email) = ?""",
                [email],
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT user_id, email, full_name, firm_name, bar_number, bar_state,
                          attorney_status, attorney_verified_at, role, tier, is_admin, is_active
                   FROM users WHERE user_id = ?""",
                [user_id],
            ).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="User not found.")
    return dict(row)


@app.post("/api/admin/attorney/approve")
async def admin_attorney_approve(request: Request):
    """Admin: approve attorney verification. Sets status to 'VERIFIED'."""
    admin = _require_user(request)
    if not _is_admin(admin):
        raise HTTPException(status_code=403, detail="Admin only.")
    body = await request.json()
    user_id = body.get("user_id", "")
    verification_url = body.get("verification_url", "")

    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required.")

    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE users SET attorney_status = 'VERIFIED', verified_attorney = 1, "
            "role = 'approved_attorney', "
            "bar_verified_at = datetime('now'), verification_url = ? WHERE user_id = ?",
            [verification_url, user_id],
        )
        _audit_log(conn, user_id, "attorney_approved", {
            "approved_by": admin["user_id"],
        })
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "attorney_status": "VERIFIED", "role": "approved_attorney"}


@app.post("/api/admin/attorney/reject")
async def admin_attorney_reject(request: Request):
    """Admin: reject attorney verification. Sets status to 'REJECTED'."""
    admin = _require_user(request)
    if not _is_admin(admin):
        raise HTTPException(status_code=403, detail="Admin only.")
    body = await request.json()
    user_id = body.get("user_id", "")
    reason = body.get("reason", "")

    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required.")

    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE users SET attorney_status = 'REJECTED', verified_attorney = 0 WHERE user_id = ?",
            [user_id],
        )
        _audit_log(conn, user_id, "attorney_rejected", {
            "rejected_by": admin["user_id"],
            "reason": reason,
        })
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "attorney_status": "REJECTED"}


# ── Admin: User Management Actions ──────────────────────────────────────────

@app.post("/api/admin/users/{user_id}/deactivate")
async def admin_deactivate_user(user_id: str, request: Request):
    """Admin: deactivate a user account (prevents login)."""
    admin = _require_user(request)
    if not _is_admin(admin):
        raise HTTPException(status_code=403, detail="Admin only.")
    conn = _get_conn()
    try:
        row = conn.execute("SELECT email, is_admin FROM users WHERE user_id = ?", [user_id]).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found.")
        if row["is_admin"]:
            raise HTTPException(status_code=400, detail="Cannot deactivate admin accounts.")
        conn.execute("UPDATE users SET is_active = 0 WHERE user_id = ?", [user_id])
        _audit_log(conn, user_id, "user_deactivated", {"by": admin["user_id"], "email": row["email"]})
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "is_active": False}


@app.post("/api/admin/users/{user_id}/activate")
async def admin_activate_user(user_id: str, request: Request):
    """Admin: reactivate a deactivated user account."""
    admin = _require_user(request)
    if not _is_admin(admin):
        raise HTTPException(status_code=403, detail="Admin only.")
    conn = _get_conn()
    try:
        row = conn.execute("SELECT email FROM users WHERE user_id = ?", [user_id]).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found.")
        conn.execute("UPDATE users SET is_active = 1 WHERE user_id = ?", [user_id])
        _audit_log(conn, user_id, "user_activated", {"by": admin["user_id"], "email": row["email"]})
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "is_active": True}


@app.post("/api/admin/users/{user_id}/adjust-credits")
async def admin_adjust_credits(user_id: str, request: Request):
    """Admin: add or subtract credits from a user's wallet (delta can be negative)."""
    admin = _require_user(request)
    if not _is_admin(admin):
        raise HTTPException(status_code=403, detail="Admin only.")
    body = await request.json()
    delta = int(body.get("delta", 0))
    note = str(body.get("note", "Admin adjustment"))[:200]
    if delta == 0:
        raise HTTPException(status_code=400, detail="delta must be non-zero.")

    conn = _get_conn()
    try:
        row = conn.execute("SELECT email FROM users WHERE user_id = ?", [user_id]).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found.")
        now_iso = datetime.now(timezone.utc).isoformat()
        # Insert a non-expiring ledger entry for positive, or consume from balance for negative
        if delta > 0:
            conn.execute(
                "INSERT INTO unlock_ledger_entries "
                "(user_id, qty_total, qty_remaining, source, expires_at, created_at) "
                "VALUES (?, ?, ?, 'admin_adjustment', NULL, ?)",
                [user_id, delta, delta, now_iso],
            )
        else:
            # Burn credits: reduce qty_remaining across entries
            remove = abs(delta)
            entries = conn.execute(
                "SELECT id, qty_remaining FROM unlock_ledger_entries "
                "WHERE user_id = ? AND qty_remaining > 0 "
                "ORDER BY CASE WHEN expires_at IS NULL THEN 1 ELSE 0 END, expires_at, created_at",
                [user_id],
            ).fetchall()
            for e in entries:
                if remove <= 0:
                    break
                take = min(e["qty_remaining"], remove)
                conn.execute(
                    "UPDATE unlock_ledger_entries SET qty_remaining = qty_remaining - ? WHERE id = ?",
                    [take, e["id"]],
                )
                remove -= take
        _audit_log(conn, user_id, "credits_adjusted", {
            "by": admin["user_id"], "delta": delta, "note": note, "email": row["email"],
        })
        conn.commit()
        new_balance = _ledger_balance(conn, user_id)
    finally:
        conn.close()
    return {"ok": True, "delta": delta, "new_balance": new_balance}


@app.post("/api/admin/users/{user_id}/set-role")
async def admin_set_role(user_id: str, request: Request):
    """Admin: change a user's role (public / approved_attorney / admin)."""
    admin = _require_user(request)
    if not _is_admin(admin):
        raise HTTPException(status_code=403, detail="Admin only.")
    body = await request.json()
    new_role = str(body.get("role", "")).strip()
    allowed = ("public", "approved_attorney", "admin")
    if new_role not in allowed:
        raise HTTPException(status_code=400, detail=f"role must be one of: {', '.join(allowed)}")
    conn = _get_conn()
    try:
        row = conn.execute("SELECT email FROM users WHERE user_id = ?", [user_id]).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found.")
        conn.execute("UPDATE users SET role = ? WHERE user_id = ?", [new_role, user_id])
        _audit_log(conn, user_id, "role_changed", {
            "by": admin["user_id"], "new_role": new_role, "email": row["email"],
        })
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "role": new_role}


@app.post("/api/admin/leads/{lead_id}/set-grade")
async def admin_set_lead_grade(lead_id: str, request: Request):
    """Admin: manually override a lead's data_grade."""
    admin = _require_user(request)
    if not _is_admin(admin):
        raise HTTPException(status_code=403, detail="Admin only.")
    body = await request.json()
    new_grade = str(body.get("grade", "")).strip().upper()
    allowed_grades = ("GOLD", "SILVER", "BRONZE", "REJECT")
    if new_grade not in allowed_grades:
        raise HTTPException(status_code=400, detail=f"grade must be one of: {', '.join(allowed_grades)}")
    reason = str(body.get("reason", "Admin override"))[:500]
    conn = _get_conn()
    try:
        row = conn.execute("SELECT county, case_number, data_grade FROM leads WHERE id = ?", [lead_id]).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Lead not found.")
        conn.execute("UPDATE leads SET data_grade = ?, updated_at = datetime('now') WHERE id = ?", [new_grade, lead_id])
        _audit_log(conn, admin["user_id"], "grade_override", {
            "lead_id": lead_id, "old_grade": row["data_grade"], "new_grade": new_grade,
            "reason": reason, "county": row["county"], "case_number": row["case_number"],
        })
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "lead_id": lead_id, "grade": new_grade}


# ── Attorney Tool Endpoints ───────────────────────────────────────

def _check_lead_unlocked(user: dict, lead_id: str, doc_type: str = "UNKNOWN", request: Request = None) -> None:
    """Verify user has unlocked this lead (or is admin). Log to download_audit."""
    ip = ""
    if request:
        ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if not ip and request.client:
            ip = request.client.host

    if _effective_admin(user, request):
        try:
            conn = _get_conn()
            conn.execute("""
                INSERT INTO download_audit (user_id, lead_id, doc_type, granted, ip_address)
                VALUES (?, ?, ?, 1, ?)
            """, [user["user_id"], lead_id, doc_type, ip])
            conn.commit()
            conn.close()
        except Exception:
            pass
        return

    conn = _get_conn()
    try:
        unlock = conn.execute(
            "SELECT 1 FROM lead_unlocks WHERE user_id = ? AND lead_id = ?",
            [user["user_id"], lead_id],
        ).fetchone()

        granted = 1 if unlock else 0
        try:
            conn.execute("""
                INSERT INTO download_audit (user_id, lead_id, doc_type, granted, ip_address)
                VALUES (?, ?, ?, ?, ?)
            """, [user["user_id"], lead_id, doc_type, granted, ip])
            conn.commit()
        except Exception:
            pass
    finally:
        conn.close()

    if not unlock:
        raise HTTPException(
            status_code=403,
            detail="You must unlock this lead first.",
        )


@app.get("/api/dossier/{lead_id}/docx")
async def get_dossier_docx(lead_id: str, request: Request):
    """Generate and serve a Word .docx dossier for an unlocked lead."""
    from fastapi.responses import FileResponse
    from verifuse_v2.attorney.dossier_docx import generate_dossier

    user = _require_user(request)
    _check_lead_unlocked(user, lead_id, doc_type="DOSSIER_DOCX", request=request)

    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", [lead_id]).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found.")

    try:
        filepath = generate_dossier(VERIFUSE_DB_PATH, lead_id)
    except Exception as e:
        log.error("Dossier generation failed: %s", e)
        raise HTTPException(status_code=500, detail="Dossier generation failed.")

    fname = Path(filepath).name
    return FileResponse(
        filepath,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=fname,
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@app.get("/api/dossier/{lead_id}/pdf")
async def get_dossier_pdf(lead_id: str, request: Request):
    """Alias: serve existing text dossier as PDF-format download."""
    return await get_dossier(lead_id, request)


def _generate_sample_dossier_pdf(lead: dict) -> bytes:
    """Generate a non-PII sample dossier PDF using fpdf2. Helvetica core font only."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Dark-themed header
    pdf.set_fill_color(15, 23, 42)
    pdf.rect(0, 0, 210, 40, "F")
    pdf.set_text_color(16, 185, 129)
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_xy(10, 10)
    pdf.cell(0, 10, "VERIFUSE // SAMPLE DOSSIER", ln=True)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(148, 163, 184)
    pdf.set_x(10)
    pdf.cell(0, 6, "Colorado Surplus Intelligence Platform", ln=True)

    pdf.ln(15)

    # Available data section
    pdf.set_text_color(248, 250, 252)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "AVAILABLE DATA", ln=True)
    pdf.set_draw_color(30, 41, 59)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(4)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(226, 232, 240)
    fields = [
        ("County", lead.get("county") or "N/A"),
        ("Sale Date", (lead.get("sale_date") or "N/A")[:7]),
        ("Data Grade", lead.get("data_grade") or "N/A"),
        ("Confidence Score", f"{(_safe_float(lead.get('confidence_score')) or 0) * 100:.0f}%"),
        ("Estimated Surplus", f"${_safe_float(lead.get('estimated_surplus')) or 0:,.2f}"),
    ]
    for label, value in fields:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(148, 163, 184)
        pdf.cell(55, 7, label + ":")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(226, 232, 240)
        pdf.cell(0, 7, value, ln=True)

    pdf.ln(10)

    # Redacted section
    pdf.set_text_color(239, 68, 68)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "REDACTED FIELDS (UNLOCK REQUIRED)", ln=True)
    pdf.set_draw_color(239, 68, 68)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(4)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(148, 163, 184)
    redacted = [
        "Owner Name", "Property Address", "Case Number",
        "Winning Bid", "Total Indebtedness", "Recorder Link",
    ]
    for field in redacted:
        pdf.cell(55, 7, field + ":")
        pdf.set_text_color(100, 116, 139)
        pdf.cell(0, 7, "[LOCKED - UNLOCK TO REVEAL]", ln=True)
        pdf.set_text_color(148, 163, 184)

    pdf.ln(10)

    # CTA
    pdf.set_fill_color(16, 185, 129)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 10, "  Unlock full intelligence at verifuse.tech", ln=True, fill=True)

    pdf.ln(8)

    # Disclaimer
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(100, 116, 139)
    pdf.multi_cell(0, 4,
        "DISCLAIMER: This sample dossier contains only publicly available, non-personally "
        "identifiable information. No PII is included. This platform provides access to public "
        "foreclosure sale data and does not constitute legal advice. "
        "C.R.S. 38-38-111 restrictions apply. Consult a licensed Colorado attorney."
    )

    raw_out = pdf.output(dest="S")
    pdf_bytes = raw_out if isinstance(raw_out, (bytes, bytearray)) else raw_out.encode("latin-1")
    return bytes(pdf_bytes)


@app.get("/api/dossier/sample/{preview_key}")
@limiter.limit("30/minute")
async def get_sample_dossier(preview_key: str, request: Request):
    """Non-PII sample dossier as PDF. No auth. O(1) lookup."""
    from fastapi.responses import Response

    # SECURITY ORACLE: Unified 404 — do not reveal which lookup step failed
    _NOT_FOUND = HTTPException(status_code=404, detail="Not found.")

    lead_id = _PREVIEW_LOOKUP.get(preview_key)
    if lead_id is None:
        raise _NOT_FOUND

    conn = _get_conn()
    try:
        row = conn.execute(
            f"SELECT county, sale_date, data_grade, confidence_score, "
            f"ROUND(COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0), 2) as estimated_surplus, "
            f"{_claim_deadline_expr} "
            f"FROM leads WHERE id = ?", [lead_id]
        ).fetchone()
    finally:
        conn.close()

    if not row:
        raise _NOT_FOUND

    # REQUEST-TIME RE-CHECK: lead data may have changed since startup
    if not is_preview_eligible(dict(row)):
        raise _NOT_FOUND

    pdf_bytes = _generate_sample_dossier_pdf(dict(row))

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="sample_dossier_{preview_key[:8]}.pdf"',
            "Access-Control-Expose-Headers": "Content-Disposition",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post("/api/letter/{lead_id}")
async def generate_letter_endpoint(lead_id: str, request: Request):
    """Generate a Rule 7.3 solicitation letter. Requires VERIFIED attorney."""
    from fastapi.responses import FileResponse
    from verifuse_v2.legal.mail_room import generate_letter

    user = _require_user(request)
    if not _is_verified_attorney(user) and not _effective_admin(user, request):
        raise HTTPException(
            status_code=403,
            detail="Rule 7.3 letters require verified attorney status.",
        )
    if not _effective_admin(user, request):
        if not user.get("verified_attorney"):
            raise HTTPException(status_code=403, detail="Verified attorney status required for letters.")
        if not user.get("firm_name"):
            raise HTTPException(status_code=403, detail="Firm name required for letter generation.")
        if not user.get("bar_number"):
            raise HTTPException(status_code=403, detail="Bar number required for letter generation.")
        if not user.get("firm_address"):
            raise HTTPException(status_code=403, detail="Firm address required for letter generation.")
    _check_lead_unlocked(user, lead_id, doc_type="LETTER", request=request)

    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", [lead_id]).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found.")

    _assert_ready_to_file(dict(row))

    try:
        filepath = generate_letter(VERIFUSE_DB_PATH, lead_id, user["user_id"])
    except Exception as e:
        log.error("Letter generation failed: %s", e)
        raise HTTPException(status_code=500, detail="Letter generation failed.")

    fname = Path(filepath).name
    return FileResponse(
        filepath,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=fname,
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@app.get("/api/case-packet/{lead_id}")
async def get_case_packet(lead_id: str, request: Request):
    """Download HTML case packet. Requires VERIFIED attorney + GOLD/SILVER lead."""
    from fastapi.responses import Response
    from verifuse_v2.attorney.case_packet import generate_case_packet

    user = _require_user(request)
    if not _is_verified_attorney(user) and not _effective_admin(user, request):
        raise HTTPException(
            status_code=403,
            detail="Case packets require verified attorney status.",
        )
    _check_lead_unlocked(user, lead_id, doc_type="CASE_PACKET", request=request)

    conn = _get_conn()
    try:
        _pkt_row = conn.execute("SELECT * FROM leads WHERE id = ?", [lead_id]).fetchone()
    finally:
        conn.close()
    if not _pkt_row:
        raise HTTPException(status_code=404, detail="Lead not found.")
    _assert_ready_to_file(dict(_pkt_row))

    try:
        filepath = generate_case_packet(VERIFUSE_DB_PATH, lead_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error("Case packet generation failed: %s", e)
        raise HTTPException(status_code=500, detail="Case packet generation failed.")

    html_content = Path(filepath).read_text(encoding="utf-8")
    fname = f"case_packet_{lead_id[:12]}.html"
    return Response(
        content=html_content,
        media_type="text/html",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@app.get("/api/leads/pre-sale")
@limiter.limit("100/minute")
async def get_presale_leads(
    request: Request,
    county: Optional[str] = Query(None),
    has_data: bool = Query(False),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Return PRE_SALE pipeline leads — upcoming auctions being monitored.

    Requires authentication (attorneys and admin).
    """
    _require_user(request)

    def _run():
        conn = _thread_conn()
        try:
            where = " WHERE processing_status = 'PRE_SALE'"
            params: list = []
            if county:
                where += " AND county = ?"
                params.append(county)
            if has_data:
                where += " AND (owner_name IS NOT NULL OR surplus_amount > 0)"

            total = conn.execute(
                f"SELECT COUNT(*) FROM leads{where}", params
            ).fetchone()[0]

            # County breakdown
            county_rows = conn.execute(
                f"""SELECT county,
                           COUNT(*) cnt,
                           SUM(CASE WHEN owner_name IS NOT NULL AND owner_name != '' THEN 1 ELSE 0 END) with_owner,
                           SUM(CASE WHEN surplus_amount > 0 THEN 1 ELSE 0 END) with_surplus,
                           SUM(COALESCE(surplus_amount, 0)) pipeline_surplus
                    FROM leads{where}
                    GROUP BY county ORDER BY cnt DESC""",
                params,
            ).fetchall()

            rows = conn.execute(
                f"""SELECT id, county, case_number, owner_name, property_address,
                           scheduled_sale_date, sale_date, ned_recorded_date,
                           opening_bid, surplus_amount, overbid_amount,
                           lender_name, ned_source, data_grade, ingestion_source,
                           updated_at
                    FROM leads{where}
                    ORDER BY county ASC,
                             COALESCE(surplus_amount, 0) DESC,
                             case_number ASC
                    LIMIT ? OFFSET ?""",
                params + [limit, offset],
            ).fetchall()
        finally:
            conn.close()

        return {
            "count": len(rows),
            "total": total,
            "limit": limit,
            "offset": offset,
            "county_breakdown": [dict(r) for r in county_rows],
            "leads": [dict(r) for r in rows],
        }

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(DB_EXECUTOR, _run)


@app.get("/api/leads/attorney-ready")
@limiter.limit("100/minute")
async def get_attorney_ready_leads(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List leads where attorney_packet_ready=1."""
    conn = _get_conn()
    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM leads WHERE attorney_packet_ready = 1"
        ).fetchone()[0]

        rows = conn.execute("""
            SELECT * FROM leads
            WHERE attorney_packet_ready = 1
            ORDER BY COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0) DESC
            LIMIT ? OFFSET ?
        """, [limit, offset]).fetchall()
    finally:
        conn.close()

    leads = [_row_to_safe(dict(r)) for r in rows]
    return {
        "count": len(leads),
        "total": total,
        "limit": limit,
        "offset": offset,
        "leads": leads,
    }


# ── POST /api/leads/{id}/attorney-ready — Set attorney_packet_ready ──

@app.post("/api/leads/{lead_id}/attorney-ready")
async def set_attorney_ready(lead_id: str, request: Request):
    """Mark a lead as attorney_packet_ready=1. Requires provenance + completeness."""
    _require_api_key(request)

    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", [lead_id]).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Lead not found.")

        lead = dict(row)

        # Provenance check
        provenance_count = conn.execute(
            "SELECT COUNT(*) FROM lead_provenance WHERE lead_id = ?", [lead_id]
        ).fetchone()[0]

        surplus = lead.get("estimated_surplus") or lead.get("surplus_amount") or 0
        errors = []
        if not lead.get("county"):
            errors.append("missing county")
        if not lead.get("case_number"):
            errors.append("missing case_number")
        if not lead.get("owner_name"):
            errors.append("missing owner_name")
        if not lead.get("sale_date"):
            errors.append("missing sale_date")
        if not (surplus and float(surplus) > 0):
            errors.append("estimated_surplus must be > 0")
        if provenance_count == 0:
            errors.append("no rows in lead_provenance (SHA256 provenance required)")

        if errors:
            raise HTTPException(
                status_code=400,
                detail=f"Lead not attorney-ready: {', '.join(errors)}",
            )

        conn.execute(
            "UPDATE leads SET attorney_packet_ready = 1 WHERE id = ?", [lead_id]
        )
        conn.commit()
    finally:
        conn.close()

    return {"status": "ok", "lead_id": lead_id, "attorney_packet_ready": True}


# ── GET /api/assets/{asset_id}/evidence — List evidence docs (attorney) ─────
#
# RBAC: requires role IN ('approved_attorney', 'admin').
# asset_id is the canonical FORECLOSURE:CO:{county}:{case_number} key.
# Cache-Control: no-store (covered by bfcache_hardening middleware).
#

@app.get("/api/assets/{asset_id:path}/evidence")
@limiter.limit("60/minute")
async def list_asset_evidence(asset_id: str, request: Request):
    """List evidence_documents for a captured GovSoft asset (attorney-gated, unlock-gated)."""
    user = _get_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if user.get("role") not in ("approved_attorney", "admin") and not _effective_admin(user, request):
        raise HTTPException(status_code=403, detail="Attorney or admin role required.")

    # Resolve lead_id from canonical asset_id (FORECLOSURE:CO:{COUNTY}:{case_number})
    conn = _get_conn()
    try:
        # Try direct asset_id lookup first, then canonical parse fallback
        lead_row = conn.execute(
            "SELECT id FROM leads WHERE id = ?", [asset_id]
        ).fetchone()
        if not lead_row:
            parts = asset_id.split(":")
            if len(parts) >= 4:
                county_key = parts[2].lower()
                case_num = ":".join(parts[3:])
                lead_row = conn.execute(
                    "SELECT id FROM leads WHERE lower(county) = ? AND case_number = ?",
                    [county_key, case_num],
                ).fetchone()
        rows = conn.execute(
            """SELECT id, asset_id, filename, doc_type, doc_family,
                      file_path, file_sha256, bytes, content_type, retrieved_ts
               FROM evidence_documents
               WHERE asset_id = ?
               ORDER BY doc_family, filename""",
            [asset_id],
        ).fetchall()
    finally:
        conn.close()

    # Enforce unlock gate (admin bypasses automatically inside _check_lead_unlocked)
    if lead_row:
        _check_lead_unlocked(user, lead_row["id"], doc_type="EVIDENCE_LIST", request=request)
    elif not _effective_admin(user, request):
        raise HTTPException(status_code=403, detail="Lead not found or not unlocked.")

    result = []
    for r in rows:
        d = dict(r)
        d["doc_family_label"] = DOC_FAMILY_LABELS.get(d.get("doc_family", ""), d.get("doc_family") or "Supporting Document")
        result.append(d)
    return result


# ── GET /api/evidence/{doc_id}/download — Secure evidence download ────────────
#
# RBAC: requires role IN ('approved_attorney', 'admin').
# Path traversal prevention: os.path.commonpath([resolved, vault_root]) == vault_root.
# File existence verified before streaming.
# MIME type from stored content_type (not hardcoded).
#

@app.get("/api/evidence/{doc_id}/download")
@limiter.limit("30/minute")
async def download_evidence_doc(doc_id: str, request: Request):
    """Securely stream a vault evidence document to an authorized attorney (unlock-gated)."""
    from fastapi.responses import FileResponse

    user = _get_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if user.get("role") not in ("approved_attorney", "admin") and not _effective_admin(user, request):
        raise HTTPException(status_code=403, detail="Attorney or admin role required.")

    conn = _get_conn()
    try:
        row = conn.execute(
            """SELECT file_path, filename, doc_type, content_type, asset_id
               FROM evidence_documents WHERE id = ?""",
            [doc_id],
        ).fetchone()
        # Resolve lead_id for unlock gate
        lead_id_for_gate = None
        if row and row["asset_id"]:
            lead_row = conn.execute(
                "SELECT id FROM leads WHERE id = ?", [row["asset_id"]]
            ).fetchone()
            if not lead_row:
                parts = (row["asset_id"] or "").split(":")
                if len(parts) >= 4:
                    county_key = parts[2].lower()
                    case_num = ":".join(parts[3:])
                    lead_row = conn.execute(
                        "SELECT id FROM leads WHERE lower(county) = ? AND case_number = ?",
                        [county_key, case_num],
                    ).fetchone()
            if lead_row:
                lead_id_for_gate = lead_row["id"]
    finally:
        conn.close()

    # Enforce unlock gate before path resolution
    if lead_id_for_gate:
        _check_lead_unlocked(user, lead_id_for_gate, doc_type=row["doc_type"] or "EVIDENCE_DOC", request=request)
    elif not _effective_admin(user, request):
        raise HTTPException(status_code=403, detail="Lead not found or not unlocked.")

    if not row:
        raise HTTPException(status_code=404, detail="Evidence document not found.")

    resolved = Path(row["file_path"]).resolve()
    vault_resolved = VAULT_ROOT.resolve()

    # Robust path containment — os.path.commonpath avoids startswith() bypass
    try:
        is_safe = (
            os.path.commonpath([str(resolved), str(vault_resolved)])
            == str(vault_resolved)
        )
    except ValueError:
        is_safe = False

    if not is_safe:
        raise HTTPException(status_code=403, detail="Path traversal denied.")

    if not resolved.exists():
        raise HTTPException(status_code=404, detail="File not found on disk.")

    mime = row["content_type"] or "application/octet-stream"
    return FileResponse(str(resolved), filename=row["filename"], media_type=mime)


# ── POST /api/assets/{asset_id}/heir-letter — Heir Notification PDF ──────────
#
# Generates a Colorado heir notification letter for estate cases (5 credits).
# Requires: unlocked lead, attorney role or admin.
#

@app.post("/api/assets/{asset_id:path}/heir-letter")
@limiter.limit("10/minute")
async def generate_heir_letter(asset_id: str, request: Request):
    """Generate a heir notification letter TEMPLATE PDF for an estate case (5 credits).

    Attorney or admin only. Lead must be unlocked by requesting user.
    Atomically deducts 5 credits (premium_dossier) inside a single BEGIN IMMEDIATE
    transaction that also writes unlock_spend_journal, transactions, and audit_log.
    PDF generation runs in PDF_EXECUTOR (CPU-bound — never blocks DB threads).

    HTTP responses:
      200  — PDF bytes (attorney) or PDF bytes (admin, no credit deduction)
      402  — Insufficient credits
      403  — Not attorney/admin, or lead not unlocked by this user
      404  — Lead not found
    """
    from fastapi.responses import Response as FastAPIResponse
    from verifuse_v2.core.heir_notification import generate_heir_notification_pdf

    # ── Auth — synchronous, reads request.state only ────────────────────────────
    user = _require_user(request)
    if user.get("role") not in ("approved_attorney", "admin") and not _effective_admin(user, request):
        raise HTTPException(status_code=403, detail="Attorney or admin role required.")

    user_id: str = user["user_id"]
    ip: str = request.client.host if request.client else ""
    is_admin: bool = _effective_admin(user, request)
    COST = 5  # premium_dossier

    # ── Step 1: Fetch lead (off event loop via _run_in_db) ──────────────────────
    def _fetch_lead():
        conn = _thread_conn()
        try:
            return conn.execute(
                """SELECT l.id, l.county, l.case_number, l.estimated_surplus,
                          l.overbid_amount, l.sale_date, l.owner_name,
                          l.property_address,
                          ar.has_deceased_indicator, ar.owner_mailing_address
                   FROM leads l
                   LEFT JOIN asset_registry ar ON ar.asset_id = l.id
                   WHERE l.id = ?""",
                [asset_id],
            ).fetchone()
        finally:
            conn.close()

    lead = await _run_in_db(_fetch_lead)
    if not lead:
        raise HTTPException(status_code=404, detail="Asset not found.")

    # ── Step 2: Asset-specific unlock check (skip for admin) ────────────────────
    if not is_admin:
        def _check_unlock():
            conn = _thread_conn()
            try:
                row = conn.execute(
                    "SELECT 1 FROM asset_unlocks "
                    "WHERE user_id = ? AND asset_id = ? LIMIT 1",
                    [user_id, asset_id],
                ).fetchone()
                if row:
                    return True
                if _HAS_LEAD_UNLOCKS:
                    row2 = conn.execute(
                        "SELECT 1 FROM lead_unlocks "
                        "WHERE user_id = ? AND lead_id = ? LIMIT 1",
                        [user_id, asset_id],
                    ).fetchone()
                    return bool(row2)
                return False
            finally:
                conn.close()

        if not await _run_in_db(_check_unlock):
            raise HTTPException(
                status_code=403,
                detail="Lead must be unlocked before generating a heir notification template.",
            )

    # ── Step 3: Atomic credit deduction + full billing audit ────────────────────
    # Single BEGIN IMMEDIATE transaction:
    #   a) FIFO ledger debit (unlock_ledger_entries)
    #   b) unlock_spend_journal rows (one per ledger entry touched — dispute proof)
    #   c) transactions row (type='premium_dossier')
    #   d) audit_log entry
    # Returns (charged: bool, balance_after: int)

    if not is_admin:
        def _charge():
            import uuid as _u
            conn = _thread_conn()
            now_epoch = _epoch_now()
            now_iso = datetime.now(timezone.utc).isoformat()
            txn_ref = str(_u.uuid4())  # opaque journal reference for this purchase

            try:
                conn.execute("BEGIN IMMEDIATE")

                debits = _fifo_spend(conn, user_id, COST)
                if debits is None:
                    conn.execute("ROLLBACK")
                    return False, 0

                balance_after = _ledger_balance(conn, user_id)

                # Billing audit — one journal row per ledger entry touched
                for d in debits:
                    conn.execute(
                        "INSERT INTO unlock_spend_journal "
                        "(id, unlock_id, ledger_entry_id, credits_consumed) "
                        "VALUES (?, ?, ?, ?)",
                        [str(_u.uuid4()), txn_ref, d["entry_id"], d["spent"]],
                    )

                # Transactions table — single row for the purchase event
                conn.execute(
                    "INSERT INTO transactions "
                    "(id, user_id, type, amount, credits, balance_after, "
                    "idempotency_key, created_at) "
                    "VALUES (?, ?, 'premium_dossier', 0, ?, ?, ?, ?)",
                    [str(_u.uuid4()), user_id, -COST, balance_after,
                     f"dossier:{user_id}:{asset_id}:{now_epoch}", now_iso],
                )

                # Audit log
                _audit_log(conn, user_id, "heir_letter_generated", {
                    "asset_id": asset_id,
                    "cost": COST,
                    "balance_after": balance_after,
                    "tier": user.get("tier"),
                    "txn_ref": txn_ref,
                }, ip)

                conn.execute("COMMIT")
                return True, balance_after

            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            finally:
                conn.close()

        charged, balance_after = await _run_in_db(_charge)
        if not charged:
            raise HTTPException(
                status_code=402,
                detail=f"Insufficient credits. {COST} credits required for heir notification template.",
            )

    # ── Step 4: Generate PDF in dedicated PDF_EXECUTOR (CPU-bound) ──────────────
    # If generation fails after credits were charged, refund atomically.
    surplus = float(lead["estimated_surplus"] or lead["overbid_amount"] or 0)

    def _make_pdf():
        return generate_heir_notification_pdf(
            owner_name=lead["owner_name"] or "Unknown Owner",
            property_address=lead["property_address"] or "",
            county=lead["county"] or "",
            case_number=lead["case_number"] or asset_id,
            surplus_amount=surplus,
            sale_date=lead["sale_date"] or "",
            mailing_address=lead["owner_mailing_address"] or "",
        )

    loop = asyncio.get_running_loop()
    try:
        pdf_bytes = await loop.run_in_executor(PDF_EXECUTOR, _make_pdf)
    except Exception as pdf_exc:
        log.error("[heir-letter] PDF generation failed for %s: %s", asset_id, pdf_exc)
        # Refund the credits — re-add COST to the newest non-expired ledger entry
        if not is_admin:
            def _refund():
                import uuid as _u
                conn = _thread_conn()
                now = _epoch_now()
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    # Find the ledger entry that still has room (or just INSERT a refund entry)
                    conn.execute(
                        "INSERT INTO unlock_ledger_entries "
                        "(id, user_id, source, qty_total, qty_remaining, "
                        "purchased_ts, expires_ts, tier_at_purchase) "
                        "VALUES (?, ?, 'refund', ?, ?, ?, NULL, ?)",
                        [str(_u.uuid4()), user_id, COST, COST,
                         now, user.get("tier", "")],
                    )
                    _audit_log(conn, user_id, "heir_letter_refunded", {
                        "asset_id": asset_id,
                        "cost": COST,
                        "reason": str(pdf_exc)[:200],
                    }, ip)
                    conn.execute("COMMIT")
                except Exception as re:
                    try:
                        conn.execute("ROLLBACK")
                    except Exception:
                        pass
                    log.error("[heir-letter] Refund failed for %s: %s", user_id, re)
                finally:
                    conn.close()
            await _run_in_db(_refund)
        raise HTTPException(
            status_code=503,
            detail="PDF generation temporarily unavailable. Credits have been refunded.",
        ) from pdf_exc

    filename = f"heir_template_{asset_id.replace(':', '_')}.pdf"
    return FastAPIResponse(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
