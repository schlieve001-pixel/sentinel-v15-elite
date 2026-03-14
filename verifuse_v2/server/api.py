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
import re
import sqlite3
import string
import time as _time
import uuid
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from verifuse_v2.utils.logging_setup import setup_logging, request_id_var

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
setup_logging(level=os.environ.get("LOG_LEVEL", "INFO"))

# ── Dev environment flag (NEVER true in production) ──────────────────
# Set VERIFUSE_ENV=development in .env to enable dev-only bypasses.
# Production must not set this variable (defaults to non-development).
_IS_DEV = os.environ.get("VERIFUSE_ENV", "production").lower() == "development"

# ── Pricing & entitlements (canonical source) ─────────────────────────
from verifuse_v2.server.pricing import (
    CREDIT_COSTS,
    FIRST_MONTH_BONUS,
    FOUNDERS_MAX_SLOTS,
    INVESTIGATION_PACK,
    SIGNUP_BONUS_CREDITS,
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
    conn.execute("PRAGMA cache_size = -65536")      # 64MB page cache
    conn.execute("PRAGMA mmap_size = 268435456")    # 256MB memory-mapped I/O
    conn.execute("PRAGMA temp_store = MEMORY")      # temp tables in RAM
    return conn


def _with_busy_retry(fn, *args, _retries=3, **kwargs):
    """Retry a callable on SQLite 'locked' errors with exponential backoff."""
    for attempt in range(_retries):
        try:
            return fn(*args, **kwargs)
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < _retries - 1:
                wait = 0.05 * (2 ** attempt)
                log.warning("db_busy_retry", extra={"attempt": attempt + 1, "wait_s": wait})
                _time.sleep(wait)
            else:
                raise


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
    """Extract client IP — uses direct connection to prevent X-Forwarded-For spoofing.

    Caddy/nginx sets X-Real-IP reliably; X-Forwarded-For is client-controllable.
    For rate limiting, we trust the real connection IP (Caddy terminates TLS).
    """
    # Prefer X-Real-IP set by Caddy (not client-forgeable behind reverse proxy)
    ip = request.headers.get("X-Real-IP", "").strip()
    if not ip and request.client:
        ip = request.client.host
    return ip or "unknown"


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


def _redact_email(addr: str) -> str:
    """Redact email for safe logging: keep first 2 chars + domain."""
    try:
        local, domain = addr.rsplit("@", 1)
        return local[:2] + "***@" + domain
    except Exception:
        return "***@***"


_VF_EMAIL_LOGO_URL = os.environ.get("VERIFUSE_LOGO_URL", "[VERIFUSE_LOGO_URL]")


def _build_html_email(title: str, body_html: str) -> str:
    """Return branded HTML email template with logo placeholder and VeriFuse color scheme."""
    logo_tag = (
        f'<img src="{_VF_EMAIL_LOGO_URL}" alt="VeriFuse" style="height:40px;margin-bottom:8px;" /><br>'
        if _VF_EMAIL_LOGO_URL != "[VERIFUSE_LOGO_URL]"
        else '<span style="font-size:1.4rem;font-weight:700;color:#22c55e;">VeriFuse</span><br>'
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#0f172a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0f172a;padding:40px 0;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#1e293b;border-radius:12px;overflow:hidden;border:1px solid #334155;">
        <tr>
          <td style="background:#0f172a;padding:24px 32px;border-bottom:1px solid #334155;text-align:center;">
            {logo_tag}
            <span style="font-size:0.75rem;color:#64748b;letter-spacing:0.05em;">VERIFIED SURPLUS INTELLIGENCE</span>
          </td>
        </tr>
        <tr>
          <td style="padding:32px;">
            <h1 style="color:#e2e8f0;font-size:1.2rem;margin:0 0 16px;">{title}</h1>
            {body_html}
            <hr style="border:none;border-top:1px solid #334155;margin:24px 0;">
            <p style="color:#64748b;font-size:0.75rem;margin:0;">
              VeriFuse Technologies LLC · Colorado Foreclosure Surplus Intelligence<br>
              support@verifuse.tech · <a href="https://verifuse.tech" style="color:#22c55e;text-decoration:none;">verifuse.tech</a>
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _send_email(to: str, subject: str, body: str, html_body: str | None = None) -> None:
    """Send email via SendGrid → SES → SMTP → log fallback.

    Reads VERIFUSE_EMAIL_MODE env var:
      sendgrid — SendGrid API (preferred production); enforces daily cap + cooldown
      ses      — AWS SES; falls through to SMTP on failure
      smtp     — SMTP directly; falls through to log on failure
      log      — log only (default / dev)

    Always sends from support@verifuse.tech.
    Never logs the API key or full email body in production.
    """
    FROM = "support@verifuse.tech"
    REGION = os.environ.get("AWS_REGION", "us-west-2")
    mode = os.environ.get("VERIFUSE_EMAIL_MODE", "log").lower()

    if mode == "sendgrid":
        sg_key = os.environ.get("SENDGRID_API_KEY", "")
        if not sg_key:
            log.error("[email] SENDGRID_API_KEY not set — cannot deliver")
            raise RuntimeError("Email delivery not configured")
        # Daily cap: 5 sends per address per day (sha256 only — never store plain email)
        email_hash = hashlib.sha256(to.lower().strip().encode()).hexdigest()
        today_start_ts = int(datetime(
            *datetime.now(timezone.utc).date().timetuple()[:3],
            tzinfo=timezone.utc,
        ).timestamp())
        try:
            _ecn = _get_conn()
            try:
                count_row = _ecn.execute(
                    "SELECT COUNT(*) AS cnt FROM email_log WHERE email_hash = ? AND sent_ts >= ?",
                    [email_hash, today_start_ts],
                ).fetchone()
                if count_row and count_row["cnt"] >= 5:
                    raise HTTPException(429, detail="Daily email limit reached. Try again tomorrow.")
                _ecn.execute(
                    "INSERT INTO email_log (email_hash, sent_ts) VALUES (?, ?)",
                    [email_hash, int(datetime.now(timezone.utc).timestamp())],
                )
                _ecn.commit()
            finally:
                _ecn.close()
        except HTTPException:
            raise
        except Exception as _cap_err:
            log.warning("[email] email_log cap check unavailable: %s", type(_cap_err).__name__)
        try:
            import httpx
            content = [{"type": "text/plain", "value": body}]
            if html_body:
                content.append({"type": "text/html", "value": html_body})
            resp = httpx.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={
                    "Authorization": f"Bearer {sg_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "personalizations": [{"to": [{"email": to}]}],
                    "from": {"email": FROM, "name": "VeriFuse Technologies LLC"},
                    "subject": subject,
                    "content": content,
                },
                timeout=10,
            )
            log.info("[email] SendGrid → %s status=%d", _redact_email(to), resp.status_code)
            if resp.status_code >= 400:
                raise RuntimeError(f"SendGrid delivery failed (status={resp.status_code})")
            return
        except HTTPException:
            raise
        except RuntimeError:
            raise
        except Exception as e:
            log.error("[email] SendGrid send failed: %s", type(e).__name__)
            raise RuntimeError("Email delivery failed") from e

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

    log.info("EMAIL [%s → %s] %s | %s", FROM, _redact_email(to), subject, body[:300])


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
    sale_status: Optional[str] = None      # PRE_SALE | POST_SALE | UNKNOWN (conservative — no timeline implied)
    timeline_flags: Optional[list] = None  # Informational only — require attorney verification before filing
    ready_to_file: Optional[bool] = None   # True only when all required fields present + restriction ended
    grade_reasons: Optional[list] = None   # Human-readable explanations of current grade
    # Phase 4: verification pipeline state (6-stage)
    verification_state: Optional[str] = None  # RAW|EXTRACTED|EVIDENCE_ATTACHED|MATH_VERIFIED|ATTORNEY_READY|PUBLISHED
    pool_source: Optional[str] = None     # VOUCHER|LEDGER|HTML_MATH|AI_VERIFIED|TRIPLE_VERIFIED|UNVERIFIED
    verification_tier: Optional[str] = None  # TRIPLE_VERIFIED|AI_VERIFIED|HTML_MATH|UNVERIFIED
    verification_confidence: Optional[float] = None  # 0.0–1.0 from SOTA engine
    # Phase 5: two-tier net-to-owner display
    display_tier: Optional[str] = None        # POTENTIAL | VERIFIED
    net_to_owner_label: Optional[str] = None  # "VERIFIED NET TO OWNER" | "OVERBID POOL (Potential)"
    # EPIC 3: explainable confidence
    confidence_reasons: Optional[list] = None
    missing_inputs: Optional[list] = None
    # A3: lien search state
    lien_search_performed: Optional[bool] = None  # True when lien_records searched or LIENOR_TAB snapshot exists


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


def _compute_sale_status(row: dict) -> tuple:
    """Conservative sale status + timeline_flags[].

    Returns (status, flags[]) — 3 states only: PRE_SALE | POST_SALE | UNKNOWN.
    Flags are informational — require attorney verification before any filing action.
    Never implies legal deadlines are confirmed.
    """
    today = datetime.now(timezone.utc).date()
    sale = row.get("sale_date")
    if not sale:
        return "UNKNOWN", ["sale_date_missing — verify with county public trustee"]
    try:
        sale_dt = date.fromisoformat(str(sale)[:10])
    except (ValueError, TypeError):
        return "UNKNOWN", ["sale_date_unparseable — verify with county public trustee"]
    if sale_dt > today:
        return "PRE_SALE", []

    flags = []
    restriction_end = _compute_restriction_end(sale)
    deadline = row.get("claim_deadline")

    if restriction_end:
        if restriction_end > today:
            flags.append(
                f"restriction_period_active_until_{restriction_end.isoformat()} "
                f"— verify C.R.S. § 38-38-302 before contacting owner"
            )
        else:
            flags.append(
                f"restriction_period_ended_{restriction_end.isoformat()} "
                f"— verify redemption status with public trustee"
            )

    if deadline:
        try:
            dl = date.fromisoformat(str(deadline)[:10])
            if dl < today:
                flags.append(
                    f"statutory_deadline_may_have_passed_{dl.isoformat()} "
                    f"— requires legal review before filing"
                )
            else:
                flags.append(
                    f"statutory_deadline_estimated_{dl.isoformat()} "
                    f"— verify with public trustee before relying on this date"
                )
        except (ValueError, TypeError):
            flags.append("claim_deadline_unparseable — verify with county public trustee")
    else:
        flags.append("claim_deadline_unconfirmed — verify with county public trustee")

    return "POST_SALE", flags


def _compute_confidence(row: dict) -> tuple:
    """Rule-based confidence scorer. Returns (score, reasons[], missing[]).

    Points:
      +35  pool_source == VOUCHER (authoritative overbid voucher)
      +25  pool_source == LEDGER  (confirmed ledger document)
      +10  pool_source == HTML_MATH (unverified, computed from HTML)
      +20  total_debt confirmed and > 0
      +20  sale_date present
      +15  property_address present
      +15  owner_name present

    Caps:
      ≤50%  if total_debt missing
      ≤60%  if pool_source == UNVERIFIED
    """
    pts = 0
    reasons = []
    missing = []

    # Pool source
    pool_source = row.get("pool_source", "UNVERIFIED")
    if pool_source == "VOUCHER":
        pts += 35
        reasons.append("+35: pool sourced from overbid voucher (authoritative)")
    elif pool_source == "LEDGER":
        pts += 25
        reasons.append("+25: pool sourced from confirmed ledger document")
    elif pool_source == "HTML_MATH":
        pts += 10
        reasons.append("+10: pool computed from HTML math (unverified source)")
    else:
        missing.append("pool_source")
        reasons.append("+0: pool_source unverified — no voucher or proven inputs")

    # Total debt
    debt = _safe_float(row.get("total_debt"))
    if debt and debt > 0:
        pts += 20
        reasons.append("+20: total_indebtedness confirmed")
    else:
        missing.append("total_debt")

    # Sale date
    if row.get("sale_date"):
        pts += 20
        reasons.append("+20: sale_date present")
    else:
        missing.append("sale_date")

    # Property address
    if row.get("property_address"):
        pts += 15
        reasons.append("+15: property_address present")
    else:
        missing.append("property_address")

    # Owner name
    if row.get("owner_name"):
        pts += 15
        reasons.append("+15: owner_name present")
    else:
        missing.append("owner_name")

    # Caps
    if not debt or debt <= 0:
        pts = min(pts, 50)
        reasons.append("cap@50%: total_debt missing — math unverified")
    elif pool_source == "UNVERIFIED":
        pts = min(pts, 60)
        reasons.append("cap@60%: pool_source unverified")

    return pts / 100.0, reasons, missing


def _compute_ready_to_file(row: dict) -> bool:
    """True only when all required fields are present, surplus meets threshold, AND status is ACTIONABLE."""
    surplus = _safe_float(row.get("overbid_amount")) or _safe_float(row.get("surplus_amount"))
    required = [
        row.get("sale_date"),
        surplus,
        row.get("owner_name"),
        row.get("property_address"),
    ]
    if any(not v for v in required):
        return False
    # Below $500 overbid is not worth filing — costs exceed recovery
    if surplus < 500:
        return False
    return _compute_status(row) == "ACTIONABLE"


def _compute_grade_reasons(row: dict) -> list:
    """Human-readable list explaining why a lead has its current grade / data gaps."""
    reasons = []
    if not row.get("sale_date"):
        reasons.append("Sale date not available")
    debt = _safe_float(row.get("total_debt"))
    if not debt or debt <= 0:
        reasons.append("Total indebtedness not extracted — confidence capped at 50%")
    if not row.get("owner_name"):
        reasons.append("Owner name not retrieved — assessor lookup needed")
    if not row.get("property_address"):
        reasons.append("Property address not retrieved — assessor lookup needed")
    # Minimum practical surplus threshold — below $500 the overbid is below filing cost
    surplus = (
        _safe_float(row.get("overbid_amount"))
        or _safe_float(row.get("surplus_amount"))
        or _safe_float(row.get("estimated_surplus"))
        or 0.0
    )
    if surplus > 0 and surplus < 500:
        reasons.append(f"Overbid ${surplus:.2f} is below minimum practical claim threshold ($500) — filing costs likely exceed recovery")
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


def _ts_to_iso(ts) -> Optional[str]:
    """Convert Unix integer timestamp to ISO 8601 string. DB stays Unix — API layer converts."""
    if ts is None:
        return None
    try:
        return datetime.utcfromtimestamp(float(ts)).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, OSError, TypeError, OverflowError):
        return None


def _safe_age_days(ts_str) -> Optional[int]:
    """Safely compute days since timestamp. Returns None for NULL, pre-2020, or unparseable."""
    if not ts_str:
        return None
    try:
        s = str(ts_str)[:10]
        dt = date.fromisoformat(s)
        # Pre-2020 dates are clearly DB defaults or errors
        if dt.year < 2020:
            return None
        today = datetime.now(timezone.utc).date()
        days = (today - dt).days
        return days if 0 <= days <= 3650 else None  # Cap at 10 years for sanity
    except (ValueError, TypeError):
        return None


def _compute_verification_state(row: dict) -> str:
    """6-stage verification pipeline state. Supplements data_grade — does not replace it.

    Stages: RAW → EXTRACTED → EVIDENCE_ATTACHED → MATH_VERIFIED → ATTORNEY_READY → PUBLISHED
    """
    grade = (row.get("data_grade") or "").upper()
    if grade == "REJECT":
        return "RAW"

    # Must have at least overbid/surplus extracted to move past RAW
    has_extraction = bool(
        _safe_float(row.get("overbid_amount")) or _safe_float(row.get("surplus_amount"))
    )
    if not has_extraction:
        return "RAW"

    # Evidence attached: voucher doc present (pool_source VOUCHER/LEDGER) or explicit voucher_doc_id
    pool_source = row.get("pool_source", "UNVERIFIED")
    has_evidence = pool_source in ("VOUCHER", "LEDGER")

    # Math verified: audit_grade A or B
    audit_grade = (row.get("audit_grade") or "").upper()
    math_ok = audit_grade in ("A", "B")

    # All required fields for attorney readiness
    all_required = all([
        row.get("sale_date"),
        row.get("owner_name"),
        row.get("property_address"),
        _safe_float(row.get("overbid_amount")) or _safe_float(row.get("surplus_amount")),
    ])

    # READY_TO_FILE: all ATTORNEY_READY requirements + lien search performed + surplus_verified
    _lien_ok = bool(row.get("lien_search_performed"))
    _surplus_ver = row.get("pool_source") in ("VOUCHER", "LEDGER")

    if all_required and math_ok and has_evidence and _lien_ok and _surplus_ver:
        return "READY_TO_FILE"
    if all_required and math_ok and has_evidence:
        return "ATTORNEY_READY"
    if math_ok:
        return "MATH_VERIFIED"
    if has_evidence:
        return "EVIDENCE_ATTACHED"
    return "EXTRACTED"


def _admin_override_log(
    conn,
    admin_id: str,
    action: str,
    reason_code: str,
    target_lead_id: Optional[str] = None,
    target_user_id: Optional[str] = None,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
) -> None:
    """Write to admin_override_log. Requires non-empty reason_code."""
    if not reason_code or not reason_code.strip():
        raise HTTPException(422, detail="reason_code is required for admin write operations")
    try:
        conn.execute(
            """INSERT INTO admin_override_log
               (admin_user_id, target_lead_id, target_user_id, action,
                reason_code, old_value, new_value)
               VALUES (?,?,?,?,?,?,?)""",
            [admin_id, target_lead_id, target_user_id, action,
             reason_code.strip()[:500], old_value, new_value],
        )
    except Exception:
        # Table may not exist yet (pre-migration run) — fall through gracefully
        pass


def _extract_city(address: Optional[str], county: Optional[str]) -> str:
    if not address:
        return f"{county or 'CO'}, CO"
    parts = [p.strip() for p in address.split(",")]
    if len(parts) >= 2:
        return ", ".join(parts[-2:]).strip()
    return f"{county or 'CO'}, CO"


def _round_surplus(amount: Optional[float]) -> Optional[float]:
    if amount is None:
        return None
    if amount <= 0:
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
    _surp_a = _safe_float(row.get("surplus_amount"))
    _surp_e = _safe_float(row.get("estimated_surplus"))
    _surp_o = _safe_float(row.get("overbid_amount"))
    surplus = _surp_a or _surp_e or _surp_o or 0.0
    debt = _safe_float(row.get("total_debt")) or 0.0
    conf, conf_reasons, conf_missing = _compute_confidence(row)
    status = _compute_status(row)
    sale_status, timeline_flags = _compute_sale_status(row)
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

    # Data age — use safe helper to avoid garbage values for epoch defaults / pre-2020 dates
    data_age_days = _safe_age_days(row.get("updated_at"))

    data_grade = (row.get("data_grade") or "").upper()
    # REJECT leads: zero out surplus so they never appear claimable
    if data_grade == "REJECT":
        surplus = 0.0
    # surplus_verified: True only when pool_source is authoritative
    pool_src = row.get("pool_source", "UNVERIFIED")
    verified = data_grade in ("GOLD", "SILVER") and conf >= 0.7 and pool_src in ("VOUCHER", "LEDGER")
    # If all surplus fields are NULL/zero and pool source is not verified, surplus is truly unknown
    _surplus_unknown = (not _surp_a and not _surp_e and not _surp_o and pool_src == "UNVERIFIED")
    if _surplus_unknown and data_grade not in ("REJECT",):
        surplus = None  # Genuine unknown — do not show $0.00

    pk = _compute_preview_key(row) if is_preview_eligible(row) else None
    ready = _compute_ready_to_file(row)
    grade_reasons = _compute_grade_reasons(row)

    # Phase 4: verification state
    _computed_vs = _compute_verification_state(row)
    # Persist if DB value differs (non-blocking — best-effort)
    if row.get("verification_state") != _computed_vs:
        try:
            _bg_conn = _get_conn()
            _bg_conn.execute(
                "UPDATE leads SET verification_state=? WHERE id=?",
                [_computed_vs, row.get("id")]
            )
            _bg_conn.commit()
            _bg_conn.close()
        except Exception:
            pass
    vstate = _computed_vs

    # Phase 5: two-tier net-to-owner display label
    pool_source = pool_src  # already computed above
    _has_verified_net = (
        data_grade == "GOLD"
        and _safe_float(row.get("trustee_fees"))
        and vstate in ("ATTORNEY_READY", "PUBLISHED")
    )
    display_tier = "VERIFIED" if _has_verified_net else "POTENTIAL"
    net_to_owner_label = "VERIFIED NET TO OWNER" if _has_verified_net else "OVERBID POOL (Potential)"

    return SafeAsset(
        asset_id=row.get("id"),
        county=row.get("county"),
        state="CO",
        case_number=row.get("case_number"),
        asset_type="FORECLOSURE_SURPLUS",
        estimated_surplus=_round_surplus(surplus) if surplus is not None else None,
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
        registry_asset_id=(
            f"FORECLOSURE:CO:{row['county'].upper()}:{row['case_number']}"
            if row.get("county") and row.get("case_number") else None
        ),
        sale_status=sale_status,
        timeline_flags=timeline_flags,
        ready_to_file=ready,
        grade_reasons=grade_reasons,
        verification_state=vstate,
        pool_source=pool_source,
        verification_tier=row.get("verification_tier") or (
            "TRIPLE_VERIFIED" if pool_source == "TRIPLE_VERIFIED"
            else "AI_VERIFIED" if pool_source == "AI_VERIFIED"
            else "HTML_MATH" if pool_source == "HTML_MATH"
            else "UNVERIFIED"
        ),
        verification_confidence=_safe_float(row.get("verification_confidence")),
        display_tier=display_tier,
        net_to_owner_label=net_to_owner_label,
        confidence_reasons=conf_reasons,
        missing_inputs=conf_missing,
    ).model_dump()


def _table_exists_conn(conn, table: str) -> bool:
    """Check if a table exists in the given connection."""
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [table]
    ).fetchone() is not None


def _compute_opportunity_score(lead_row: dict, conn) -> int:
    """Score 0-10 based on surplus size, deadline proximity, grade, and lien burden."""
    score = 0
    surplus = lead_row.get("overbid_amount") or lead_row.get("surplus_amount") or lead_row.get("estimated_surplus") or 0
    try:
        surplus = float(surplus)
    except (ValueError, TypeError):
        surplus = 0.0

    if surplus >= 50000:
        score += 3
    elif surplus >= 20000:
        score += 2
    elif surplus >= 5000:
        score += 1

    # Deadline proximity
    sale_date = lead_row.get("sale_date")
    if sale_date:
        try:
            from datetime import date as _date
            if isinstance(sale_date, str):
                sd = _date.fromisoformat(sale_date[:10])
            else:
                sd = sale_date
            # Colorado: 75 days after sale for redemption, then 1 year for surplus claim
            claim_deadline = sd + timedelta(days=75 + 365)
            days_left = (claim_deadline - _date.today()).days
            if 90 < days_left <= 365:
                score += 2
            elif days_left <= 90:
                score += 3
        except Exception:
            pass

    grade = lead_row.get("data_grade", "")
    if grade == "GOLD":
        score += 2
    elif grade == "SILVER":
        score += 1

    # No open liens = +1
    asset_id = lead_row.get("id", "")
    try:
        lien_row = conn.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) as total FROM lien_records WHERE asset_id = ? AND is_open = 1",
            [asset_id]
        ).fetchone()
        if lien_row and (lien_row["total"] or 0) == 0:
            score += 1
    except Exception:
        pass

    return min(10, score)


def _row_to_full(row: dict, conn=None, unlocked_by_me: bool = True, is_admin: bool = False) -> dict:
    """Convert a leads row to FullAsset dict. NULL-safe.

    Optional conn enables quality_badge and opportunity_score computation.
    unlocked_by_me / is_admin control owner_name masking (EPIC 1C).
    """
    safe = _row_to_safe(row)
    # Exact (unrounded) surplus for authenticated users — override the $100-rounded preview value
    exact_surplus = (
        _safe_float(row.get("surplus_amount"))
        or _safe_float(row.get("estimated_surplus"))
        or _safe_float(row.get("overbid_amount"))
    )

    owner_name = row.get("owner_name")
    # EPIC 1C: mask owner_name for locked, non-admin users
    if not unlocked_by_me and not is_admin and owner_name:
        parts = owner_name.split()
        if len(parts) >= 2:
            owner_name = parts[0][0] + ". " + parts[-1]
        else:
            owner_name = owner_name[0] + "." if owner_name else owner_name

    safe.update({
        "estimated_surplus": round(exact_surplus, 2) if exact_surplus is not None else None,
        "owner_name": owner_name,
        "property_address": row.get("property_address"),
        "winning_bid": _safe_float(row.get("winning_bid")),
        "total_debt": _safe_float(row.get("total_debt")),
        "total_indebtedness": _safe_float(row.get("total_debt")),
        "surplus_amount": _safe_float(row.get("surplus_amount")),
        "overbid_amount": _safe_float(row.get("overbid_amount")),
        "recorder_link": row.get("recorder_link"),
        "verification_state": row.get("verification_state", "RAW"),
        "surplus_verified": row.get("pool_source", "UNVERIFIED") in ("VOUCHER", "LEDGER"),
    })

    # EPIC 2D: quality badge and opportunity score (require conn)
    if conn is not None:
        lead_id = row.get("id", "")
        county = (row.get("county") or "").upper()
        case_number = (row.get("case_number") or "").upper()
        asset_id_canonical = f"FORECLOSURE:CO:{county}:{case_number}"

        ev_count = 0
        snap_count = 0
        try:
            if _table_exists_conn(conn, "evidence_documents"):
                ev_count = conn.execute(
                    "SELECT COUNT(*) FROM evidence_documents WHERE asset_id = ?", [lead_id]
                ).fetchone()[0]
        except Exception:
            pass
        try:
            if _table_exists_conn(conn, "html_snapshots"):
                snap_count = conn.execute(
                    "SELECT COUNT(*) FROM html_snapshots WHERE asset_id = ?", [asset_id_canonical]
                ).fetchone()[0]
        except Exception:
            pass

        if ev_count > 0:
            quality_badge = "VERIFIED"
        elif snap_count > 0:
            quality_badge = "PARTIAL"
        else:
            quality_badge = "ESTIMATED"

        safe["quality_badge"] = quality_badge
        safe["opportunity_score"] = _compute_opportunity_score(row, conn)

        # A2: GOLD display downgrade if no evidence or low confidence
        _display_grade = row.get("data_grade")
        _conf_score = _safe_float(row.get("confidence_score")) or 0.0
        if _display_grade == "GOLD" and ev_count == 0 and snap_count == 0:
            _display_grade = "SILVER"
            log.warning("[A2] Lead %s: GOLD with zero evidence — downgrading display to SILVER", row.get("id"))
        elif _display_grade == "GOLD" and _conf_score < 0.65:
            _display_grade = "SILVER"
            log.warning("[A2] Lead %s: GOLD with confidence_score %.2f < 0.65 — downgrading display to SILVER", row.get("id"), _conf_score)
        safe["display_grade"] = _display_grade

        # A3: lien_search_performed — True if any lien_records exist OR LIENOR_TAB snapshot exists
        _lien_search_performed = False
        try:
            _lien_ct = conn.execute(
                "SELECT COUNT(*) FROM lien_records WHERE asset_id = ?", [row.get("id", "")]
            ).fetchone()[0]
            _lienor_snap = conn.execute(
                "SELECT COUNT(*) FROM html_snapshots WHERE asset_id = ? AND snapshot_type = 'LIENOR_TAB'",
                [asset_id_canonical]
            ).fetchone()[0]
            _lien_search_performed = (_lien_ct > 0 or _lienor_snap > 0)
        except Exception:
            pass
        safe["lien_search_performed"] = _lien_search_performed
    else:
        safe["quality_badge"] = "ESTIMATED"
        safe["opportunity_score"] = 0
        safe["display_grade"] = row.get("data_grade")
        safe["lien_search_performed"] = None

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
    """Check x-verifuse-api-key header for admin/scraper endpoints.
    SECURITY: Fail-closed — if key is not configured, deny all access.
    """
    if not VERIFUSE_API_KEY:
        raise HTTPException(status_code=500, detail="API key not configured on server.")
    key = request.headers.get("x-verifuse-api-key", "")
    # Constant-time compare to prevent timing attacks
    import hmac as _hmac
    if not _hmac.compare_digest(key, VERIFUSE_API_KEY):
        raise HTTPException(status_code=403, detail="Invalid or missing API key.")


def _require_admin_or_api_key(request: Request) -> None:
    """Check API key OR JWT admin flag. For admin endpoints that accept either."""
    # Try API key first — constant-time compare prevents timing attacks
    key = request.headers.get("x-verifuse-api-key", "")
    if VERIFUSE_API_KEY and hmac.compare_digest(key, VERIFUSE_API_KEY):
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

def _rate_limit_key(request: Request) -> str:
    """Rate limit key uses X-Real-IP (set by Caddy) to prevent X-Forwarded-For spoofing."""
    return request.headers.get("X-Real-IP", "").strip() or (request.client.host if request.client else "unknown")

limiter = Limiter(key_func=_rate_limit_key, default_limits=["100/minute"])

# ── App ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="VeriFuse V2 — Titanium API",
    version="4.2.0",
    description="Colorado Surplus Intelligence Platform — Sprint 12",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(Exception)
async def _global_exc_handler(request: Request, exc: Exception):
    import traceback as _tb
    req_id = request_id_var.get("unknown")
    log.error("unhandled_exception", extra={
        "request_id": req_id,
        "method": request.method,
        "path": request.url.path,
        "exc_type": type(exc).__name__,
        "traceback": _tb.format_exc(),
    })
    return JSONResponse(status_code=500, content={
        "error": {"code": "INTERNAL_ERROR",
                  "message": "An unexpected error occurred",
                  "request_id": req_id}
    })


@app.exception_handler(HTTPException)
async def _http_exc_handler(request: Request, exc: HTTPException):
    req_id = request_id_var.get("unknown")
    return JSONResponse(status_code=exc.status_code, content={
        "error": {"code": str(exc.status_code), "message": exc.detail, "request_id": req_id}
    })

_CORS_ORIGINS = [
    "https://verifuse.tech",
    "https://www.verifuse.tech",
]
if _IS_DEV:
    _CORS_ORIGINS += ["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "x-verifuse-api-key", "X-Verifuse-Simulate"],
    expose_headers=["Content-Disposition"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


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


_SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "X-API-Version": "4.2.0",
    "X-Robots-Tag": "noindex, nofollow, nosnippet, noarchive",
    "Content-Security-Policy": (
        "default-src 'none'; "
        "script-src 'self'; "
        "connect-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; "
        "font-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'"
    ),
}

# ── Anti-scraping: blocked User-Agent patterns ─────────────────────
_SCRAPER_UA_PATTERNS = re.compile(
    r"(?i)("
    r"python-requests|python-urllib|aiohttp|httpx|pycurl|"
    r"scrapy|playwright|puppeteer|selenium|webdriver|headless|"
    r"curl/|wget/|go-http-client|java/|okhttp|"
    r"libwww-perl|perl/|ruby|php/|"
    r"ahrefsbot|semrushbot|mj12bot|dotbot|blexbot|petalbot|"
    r"baiduspider|yandexbot|rogerbot|exabot|seznambot|"
    r"nikto|sqlmap|masscan|zgrab|nuclei|nmap|"
    r"scraperapi|scrapinghub|luminati|brightdata|"
    r"dataforseo|spiderbro|webcopier|httrack|"
    r"postman|insomnia"
    r")"
)

# Paths that legitimate API clients use — skip UA check for these when
# the request carries a valid API key header (checked by other middleware)
_API_KEY_HEADER = "x-verifuse-api-key"

# IPs to shadow-block (populated at runtime by _flag_scraper_ip)
_SHADOW_BLOCKED: dict[str, float] = {}
_SHADOW_BLOCK_TTL = 3600  # 1 hour

# IPs that are never shadow-blocked (localhost, internal health checks)
_SHADOW_BLOCK_EXEMPT = {"127.0.0.1", "::1", "localhost"}


def _flag_scraper_ip(ip: str) -> None:
    """Add IP to shadow-block list for 1 hour."""
    if ip in _SHADOW_BLOCK_EXEMPT:
        return
    _SHADOW_BLOCKED[ip] = _time.time() + _SHADOW_BLOCK_TTL
    log.warning("anti_scrape.shadow_block", extra={"ip": ip})


@app.middleware("http")
async def request_lifecycle_middleware(request: Request, call_next):
    """Attach request ID, timing, and security headers to every response."""
    # Sanitize user-supplied X-Request-ID to prevent log injection
    _raw_rid = request.headers.get("X-Request-ID", "")
    req_id = re.sub(r"[^a-zA-Z0-9\-]", "", _raw_rid)[:32] or str(uuid.uuid4())[:8]
    request_id_var.set(req_id)
    t0 = _time.perf_counter()
    log.debug("req.start", extra={"method": request.method, "path": request.url.path})
    response = await call_next(request)
    elapsed_ms = int((_time.perf_counter() - t0) * 1000)
    response.headers["X-Request-ID"] = req_id
    response.headers["X-Response-Time"] = f"{elapsed_ms}ms"
    for h, v in _SECURITY_HEADERS.items():
        response.headers.setdefault(h, v)
    log.info("req.end", extra={
        "method": request.method, "path": request.url.path,
        "status": response.status_code, "ms": elapsed_ms,
    })
    return response


@app.middleware("http")
async def anti_scrape_middleware(request: Request, call_next):
    """Block known scraper/bot user agents and shadow-blocked IPs.

    Policy:
    - Public API endpoints (no auth) are fully protected.
    - Requests bearing x-verifuse-api-key bypass UA check (legitimate integrations).
    - Shadow-blocked IPs receive 404 (stealth block, no signal to attacker).
    - Known scraper UAs on /api/* receive 403.
    - OPTIONS (preflight) requests are always passed through.
    """
    if request.method == "OPTIONS":
        return await call_next(request)

    path = request.url.path
    ip = request.headers.get("X-Real-IP", "").strip() or (
        request.client.host if request.client else "unknown"
    )

    # ── Purge expired shadow blocks ─────────────────────────────────
    now = _time.time()
    expired = [k for k, exp in _SHADOW_BLOCKED.items() if exp < now]
    for k in expired:
        _SHADOW_BLOCKED.pop(k, None)

    # ── Shadow-block check ──────────────────────────────────────────
    if ip in _SHADOW_BLOCKED and ip not in _SHADOW_BLOCK_EXEMPT:
        log.warning("anti_scrape.shadow_blocked_hit", extra={"ip": ip, "path": path})
        return JSONResponse(status_code=404, content={"detail": "Not found"})

    # ── UA check — only for /api/* and only when no API key present ──
    # Localhost is trusted (internal health checks, gauntlet, dev)
    has_api_key = bool(request.headers.get(_API_KEY_HEADER, "").strip())
    if path.startswith("/api/") and not has_api_key and ip not in _SHADOW_BLOCK_EXEMPT:
        ua = request.headers.get("User-Agent", "")
        if _SCRAPER_UA_PATTERNS.search(ua):
            log.warning(
                "anti_scrape.blocked",
                extra={"ip": ip, "ua": ua[:120], "path": path},
            )
            _flag_scraper_ip(ip)
            return JSONResponse(
                status_code=403,
                content={"error": {"code": "FORBIDDEN", "message": "Access denied"}},
            )

    return await call_next(request)


# ── Anti-scraping: public endpoints ──────────────────────────────────

from fastapi.responses import PlainTextResponse  # noqa: E402 (local import for clarity)


@app.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    """Instruct all crawlers to stay out."""
    body = (
        "User-agent: *\n"
        "Disallow: /\n"
        "\n"
        "# VeriFuse is a private legal intelligence platform.\n"
        "# Automated access is prohibited without written authorization.\n"
    )
    return PlainTextResponse(body, headers={"Cache-Control": "public, max-age=86400"})


@app.get("/.well-known/security.txt", include_in_schema=False)
async def security_txt():
    """Security contact information."""
    body = (
        "Contact: mailto:security@verifuse.tech\n"
        "Preferred-Languages: en\n"
        "Policy: https://verifuse.tech/privacy\n"
    )
    return PlainTextResponse(body)


# Honeypot endpoint — logs and shadow-blocks any client that hits it
@app.get("/api/internal/data-export", include_in_schema=False)
async def honeypot(request: Request):
    ip = request.headers.get("X-Real-IP", "").strip() or (
        request.client.host if request.client else "unknown"
    )
    ua = request.headers.get("User-Agent", "")
    log.warning(
        "anti_scrape.honeypot_hit",
        extra={"ip": ip, "ua": ua[:120], "path": request.url.path},
    )
    _flag_scraper_ip(ip)
    # Return realistic-looking 404 to not reveal it's a honeypot
    return JSONResponse(status_code=404, content={"detail": "Not found"})


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

    # Apply migration 016: auth security columns (idempotent)
    try:
        _mc = _get_conn()
        try:
            _mc_cols = {r[1] for r in _mc.execute("PRAGMA table_info(users)").fetchall()}
            _016 = {
                "failed_login_count": "INTEGER DEFAULT 0",
                "locked_until": "TEXT",
                "password_reset_token": "TEXT",
                "password_reset_sent_at": "TEXT",
                "token_version": "INTEGER DEFAULT 0",  # Incremented on password change/logout → revokes old JWTs
                "billing_period": "TEXT DEFAULT 'monthly'",
            }
            for _col, _typedef in _016.items():
                if _col not in _mc_cols:
                    _mc.execute(f"ALTER TABLE users ADD COLUMN {_col} {_typedef}")
                    log.info("Migration 016: added users.%s", _col)
            _mc.commit()
        finally:
            _mc.close()
    except Exception as _me:
        log.warning("Migration 016 partial: %s", _me)

    # Bar number uniqueness index (idempotent — CREATE INDEX IF NOT EXISTS)
    try:
        _bn = _get_conn()
        try:
            # Partial unique index: only non-empty bar_numbers must be unique
            _bn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_bar_number_unique "
                "ON users(bar_number) WHERE bar_number IS NOT NULL AND TRIM(bar_number) != ''"
            )
            _bn.commit()
            log.info("Bar number uniqueness index: OK")
        finally:
            _bn.close()
    except Exception as _bne:
        log.warning("Bar number uniqueness index: %s", _bne)

    # Orphaned html_snapshots cleanup (snapshots with no matching lead)
    try:
        _oc = _get_conn()
        try:
            _deleted = _oc.execute(
                "DELETE FROM html_snapshots WHERE asset_id NOT IN (SELECT id FROM leads)"
            ).rowcount
            _oc.commit()
            if _deleted:
                log.info("Orphaned html_snapshots cleaned: %d rows deleted", _deleted)
        finally:
            _oc.close()
    except Exception as _oce:
        log.warning("Orphaned snapshot cleanup: %s", _oce)

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

    # Apply migration 018: ops_jobs table (idempotent)
    try:
        _oj = _get_conn()
        try:
            _oj.execute("""
                CREATE TABLE IF NOT EXISTS ops_jobs (
                    id           TEXT PRIMARY KEY,
                    command      TEXT NOT NULL,
                    args_json    TEXT,
                    status       TEXT NOT NULL DEFAULT 'QUEUED',
                    triggered_by TEXT,
                    triggered_at INTEGER NOT NULL,
                    started_at   INTEGER,
                    finished_at  INTEGER,
                    output       TEXT,
                    exit_code    INTEGER,
                    county       TEXT
                )
            """)
            _oj.execute("CREATE INDEX IF NOT EXISTS idx_ops_jobs_triggered ON ops_jobs(triggered_at DESC)")
            _oj.commit()
        finally:
            _oj.close()
    except Exception as _oe:
        log.warning("Migration 018 (ops_jobs): %s", _oe)

    # ── Background tasks ────────────────────────────────────────────
    async def _wal_checkpoint_loop():
        """Hourly WAL checkpoint to keep WAL file from growing unbounded."""
        while True:
            await asyncio.sleep(3600)
            try:
                _wc = _get_conn()
                try:
                    _wc.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    _wc.commit()
                    log.info("WAL checkpoint completed")
                finally:
                    _wc.close()
            except Exception as _we:
                log.warning("WAL checkpoint failed: %s", _we)

    async def _preview_lookup_refresh_loop():
        """Refresh preview lookup every 5 minutes so new GOLD leads appear without restart."""
        while True:
            await asyncio.sleep(300)
            try:
                global _PREVIEW_LOOKUP
                _new_lookup: dict[str, str] = {}
                _rc = _get_conn()
                try:
                    _rq = (
                        "SELECT id, "
                        "ROUND(COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0), 2) as estimated_surplus, "
                        f"data_grade, {_claim_deadline_expr} "
                        "FROM leads WHERE COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0) > 100 "
                        f"AND data_grade != 'REJECT' {_EXPIRED_FILTER}"
                    )
                    for _rrow in _rc.execute(_rq).fetchall():
                        _rd = dict(_rrow)
                        if is_preview_eligible(_rd):
                            _pk = _compute_preview_key(_rd)
                            _new_lookup[_pk] = _rd["id"]
                finally:
                    _rc.close()
                _PREVIEW_LOOKUP = _new_lookup
                log.debug("Preview lookup refreshed: %d entries", len(_PREVIEW_LOOKUP))
            except Exception as _re:
                log.warning("Preview lookup refresh failed: %s", _re)

    asyncio.ensure_future(_wal_checkpoint_loop())
    asyncio.ensure_future(_preview_lookup_refresh_loop())

    log.info(
        "Omega v4.8 BOOT — DB: %s | inode: %s | sha256: %s | leads: %s | columns: %d | build: %s",
        VERIFUSE_DB_PATH, inode, sha, rows, len(_LEADS_COLUMNS), _BUILD_ID,
    )


@app.on_event("shutdown")
async def _shutdown_db_executor():
    DB_EXECUTOR.shutdown(wait=True)
    PDF_EXECUTOR.shutdown(wait=False)  # PDF renders are non-critical at exit


# ── Health ──────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    """Public health check with dependency status."""
    deps = {}

    def _db_health():
        conn = sqlite3.connect(VERIFUSE_DB_PATH, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        wcp = conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        sz_mb = round(os.path.getsize(VERIFUSE_DB_PATH) / 1_048_576, 1)
        cnt = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        conn.close()
        return {"status": "ok", "size_mb": sz_mb, "leads": cnt, "wal_pages": wcp[1] if wcp else 0}

    try:
        deps["database"] = await asyncio.get_event_loop().run_in_executor(DB_EXECUTOR, _db_health)
    except Exception as e:
        deps["database"] = {"status": "error", "detail": str(e)[:120]}

    deps["stripe"] = {"status": "configured" if STRIPE_SECRET_KEY else "unconfigured", "mode": STRIPE_MODE}

    sg = os.environ.get("SENDGRID_API_KEY", "")
    deps["sendgrid"] = {"status": "configured" if sg.startswith("SG.") else "unconfigured"}

    gcp = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    deps["google_cloud"] = {
        "status": "configured" if os.path.isfile(gcp) else "unconfigured",
        "project": os.environ.get("VERTEX_AI_PROJECT", ""),
    }

    overall = "error" if any(d.get("status") == "error" for d in deps.values()) else "ok"
    return {
        "status": overall,
        "version": "4.2.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "env": "development" if _IS_DEV else "production",
        "dependencies": deps,
    }


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


# ── B2: RTF Endpoints ────────────────────────────────────────────────

@app.get("/api/leads/ready-to-file")
async def get_rtf_leads(request: Request):
    """Returns all READY_TO_FILE leads for the requesting user's subscribed counties."""
    user = _require_user(request)
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM leads WHERE verification_state = 'READY_TO_FILE' "
            "AND data_grade IN ('GOLD', 'SILVER') "
            "ORDER BY updated_at DESC LIMIT 100"
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            safe = _row_to_safe(d)
            results.append(safe)
        return {"leads": results, "count": len(results)}
    finally:
        conn.close()


@app.post("/api/admin/leads/{lead_id}/promote-rtf")
async def promote_rtf(lead_id: str, request: Request):
    """Admin/staff: promote a lead to READY_TO_FILE state after manual RTF gate validation."""
    user = _require_user(request)
    if not _effective_admin(user):
        raise HTTPException(403, detail="Admin required.")
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", [lead_id]).fetchone()
        if not row:
            raise HTTPException(404, detail="Lead not found.")
        row = dict(row)
        # Validate RTF gates
        gate_fails = []
        if not row.get("sale_date"):
            gate_fails.append("sale_date missing")
        if not ((_safe_float(row.get("overbid_amount")) or 0) > 0):
            gate_fails.append("surplus_amount = 0 or missing")
        if not row.get("owner_name"):
            gate_fails.append("owner_name missing")
        if not row.get("property_address"):
            gate_fails.append("property_address missing")
        pool_src = row.get("pool_source", "UNVERIFIED")
        if pool_src not in ("VOUCHER", "LEDGER"):
            gate_fails.append(f"pool_source={pool_src} (requires VOUCHER or LEDGER)")
        if gate_fails:
            raise HTTPException(422, detail=f"RTF gate failed: {'; '.join(gate_fails)}")
        # Promote
        now_iso = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE leads SET verification_state = 'READY_TO_FILE', updated_at = ? WHERE id = ?",
            [now_iso, lead_id]
        )
        conn.commit()
        _audit_log(conn, user.get("user_id"), "promote_rtf", {"lead_id": lead_id})
        return {"ok": True, "verification_state": "READY_TO_FILE", "lead_id": lead_id}
    finally:
        conn.close()


@app.post("/api/admin/leads/{lead_id}/verify-sota")
async def admin_verify_sota(lead_id: str, request: Request):
    """Run SOTA triple-verification (Document AI + Gemini) on a GOLD lead.

    Non-blocking: upgrades pool_source to TRIPLE_VERIFIED/AI_VERIFIED if AI confirms.
    Requires admin auth. Uses Vertex AI credits.
    """
    user = get_current_user(request)
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Admin required.")

    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT id, overbid_amount, data_grade, county, case_number FROM leads WHERE id = ?",
            [lead_id],
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Lead not found.")
        if row["data_grade"] != "GOLD":
            raise HTTPException(status_code=400, detail="SOTA verification only available for GOLD leads.")

        from decimal import Decimal as _Decimal
        overbid = _Decimal(str(row["overbid_amount"] or 0))
        asset_id = f"FORECLOSURE:CO:{row['county'].upper()}:{row['case_number']}"

        def _run():
            from verifuse_v2.core.ai_verification_engine import VerificationEngine
            engine = VerificationEngine(use_docai=True, use_gemini=True, use_claude=False)
            return engine.verify_from_vault(asset_id, overbid, conn)

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_executor, _run)

        _audit_log(conn, user.get("user_id"), "sota_verify", {
            "lead_id": lead_id,
            "tier": result.tier,
            "confidence": result.confidence,
            "engines_agreed": result.engines_agreed,
        })

        return {
            "ok": True,
            "asset_id": asset_id,
            "tier": result.tier,
            "confidence": result.confidence,
            "engines_agreed": result.engines_agreed,
            "engines_run": result.engines_run,
            "docai_amount": str(result.docai_amount) if result.docai_amount else None,
            "gemini_amount": str(result.gemini_amount) if result.gemini_amount else None,
            "errors": result.errors,
            "duration_ms": result.duration_ms,
            "notes": result.verification_notes,
        }
    finally:
        conn.close()


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
    verification_state: Optional[str] = Query(None),
    surplus_stream: Optional[str] = Query(None),
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

            # Zombie filter: skip when explicitly requesting BRONZE/REJECT leads or
            # PRE_SALE pipeline leads — all three categories have $0 surplus by definition.
            _skip_zombie = (
                include_zombies
                or grade in ("BRONZE", "REJECT")
            )
            if not _skip_zombie:
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
            if verification_state:
                where += " AND verification_state = ?"
                params.append(verification_state)
            if surplus_stream:
                where += " AND surplus_stream = ?"
                params.append(surplus_stream.upper())

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

    # ── Parse optional body (reason_code / ticket_id for admin audit) ─
    _unlock_body: dict = {}
    try:
        _unlock_body = await request.json()
    except Exception:
        pass

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
            _audit_action = "admin_preview"  # default: read-only admin view
            _reason_code = _unlock_body.get("reason_code", "ADMIN_ACCESS")
            _ticket_id = _unlock_body.get("ticket_id")
            _supervisor = _unlock_body.get("supervisor_approval", False)
            _is_restricted_lead = dict(row).get("restriction_status") == "RESTRICTED"

            if _is_restricted_lead and _supervisor:
                _audit_action = "admin_force_unlock"
            elif _reason_code and _reason_code != "ADMIN_ACCESS":
                _audit_action = "admin_override_unlock"
            else:
                _audit_action = "admin_preview"

            _audit_log(conn2, user_id, _audit_action, {
                "reason_code": _reason_code,
                "ticket_id": _ticket_id,
                "supervisor_approval": _supervisor,
                "case_id": lead_id,
                "ip": ip,
            }, ip)

            # Also log to admin_override_log for override/force actions
            if _audit_action in ("admin_override_unlock", "admin_force_unlock"):
                try:
                    _admin_override_log(
                        conn2, user_id, _audit_action,
                        reason_code=_reason_code or "ADMIN_ACCESS",
                        target_lead_id=lead_id,
                    )
                except Exception:
                    pass  # Non-fatal — audit_log entry already captured above

            conn2.execute("COMMIT")
        except Exception as e:
            try:
                conn2.execute("ROLLBACK")
            except Exception:
                pass
            log.warning("Admin unlock audit write failed: %s", e)
        finally:
            conn2.close()

        _sc2 = _get_conn()
        try:
            result = _row_to_full(dict(row), conn=_sc2, unlocked_by_me=True, is_admin=True)
            # Phase 5: source_doc_count for UI evidence lock
            _lead_id2 = dict(row).get("id", "")
            _county2 = dict(row).get("county", "")
            _case2 = dict(row).get("case_number", "")
            _asset_key2 = f"FORECLOSURE:CO:{_county2.upper()}:{_case2.upper()}"
            try:
                _snap_ct2 = _sc2.execute("SELECT COUNT(*) FROM html_snapshots WHERE asset_id=?", [_asset_key2]).fetchone()[0]
                _pdf_ct2 = _sc2.execute("SELECT COUNT(*) FROM evidence_documents WHERE asset_id=?", [_lead_id2]).fetchone()[0]
                result["source_doc_count"] = _snap_ct2 + _pdf_ct2
            except Exception:
                result["source_doc_count"] = 0
        finally:
            _sc2.close()
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

    # RTF leads cost 3 credits (premium tier); standard leads cost 1
    if lead.get("verification_state") == "READY_TO_FILE":
        cost = CREDIT_COSTS.get("rtf_unlock", 3)
    else:
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
            result = _row_to_full(lead, conn=conn, unlocked_by_me=True, is_admin=False)
            # Phase 5: source_doc_count for UI evidence lock
            try:
                _lead_id3 = lead.get("id", "")
                _county3 = lead.get("county", "")
                _case3 = lead.get("case_number", "")
                _asset_key3 = f"FORECLOSURE:CO:{_county3.upper()}:{_case3.upper()}"
                _snap_ct3 = conn.execute("SELECT COUNT(*) FROM html_snapshots WHERE asset_id=?", [_asset_key3]).fetchone()[0]
                _pdf_ct3 = conn.execute("SELECT COUNT(*) FROM evidence_documents WHERE asset_id=?", [_lead_id3]).fetchone()[0]
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

    _sc = _get_conn()
    try:
        result = _row_to_full(lead, conn=_sc, unlocked_by_me=True, is_admin=False)
        # Phase 5: source_doc_count for UI evidence lock
        _lead_uuid = lead.get("id", "")
        _county = lead.get("county", "")
        _case = lead.get("case_number", "")
        _asset_key = f"FORECLOSURE:CO:{_county.upper()}:{_case.upper()}"
        try:
            _snap_ct = _sc.execute("SELECT COUNT(*) FROM html_snapshots WHERE asset_id=?", [_asset_key]).fetchone()[0]
            _pdf_ct = _sc.execute("SELECT COUNT(*) FROM evidence_documents WHERE asset_id=?", [_lead_uuid]).fetchone()[0]
            result["source_doc_count"] = _snap_ct + _pdf_ct
        except Exception:
            result["source_doc_count"] = 0
    finally:
        _sc.close()
    result["ok"] = True
    result["credits_remaining"] = credits_after
    result["credits_spent"] = cost
    _invalidate_stats_cache()
    return result


# ── POST /api/billing/upgrade — Tier upgrade + credit refill ────────

@app.post("/api/billing/upgrade")
@limiter.limit("10/minute")
async def billing_upgrade(request: Request):
    """Admin-only: manually adjust a user's tier and credit balance.

    SECURITY: This endpoint is ADMIN ONLY. User-facing tier upgrades flow
    exclusively through the Stripe webhook (/api/webhook).
    """
    user = _require_user(request)
    if not _effective_admin(user, request):
        raise HTTPException(status_code=403, detail="Admin only. Tier upgrades happen via Stripe.")

    body = await request.json()
    target_user_id = body.get("user_id", user["user_id"])
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
        """, [new_tier, credits, now, target_user_id])
        conn.commit()
    finally:
        conn.close()

    _log_action(user["user_id"], "admin_tier_upgrade", {"target": target_user_id, "tier": new_tier})
    return {
        "status": "ok",
        "user_id": target_user_id,
        "tier": new_tier,
        "credits_remaining": credits,
    }


# ── GET /api/stats — Public dashboard stats ────────────────────────

_stats_cache: dict = {"data": None, "expires": 0.0}
_STATS_CACHE_TTL = 30.0


def _invalidate_stats_cache() -> None:
    _stats_cache["expires"] = 0.0


@app.get("/api/stats")
async def get_stats():
    now = _time.monotonic()
    if _stats_cache["data"] is not None and now < _stats_cache["expires"]:
        return _stats_cache["data"]

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
            verified_surplus = conn.execute(
                "SELECT COALESCE(SUM(COALESCE(estimated_surplus, surplus_amount, overbid_amount, 0)), 0) "
                "FROM leads WHERE data_grade IN ('GOLD', 'SILVER') AND data_grade != 'REJECT'"
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

            # Pre-sale pipeline: upcoming auctions (explicit PRE_SALE status OR future scheduled sale date)
            pre_sale_count = conn.execute(
                "SELECT COUNT(*) FROM leads WHERE processing_status = 'PRE_SALE' "
                "OR (scheduled_sale_date IS NOT NULL AND scheduled_sale_date > date('now')) "
                "OR (sale_date IS NOT NULL AND sale_date > date('now'))"
            ).fetchone()[0]
            pre_sale_surplus = conn.execute(
                "SELECT COALESCE(SUM(COALESCE(opening_bid, 0)), 0) "
                "FROM leads WHERE (processing_status = 'PRE_SALE' "
                "OR (scheduled_sale_date IS NOT NULL AND scheduled_sale_date > date('now')) "
                "OR (sale_date IS NOT NULL AND sale_date > date('now'))) "
                "AND opening_bid > 0"
            ).fetchone()[0]

            # County list from county_profiles (active counties in platform — for filter UI)
            county_rows = conn.execute(
                "SELECT county FROM county_profiles ORDER BY county"
            ).fetchall()
            county_list = [r[0].replace("_", " ").title() for r in county_rows] if county_rows else []

            # Counties actually covered: active GovSoft config + real GOLD/SILVER/BRONZE leads
            active_rows = conn.execute("""
                SELECT DISTINCT l.county FROM leads l
                JOIN govsoft_county_configs gcc ON gcc.county = l.county AND gcc.active = 1
                WHERE l.data_grade IN ('GOLD','SILVER','BRONZE')
                ORDER BY l.county
            """).fetchall()
            counties_covered = len(active_rows)

            # New leads added in last 7 days (GOLD/SILVER only)
            new_leads_7d = conn.execute(
                "SELECT COUNT(*) FROM leads WHERE data_grade IN ('GOLD','SILVER') "
                "AND updated_at >= datetime('now', '-7 days')"
            ).fetchone()[0]
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
            "counties_covered": counties_covered,
            "new_leads_7d": new_leads_7d,
            "total_claimable_surplus": round(total_surplus, 2),
            "verified_surplus": round(verified_surplus, 2),
            "counties": [dict(r) for r in counties],
            "stream_breakdown": stream_breakdown,
            "verified_pipeline": vp_row["cnt"],
            "verified_pipeline_surplus": round(vp_row["total"], 2),
            "total_raw_volume": raw_row["cnt"],
            "total_raw_volume_surplus": round(raw_row["total"], 2),
            "pre_sale_count": pre_sale_count,
            "pre_sale_pipeline_surplus": round(pre_sale_surplus, 2),
        }

    result = await _run_in_db(_run)
    _stats_cache["data"] = result
    _stats_cache["expires"] = _time.monotonic() + _STATS_CACHE_TTL
    return result


# ── Auth helpers ────────────────────────────────────────────────────

def _trigger_verification_email(user_id: str, email: str, conn=None) -> None:
    """Send a 6-digit verification code. Reusable from register + send-verification endpoints."""
    import secrets as _sec
    code = "".join(_sec.choice(string.digits) for _ in range(6))
    now_ts = datetime.now(timezone.utc).isoformat()
    _conn = conn or _get_conn()
    _close_after = conn is None
    try:
        _conn.execute(
            "UPDATE users SET email_verify_code = ?, email_verify_sent_at = ? WHERE user_id = ?",
            [code, now_ts, user_id],
        )
        _conn.commit()
    finally:
        if _close_after:
            _conn.close()
    email_mode = os.environ.get("VERIFUSE_EMAIL_MODE", "log").lower()
    if _IS_DEV and email_mode == "log":
        log.info("[DEV] Verification code for %s: %s", email, code)
        print(f"[DEV] Verification code for {email}: {code}", flush=True)
    html = _build_html_email(
        "Verify Your Email Address",
        f"""<p style="color:#cbd5e1;font-size:1rem;margin:0 0 20px;">
          Enter this code in the VeriFuse app to verify your email address:
        </p>
        <div style="background:#0f172a;border-radius:8px;padding:20px;text-align:center;margin:0 0 20px;border:1px solid #334155;">
          <span style="font-size:2.5rem;font-weight:700;letter-spacing:0.2em;color:#22c55e;font-family:monospace;">{code}</span>
        </div>
        <p style="color:#64748b;font-size:0.875rem;margin:0;">
          This code expires in 10 minutes. If you did not request this, you can safely ignore this email.
        </p>""",
    )
    _send_email(
        to=email,
        subject="VeriFuse — Verify Your Email",
        body=f"Your VeriFuse verification code is: {code}\n\nThis code expires in 10 minutes.",
        html_body=html,
    )


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
    # Tier is ALWAYS set to the free base tier at registration.
    # Upgrades happen only via Stripe webhook — never via user-supplied tier field.
    user, token = register_user(
        email=email, password=password,
        full_name=body.get("full_name", ""),
        firm_name=body.get("firm_name", ""),
        bar_number=bar_number,
        tier="recon",
    )
    # Universal signup bonus — 3 free credits for every new account (no card required)
    import uuid as _uuid_m
    import time as _time_m
    _signup_expires = int(_time_m.time()) + 90 * 86400  # 90-day expiry
    _sc = _get_conn()
    try:
        _sc.execute(
            "INSERT OR IGNORE INTO unlock_ledger_entries "
            "(id, user_id, source, qty_total, qty_remaining, purchased_ts, expires_ts) "
            "VALUES (?, ?, 'signup_bonus', ?, ?, ?, ?)",
            [str(_uuid_m.uuid4()), user["user_id"], SIGNUP_BONUS_CREDITS, SIGNUP_BONUS_CREDITS,
             int(_time_m.time()), _signup_expires],
        )
        _sc.commit()
        log.info("Signup bonus credited: user=%s credits=%d", user["user_id"], SIGNUP_BONUS_CREDITS)
    except Exception as _e:
        log.warning("Signup bonus grant failed: %s", _e)
    finally:
        _sc.close()

    # Founders cap check — grant 5 additional bonus credits if founding slot claimed
    is_founder = _try_founders_redemption(user["user_id"])
    if is_founder:
        _bonus = 5
        _expires = int(_time_m.time()) + 365 * 86400  # 1 year
        _c = _get_conn()
        try:
            _c.execute(
                "INSERT OR IGNORE INTO unlock_ledger_entries "
                "(id, user_id, source, qty_total, qty_remaining, purchased_ts, expires_ts) "
                "VALUES (?, ?, 'founders_bonus', ?, ?, ?, ?)",
                [str(_uuid_m.uuid4()), user["user_id"], _bonus, _bonus, int(_time_m.time()), _expires],
            )
            _c.commit()
            log.info("Founders bonus credited: user=%s credits=%d", user["user_id"], _bonus)
        except Exception as _e:
            log.warning("Founders bonus grant failed: %s", _e)
        finally:
            _c.close()
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
    # Auto-send verification email at registration
    try:
        _trigger_verification_email(user["user_id"], email)
    except Exception as _ve:
        log.warning("Auto-send verification email failed for %s: %s", email, _ve)

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

    # 60-second resend cooldown
    _cconn = _get_conn()
    try:
        _cts = _cconn.execute(
            "SELECT email_verify_sent_at FROM users WHERE user_id = ?",
            [user["user_id"]],
        ).fetchone()
    finally:
        _cconn.close()
    if _cts and _cts["email_verify_sent_at"]:
        try:
            _sent = datetime.fromisoformat(_cts["email_verify_sent_at"].replace("Z", "+00:00"))
            _elapsed = (datetime.now(timezone.utc) - _sent).total_seconds()
            if _elapsed < 60:
                raise HTTPException(429, detail=f"Please wait {int(60 - _elapsed)} seconds before resending.")
        except HTTPException:
            raise
        except Exception:
            pass

    import secrets as _sec2
    code = "".join(_sec2.choice(string.digits) for _ in range(6))
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


# ── Forgot / Reset / Change Password ────────────────────────────────

@app.post("/api/auth/forgot-password")
@limiter.limit("3/minute")
async def forgot_password(request: Request):
    """Send password reset link. Returns ok=True regardless (no email enumeration)."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")
    email = body.get("email", "").strip().lower()
    if not email:
        return {"ok": True}

    import secrets as _secrets
    token = _secrets.token_urlsafe(32)
    now_ts = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    try:
        row = conn.execute("SELECT user_id FROM users WHERE email = ?", [email]).fetchone()
        if row:
            conn.execute(
                "UPDATE users SET password_reset_token = ?, password_reset_sent_at = ? WHERE user_id = ?",
                [token, now_ts, row["user_id"]],
            )
            conn.commit()
            reset_url = f"https://verifuse.tech/reset-password?token={token}"
            pw_html = _build_html_email(
                "Password Reset Request",
                f"""<p style="color:#cbd5e1;margin:0 0 20px;">
                  We received a request to reset your VeriFuse password.
                  Click the button below to set a new password (link expires in 1 hour):
                </p>
                <div style="text-align:center;margin:0 0 24px;">
                  <a href="{reset_url}" style="display:inline-block;background:#22c55e;color:#0f172a;padding:12px 28px;border-radius:6px;font-weight:700;text-decoration:none;font-size:0.95rem;">
                    Reset My Password →
                  </a>
                </div>
                <p style="color:#64748b;font-size:0.875rem;margin:0;">
                  If you didn't request a password reset, you can safely ignore this email.
                  Your password will remain unchanged.
                </p>""",
            )
            _send_email(
                to=email,
                subject="Reset your VeriFuse password",
                body=(
                    f"You requested a VeriFuse password reset.\n\n"
                    f"Click the link below (expires in 1 hour):\n{reset_url}\n\n"
                    f"If you did not request this, ignore this email."
                ),
                html_body=pw_html,
            )
            if _IS_DEV:
                log.info("[DEV] Password reset token for %s: %s", email, token)
    finally:
        conn.close()
    return {"ok": True}


@app.post("/api/auth/reset-password")
@limiter.limit("5/minute")
async def reset_password(request: Request):
    """Reset password using token from email link. Token expires in 1 hour."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")
    token = body.get("token", "").strip()
    password = body.get("password", "")
    if not token or not password:
        raise HTTPException(status_code=400, detail="Token and password required.")

    from verifuse_v2.server.auth import _validate_password, hash_password
    _validate_password(password)

    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT user_id, password_reset_token, password_reset_sent_at FROM users "
            "WHERE password_reset_token = ?",
            [token],
        ).fetchone()
        if not row:
            raise HTTPException(status_code=400, detail="Invalid or expired reset token.")

        sent_at = row["password_reset_sent_at"]
        if sent_at:
            try:
                sent_dt = datetime.fromisoformat(sent_at.replace("Z", "+00:00"))
                if sent_dt.tzinfo is None:
                    sent_dt = sent_dt.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - sent_dt > timedelta(hours=1):
                    raise HTTPException(status_code=400, detail="Reset token has expired. Request a new one.")
            except HTTPException:
                raise
            except Exception:
                pass

        new_hash = hash_password(password)
        # NOTE: Do NOT clear locked_until here — resetting password must not bypass lockout.
        # Increment token_version to revoke all previously issued JWTs.
        conn.execute(
            "UPDATE users SET password_hash = ?, password_reset_token = NULL, "
            "password_reset_sent_at = NULL, failed_login_count = 0, "
            "token_version = COALESCE(token_version, 0) + 1 WHERE user_id = ?",
            [new_hash, row["user_id"]],
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@app.post("/api/auth/change-password")
@limiter.limit("10/minute")
async def change_password(request: Request):
    """Change password for authenticated user. Requires current password."""
    user = _require_user(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")
    current_pw = body.get("current_password", "")
    new_pw = body.get("new_password", "")
    if not current_pw or not new_pw:
        raise HTTPException(status_code=400, detail="current_password and new_password required.")

    from verifuse_v2.server.auth import _validate_password, hash_password, verify_password
    _validate_password(new_pw)

    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE user_id = ?", [user["user_id"]]
        ).fetchone()
        if not row or not verify_password(current_pw, row["password_hash"]):
            raise HTTPException(status_code=401, detail="Current password is incorrect.")
        new_hash = hash_password(new_pw)
        # Increment token_version to revoke all previously issued JWTs (including attacker's stolen token)
        conn.execute(
            "UPDATE users SET password_hash = ?, token_version = COALESCE(token_version, 0) + 1 WHERE user_id = ?",
            [new_hash, user["user_id"]],
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


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
                full = _row_to_full(dict(row), conn=conn, unlocked_by_me=True, is_admin=True)
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
                if is_unlocked:
                    full = _row_to_full(dict(row), conn=conn, unlocked_by_me=True, is_admin=False)
                    result.update(full)

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

            # ── Junior lien records (always included when available) ──────────
            # Surfaced to all authenticated users — lien existence is intelligence, not PII.
            if registry_asset_id:
                try:
                    lien_rows = conn.execute(
                        """SELECT lien_type, lienholder_name, priority, amount_cents, is_open
                           FROM lien_records
                           WHERE asset_id = ?
                           ORDER BY is_open DESC, priority ASC""",
                        [registry_asset_id],
                    ).fetchall()
                    result["junior_liens"] = [dict(r) for r in lien_rows]
                except Exception:
                    result["junior_liens"] = []

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

    # Generate dossier in-memory — never write PII to disk
    filename = f"dossier_{lead_id[:12]}.txt"
    lines = [
        "=" * 60,
        "  VERIFUSE — INTELLIGENCE DOSSIER",
        "=" * 60, "",
        f"Case Number:      {lead.get('case_number', 'N/A')}",
        f"County:           {lead.get('county', 'N/A')}",
        f"Owner:            {lead.get('owner_name', 'N/A')}",
        f"Property Address: {lead.get('property_address', 'N/A')}",
        f"Sale Date:        {lead.get('sale_date', 'N/A')}",
        f"Claim Deadline:   {lead.get('claim_deadline', 'N/A')}", "",
        f"Winning Bid:      ${bid:,.2f}",
        f"Total Debt:       ${_safe_float(lead.get('total_debt')) or 0:,.2f}",
        f"Surplus Amount:   ${surplus:,.2f}",
        f"Data Grade:       {lead.get('data_grade', 'N/A')}",
        f"Confidence:       {_safe_float(lead.get('confidence_score')) or 0:.0%}", "",
        "=" * 60,
        "  DISCLAIMER: For informational purposes only.",
        "  Verify all figures with the County Public Trustee.",
        "=" * 60,
    ]
    content = "\n".join(lines)

    from fastapi.responses import Response as _Resp
    return _Resp(
        content=content,
        media_type="text/plain",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store, no-cache",
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
    "starter":          {"env_key": "STARTER",          "credits": 10, "name": "Lead Unlock Bundle"},
    "investigation":    {"env_key": "INVESTIGATION",     "credits": 25, "name": "Investigation Pack"},
    "skip_trace":       {"env_key": "SKIP_TRACE",        "credits": 1,  "name": "Skip Trace"},
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
            success_url=f"{os.environ.get('VERIFUSE_BASE_URL', 'https://verifuse.tech')}/account?credits=1",
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
            success_url=f"{os.environ.get('VERIFUSE_BASE_URL', 'https://verifuse.tech')}/account?credits=1",
            cancel_url=f"{os.environ.get('VERIFUSE_BASE_URL', 'https://verifuse.tech')}/pricing",
        )
        return {"checkout_url": session.url}
    except Exception as e:
        log.error("Starter checkout failed: %s", e)
        raise HTTPException(status_code=503, detail="Billing service unavailable.")


# ── GET /api/billing/status — Current subscription info ─────────────

@app.get("/api/billing/status")
async def billing_status(request: Request):
    """Return current user's subscription status, credits, and tier."""
    user = _require_user(request)
    conn = _get_conn()
    try:
        try:
            row = conn.execute(
                """SELECT tier, credits_remaining, stripe_customer_id, stripe_subscription_id,
                          subscription_status, current_period_end, founders_pricing,
                          billing_period, created_at
                   FROM users WHERE user_id = ?""",
                [user["user_id"]],
            ).fetchone()
        except Exception:
            row = conn.execute(
                """SELECT tier, credits_remaining, stripe_customer_id, stripe_subscription_id,
                          subscription_status, current_period_end, founders_pricing, created_at
                   FROM users WHERE user_id = ?""",
                [user["user_id"]],
            ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found.")
        monthly_grant = get_monthly_credits(row["tier"])
        # Use FIFO ledger balance (source of truth) not legacy users.credits_remaining
        ledger_bal = _ledger_balance(conn, user["user_id"])
        return {
            "tier": row["tier"],
            "credits_remaining": ledger_bal,
            "monthly_grant": monthly_grant,
            "stripe_customer_id": row["stripe_customer_id"],
            "subscription_status": row["subscription_status"],
            "current_period_end": row["current_period_end"],
            "founders_pricing": bool(row["founders_pricing"]),
            "stripe_configured": bool(STRIPE_SECRET_KEY),
            "billing_period": (row["billing_period"] if "billing_period" in row.keys() else None) or "monthly",
            "subscribed_since": row["created_at"],
        }
    finally:
        conn.close()


# ── GET /api/founding/status — Founding attorney program status ──────

@app.get("/api/founding/status")
async def founding_status():
    """Public endpoint — returns founding attorney program status."""
    conn = _get_conn()
    try:
        claimed = conn.execute(
            "SELECT COUNT(*) FROM users WHERE founders_pricing = 1"
        ).fetchone()[0]
        total = 10
        return {
            "slots_claimed": claimed,
            "slots_total": total,
            "is_open": claimed < total,
        }
    finally:
        conn.close()


# ── POST /api/billing/portal — Stripe Customer Portal ───────────────

@app.post("/api/billing/portal")
async def billing_portal(request: Request):
    """Create a Stripe Customer Portal session for self-service billing management."""
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Billing not configured.")
    user = _require_user(request)
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT stripe_customer_id FROM users WHERE user_id = ?",
            [user["user_id"]],
        ).fetchone()
    finally:
        conn.close()
    if not row or not row["stripe_customer_id"]:
        raise HTTPException(
            status_code=400,
            detail="No active subscription found. Purchase a plan to manage billing.",
        )
    try:
        import stripe as _stripe
        _stripe.api_key = STRIPE_SECRET_KEY
        base_url = os.environ.get("VERIFUSE_BASE_URL", "https://verifuse.tech")
        session = _stripe.billing_portal.Session.create(
            customer=row["stripe_customer_id"],
            return_url=f"{base_url}/account",
        )
        return {"portal_url": session.url}
    except Exception as e:
        log.error("Billing portal failed: %s", e)
        raise HTTPException(status_code=503, detail="Billing portal unavailable.")


# ── GET /api/billing/invoices — Stripe invoice history ──────────────

@app.get("/api/billing/invoices")
async def billing_invoices(request: Request):
    """Return the last 10 Stripe invoices for the current user."""
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Billing not configured.")
    user = _require_user(request)
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT stripe_customer_id FROM users WHERE user_id = ?",
            [user["user_id"]],
        ).fetchone()
    finally:
        conn.close()
    if not row or not row["stripe_customer_id"]:
        return {"invoices": []}
    try:
        import stripe as _stripe
        _stripe.api_key = STRIPE_SECRET_KEY
        invoices = _stripe.Invoice.list(customer=row["stripe_customer_id"], limit=10)
        result = []
        for inv in invoices.data:
            result.append({
                "id": inv.id,
                "number": inv.number,
                "amount_paid": inv.amount_paid / 100,
                "currency": inv.currency.upper(),
                "status": inv.status,
                "created": inv.created,
                "invoice_pdf": inv.invoice_pdf,
                "period_start": inv.period_start,
                "period_end": inv.period_end,
                "description": inv.lines.data[0].description if inv.lines.data else "",
            })
        return {"invoices": result}
    except Exception as e:
        log.error("Invoices fetch failed: %s", e)
        return {"invoices": []}


# ── PATCH /api/account — Update user profile ────────────────────────

@app.patch("/api/account")
async def update_account(request: Request):
    """Update user profile: full_name, firm_name, bar_number."""
    user = _require_user(request)
    body = await request.json()
    allowed = {"full_name", "firm_name", "bar_number", "bar_state", "firm_address"}
    updates = {k: v for k, v in body.items() if k in allowed and isinstance(v, str)}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update.")
    conn = _get_conn()
    try:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        params = list(updates.values()) + [user["user_id"]]
        conn.execute(f"UPDATE users SET {set_clause} WHERE user_id = ?", params)
        conn.commit()
        _audit_log(conn, user["user_id"], "profile_update", {"fields": list(updates.keys())})
        row = conn.execute(
            "SELECT full_name, firm_name, bar_number, bar_state, firm_address, email FROM users WHERE user_id = ?",
            [user["user_id"]],
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


# ── Self-service API Key (user manages own key) ─────────────────────

@app.post("/api/account/api-key")
async def account_generate_api_key(request: Request):
    """Generate or rotate API key for the authenticated user (self-service)."""
    user = _require_user(request)
    import secrets as _secrets
    raw_key = "vf_" + _secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    now_str = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE users SET api_key_hash = ?, api_key_created_at = ? WHERE user_id = ?",
            [key_hash, now_str, user["user_id"]],
        )
        conn.commit()
        _audit_log(conn, user["user_id"], "api_key_generated", {"self_service": True})
        return {"api_key": raw_key, "created_at": now_str, "note": "Store this key securely — it will not be shown again."}
    finally:
        conn.close()


@app.get("/api/account/api-key-status")
async def account_api_key_status(request: Request):
    """Return whether the authenticated user has an API key configured."""
    user = _require_user(request)
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT api_key_hash, api_key_created_at FROM users WHERE user_id = ?",
            [user["user_id"]],
        ).fetchone()
        return {"has_key": bool(row and row["api_key_hash"]), "created_at": row["api_key_created_at"] if row else None}
    finally:
        conn.close()


@app.delete("/api/account/api-key")
async def account_revoke_api_key(request: Request):
    """Revoke the authenticated user's API key."""
    user = _require_user(request)
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE users SET api_key_hash = NULL, api_key_created_at = NULL WHERE user_id = ?",
            [user["user_id"]],
        )
        conn.commit()
        _audit_log(conn, user["user_id"], "api_key_revoked", {"self_service": True})
        return {"status": "revoked"}
    finally:
        conn.close()


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
    finally:
        conn.close()

    # Run handler BEFORE marking as processed — if handler crashes, Stripe will retry
    try:
        if event_type == "checkout.session.completed":
            _handle_checkout_session(data_obj)
        elif event_type == "invoice.payment_succeeded":
            _handle_invoice_payment(data_obj)
        elif event_type == "customer.subscription.deleted":
            _handle_subscription_cancelled(data_obj)
        else:
            log.debug("Unhandled Stripe event: %s", event_type)
    except Exception as exc:
        log.error("Stripe handler failed for %s %s: %s", event_type, event_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Webhook handler error — will retry")

    # Mark as processed only after successful handling
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO stripe_events (event_id, type, received_at) VALUES (?, ?, datetime('now'))",
            [event_id, event_type],
        )
        conn.commit()
    finally:
        conn.close()

    return {"status": "ok"}


def _handle_checkout_session(session: dict) -> None:
    """Handle checkout.session.completed — one-time pack crediting and subscription activation."""
    metadata = session.get("metadata", {})
    sku = metadata.get("sku", "")

    # ── One-time payment packs ───────────────────────────────────────────
    # Canonical SKU map for all one-time purchases
    _PACK_REGISTRY: dict[str, dict] = {
        "starter_pack":    {"credits": STARTER_PACK["credits"],        "expiry_days": STARTER_PACK.get("expiry_days", 90),  "source": "starter"},
        "starter":         {"credits": STARTER_PACK["credits"],        "expiry_days": STARTER_PACK.get("expiry_days", 90),  "source": "starter"},
        "investigation":   {"credits": INVESTIGATION_PACK["credits"],  "expiry_days": INVESTIGATION_PACK.get("expiry_days", 90), "source": "investigation"},
        "skip_trace":      {"credits": 1,                              "expiry_days": 90, "source": "skip_trace"},
        "filing_pack":     {"credits": CREDIT_COSTS["filing_pack"],    "expiry_days": 90, "source": "filing_pack"},
        "premium_dossier": {"credits": CREDIT_COSTS["premium_dossier"],"expiry_days": 90, "source": "premium_dossier"},
    }

    if session.get("mode") == "payment" and sku in _PACK_REGISTRY:
        pack = _PACK_REGISTRY[sku]
        # Strict validation
        if session.get("payment_status") != "paid":
            log.warning("Pack %s: payment_status != paid", sku)
            return
        user_id = metadata.get("user_id", "")
        if not user_id:
            log.warning("Pack %s: no user_id in metadata", sku)
            return
        if session.get("client_reference_id") != user_id:
            log.warning("Pack %s: client_reference_id mismatch", sku)
            return
        amount_total = session.get("amount_total", 0)
        if amount_total <= 0:
            log.warning("Pack %s: amount_total <= 0", sku)
            return
        currency = (session.get("currency") or "").lower()
        if currency != EXPECTED_CURRENCY:
            log.warning("Pack %s: currency mismatch (got %s)", sku, currency)
            return

        import uuid as _uuid_mod
        session_id = session.get("id", "")
        credits = pack["credits"]
        expires_ts = _epoch_now() + pack["expiry_days"] * 86400

        conn = _get_conn()
        try:
            try:
                conn.execute(
                    "INSERT INTO unlock_ledger_entries "
                    "(id, user_id, source, qty_total, qty_remaining, purchased_ts, expires_ts, stripe_event_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [str(_uuid_mod.uuid4()), user_id, pack["source"], credits, credits,
                     _epoch_now(), expires_ts, session_id],
                )
            except sqlite3.IntegrityError:
                log.info("Pack %s already credited (stripe_event_id dup): %s", sku, session_id)
                return
            _audit_log(conn, user_id, f"{pack['source']}_credited", {
                "sku": sku, "credits": credits, "amount_total": amount_total,
                "session_id": session_id, "expires_ts": expires_ts,
            })
            conn.commit()
            log.info("Pack credited: user=%s sku=%s credits=%d expires=%d", user_id, sku, credits, expires_ts)
        finally:
            conn.close()
    else:
        # Subscription checkout — record customer/subscription IDs only.
        # Credits are granted atomically by the invoice.payment_succeeded event.
        user_id = metadata.get("user_id", "")
        tier = metadata.get("tier", "scout")
        billing_period = metadata.get("billing_period", "monthly") or "monthly"
        customer_id = session.get("customer", "")
        subscription_id = session.get("subscription", "")

        if not user_id:
            log.warning("Subscription checkout: no user_id in metadata — session_id=%s", session.get("id", ""))
            return

        if not customer_id:
            log.warning("Subscription checkout: no customer_id — session_id=%s user_id=%s", session.get("id", ""), user_id)
            return

        if tier not in ("associate", "partner", "sovereign"):
            log.warning("Subscription checkout: invalid tier=%r for user_id=%s", tier, user_id)
            return

        conn = _get_conn()
        try:
            rows_updated = conn.execute(
                "UPDATE users SET stripe_customer_id = ?, stripe_subscription_id = ?, "
                "subscription_status = 'active', tier = ?, billing_period = ? WHERE user_id = ?",
                [customer_id, subscription_id, tier, billing_period, user_id],
            ).rowcount
            if rows_updated == 0:
                log.error("Subscription checkout: UPDATE matched 0 rows for user_id=%s", user_id)
            _audit_log(conn, user_id, "subscription_activated", {
                "tier": tier, "billing_period": billing_period, "customer_id": customer_id,
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
            _TIER_RANK = {"recon": 0, "associate": 1, "partner": 2, "sovereign": 3}
            cur_row = conn.execute(
                "SELECT tier FROM users WHERE user_id = ?", [user_id]
            ).fetchone()
            current_tier = (cur_row["tier"] if cur_row else None) or "recon"
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

            # First-month welcome bonus (subscription_create only)
            welcome_bonus = FIRST_MONTH_BONUS.get(new_tier, 0) if billing_reason == "subscription_create" else 0
            total_credits = monthly + rollover + welcome_bonus

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
                "welcome_bonus": welcome_bonus, "total": total_credits, "reason": billing_reason,
            })
            log.info("Credits granted: user=%s tier=%s monthly=%d rollover=%d welcome_bonus=%d total=%d reason=%s",
                     user_id, new_tier, monthly, rollover, welcome_bonus, total_credits, billing_reason)
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
            f"SELECT u.user_id, u.email, u.full_name, u.firm_name, u.bar_number, u.bar_state, "
            f"u.tier, u.attorney_status, u.role, "
            f"u.is_admin, u.is_active, u.email_verified, u.created_at, u.last_login_at, "
            f"COALESCE((SELECT SUM(le.qty_remaining) FROM unlock_ledger_entries le "
            f"WHERE le.user_id = u.user_id "
            f"AND (le.expires_ts IS NULL OR le.expires_ts > strftime('%s','now'))), 0) as credits_remaining "
            f"FROM users u {where}",
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

        # User counts (excludes admin accounts)
        user_counts = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN attorney_status='VERIFIED' THEN 1 ELSE 0 END) as verified_attorneys,
                SUM(CASE WHEN attorney_status='PENDING' THEN 1 ELSE 0 END) as pending_attorneys,
                SUM(CASE WHEN tier='sovereign' THEN 1 ELSE 0 END) as sovereign_users,
                SUM(CASE WHEN tier='partner' THEN 1 ELSE 0 END) as partner_users,
                SUM(CASE WHEN tier='associate' THEN 1 ELSE 0 END) as associate_users
            FROM users WHERE is_admin = 0
        """).fetchone()

        # EPIC 4H: Attorney outcomes summary
        attorney_outcomes_summary: dict = {}
        try:
            outcome_rows = conn.execute("""
                SELECT
                    COALESCE(outcome_type, 'PENDING') as outcome_type,
                    COUNT(*) as case_count,
                    COALESCE(SUM(outcome_funds_cents), 0) as total_funds_cents
                FROM attorney_cases
                GROUP BY outcome_type
                ORDER BY case_count DESC
            """).fetchall()
            attorney_outcomes_summary = {
                "by_outcome": [dict(r) for r in outcome_rows],
                "total_cases": sum(r["case_count"] for r in outcome_rows),
                "total_funds_cents": sum(r["total_funds_cents"] for r in outcome_rows),
            }
        except Exception:
            attorney_outcomes_summary = {"by_outcome": [], "total_cases": 0, "total_funds_cents": 0}

    finally:
        conn.close()

    # Stripe status
    stripe_configured = bool(STRIPE_SECRET_KEY)
    stripe_publishable_configured = bool(STRIPE_PUBLISHABLE_KEY)

    return {
        "db_path": Path(VERIFUSE_DB_PATH).name,  # filename only, never full path
        "db_size_mb": round(db_size_bytes / 1024 / 1024, 2),
        "wal_pages": wal_pages,
        "total_leads": total_leads,
        "scoreboard": scoreboard,
        "verified_pipeline_count": vp_row["cnt"],
        "verified_pipeline_surplus": round(vp_row["total"], 2),
        "recent_audit": recent_audit,
        "user_counts": dict(user_counts) if user_counts else {},
        "attorney_outcomes_summary": attorney_outcomes_summary,
        "stripe_configured": stripe_configured,
        "stripe_publishable_configured": stripe_publishable_configured,
        "stripe_mode": STRIPE_MODE,
        "build_id": _BUILD_ID,
        "verifuse_env": os.environ.get("VERIFUSE_ENV", "production"),
        "api_key_configured": bool(VERIFUSE_API_KEY),
    }


_TIER_MONTHLY_CENTS = {"associate": 14900, "partner": 39900, "sovereign": 89900}


@app.get("/api/admin/pipeline-status")
async def pipeline_status(request: Request):
    """Per-county Gate 4 readiness with action classification (admin only)."""
    _require_admin_or_api_key(request)

    def _query():
        conn = _thread_conn()
        rows = conn.execute("""
            SELECT
                cp.county,
                COALESCE(SUM(CASE WHEN l.data_grade != 'REJECT' THEN 1 ELSE 0 END), 0) as total,
                COALESCE(SUM(CASE WHEN l.data_grade = 'GOLD' THEN 1 ELSE 0 END), 0) as gold,
                COALESCE(SUM(CASE WHEN l.data_grade = 'SILVER' THEN 1 ELSE 0 END), 0) as silver,
                COALESCE(SUM(CASE WHEN l.data_grade = 'BRONZE' THEN 1 ELSE 0 END), 0) as bronze,
                COALESCE(SUM(CASE WHEN l.data_grade = 'REJECT' THEN 1 ELSE 0 END), 0) as reject,
                COALESCE(SUM(CASE WHEN l.sale_date IS NULL AND l.data_grade = 'BRONZE' THEN 1 ELSE 0 END), 0) as bronze_no_sale_date,
                COALESCE(SUM(CASE WHEN l.overbid_amount IS NULL AND l.data_grade = 'BRONZE' THEN 1 ELSE 0 END), 0) as bronze_not_extracted,
                COALESCE(SUM(CASE WHEN l.overbid_amount IS NOT NULL AND l.overbid_amount = 0 AND l.data_grade = 'BRONZE' THEN 1 ELSE 0 END), 0) as bronze_zero_overbid,
                cp.platform_type,
                cp.last_verified_ts
            FROM county_profiles cp
            LEFT JOIN leads l ON l.county = cp.county
            GROUP BY cp.county
            ORDER BY gold DESC, silver DESC, bronze DESC, cp.county ASC
        """).fetchall()
        # SALE_INFO snapshot counts per county (asset_id = FORECLOSURE:CO:{COUNTY}:{CASE})
        snap_rows = conn.execute("""
            SELECT LOWER(SUBSTR(asset_id, 17,
                   INSTR(SUBSTR(asset_id, 17), ':') - 1)) as county,
                   COUNT(*) as cnt
            FROM html_snapshots
            WHERE snapshot_type = 'SALE_INFO'
              AND asset_id LIKE 'FORECLOSURE:CO:%'
            GROUP BY county
        """).fetchall()
        snap_by_county = {r["county"]: r["cnt"] for r in snap_rows}
        # Last ingestion run per county (with run_duration_s and error_message if available)
        try:
            last_run_rows = conn.execute("""
                SELECT county, MAX(start_ts) as last_ts
                FROM ingestion_runs GROUP BY county
            """).fetchall()
            last_run_by_county = {r["county"]: r["last_ts"] for r in last_run_rows}
        except Exception:
            last_run_by_county = {}
        # Latest run metadata per county (duration + error)
        run_meta_by_county: dict = {}
        try:
            _cols = [row[1] for row in conn.execute("PRAGMA table_info(ingestion_runs)").fetchall()]
            _has_duration = "run_duration_s" in _cols
            _has_error = "error_message" in _cols
            _sel_extra = ""
            if _has_duration:
                _sel_extra += ", ir.run_duration_s"
            if _has_error:
                _sel_extra += ", ir.error_message"
            if _sel_extra:
                _meta_rows = conn.execute(f"""
                    SELECT ir.county{_sel_extra}
                    FROM ingestion_runs ir
                    INNER JOIN (
                        SELECT county, MAX(start_ts) as max_ts FROM ingestion_runs GROUP BY county
                    ) latest ON ir.county = latest.county AND ir.start_ts = latest.max_ts
                """).fetchall()
                for mr in _meta_rows:
                    meta: dict = {}
                    if _has_duration:
                        meta["run_duration_s"] = mr["run_duration_s"]
                    if _has_error:
                        meta["error_message"] = mr["error_message"]
                    run_meta_by_county[mr["county"]] = meta
        except Exception:
            pass
        conn.close()
        return rows, snap_by_county, last_run_by_county, run_meta_by_county

    rows, snap_by_county, last_run_by_county, run_meta_by_county = await _run_in_db(_query)
    result = []
    _captcha_counties = {"mesa", "eagle"}
    for r in rows:
        bronze_no_sale_date = r["bronze_no_sale_date"] or 0
        bronze_not_extracted = r["bronze_not_extracted"] or 0
        bronze_zero_overbid = r["bronze_zero_overbid"] or 0
        bronze = r["bronze"] or 0
        county = r["county"] or ""
        has_snapshots = snap_by_county.get(county, 0)
        platform = r["platform_type"] or ""
        last_ts = last_run_by_county.get(county)
        run_meta = run_meta_by_county.get(county, {})
        if county in _captcha_counties or "captcha" in platform:
            action = "captcha_blocked"
        elif bronze > 0 and bronze_no_sale_date > bronze * 0.5:
            action = "sale_info_backfill_needed"
        elif bronze_not_extracted > 0:
            action = "gate4_ready"
        elif bronze_zero_overbid > 0:
            action = "no_surplus"   # Gate 4 ran — confirmed $0 overbid
        elif bronze == 0:
            action = "clean"
        else:
            action = "gate4_ready"
        result.append({
            "county": county,
            "total": r["total"],
            "gold": r["gold"] or 0,
            "silver": r["silver"] or 0,
            "bronze": bronze,
            "reject": r["reject"] or 0,
            "bronze_no_sale_date": bronze_no_sale_date,
            "bronze_not_extracted": bronze_not_extracted,
            "bronze_zero_overbid": bronze_zero_overbid,
            "has_snapshots": has_snapshots,
            "platform_type": platform,
            "last_verified_ts": r["last_verified_ts"],
            "last_ingestion_ts": last_ts,
            "run_duration_s": run_meta.get("run_duration_s"),
            "error_message": run_meta.get("error_message"),
            "action_needed": action,
        })
    return {"pipeline": result, "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/admin/county-health")
async def admin_county_health(request: Request):
    """Layer 6: Per-county health scores — sale_date coverage, extraction rate, evidence, parser drift (admin only)."""
    _require_admin_or_api_key(request)

    def _query():
        conn = _thread_conn()
        # ── Lead quality per county ──────────────────────────────────────────
        quality_rows = conn.execute("""
            SELECT
                cp.county,
                cp.platform_type,
                COALESCE(SUM(CASE WHEN l.data_grade != 'REJECT' THEN 1 ELSE 0 END), 0) as total,
                COALESCE(SUM(CASE WHEN l.data_grade = 'GOLD' THEN 1 ELSE 0 END), 0)   as gold,
                COALESCE(SUM(CASE WHEN l.data_grade = 'SILVER' THEN 1 ELSE 0 END), 0) as silver,
                COALESCE(SUM(CASE WHEN l.data_grade = 'BRONZE' THEN 1 ELSE 0 END), 0) as bronze,
                COALESCE(SUM(CASE WHEN l.data_grade = 'REJECT' THEN 1 ELSE 0 END), 0) as reject,
                COALESCE(SUM(CASE WHEN l.data_grade != 'REJECT' AND l.sale_date IS NOT NULL THEN 1 ELSE 0 END), 0) as has_sale_date,
                COALESCE(SUM(CASE WHEN l.data_grade != 'REJECT' AND l.overbid_amount IS NOT NULL THEN 1 ELSE 0 END), 0) as has_overbid,
                COALESCE(SUM(CASE WHEN l.data_grade != 'REJECT' AND l.overbid_amount IS NOT NULL AND l.overbid_amount > 0 THEN 1 ELSE 0 END), 0) as has_positive_overbid
            FROM county_profiles cp
            LEFT JOIN leads l ON l.county = cp.county
            GROUP BY cp.county, cp.platform_type
        """).fetchall()

        # ── Last ingestion run per county ──────────────────────────────────
        now_ts = int(__import__("time").time())
        try:
            _ir_cols = {r[1] for r in conn.execute("PRAGMA table_info(ingestion_runs)").fetchall()}
            _has_browser = "browser_count" in _ir_cols
            _extra = ", ir.browser_count, ir.db_count, ir.delta" if _has_browser else ""
            run_rows = conn.execute(f"""
                SELECT ir.county, ir.start_ts, ir.status, ir.cases_processed{_extra}
                FROM ingestion_runs ir
                INNER JOIN (
                    SELECT county, MAX(start_ts) max_ts FROM ingestion_runs GROUP BY county
                ) latest ON ir.county = latest.county AND ir.start_ts = latest.max_ts
            """).fetchall()
            runs_by_county = {}
            for r in run_rows:
                runs_by_county[r["county"]] = {
                    "last_run_age_days": round((now_ts - r["start_ts"]) / 86400, 1) if r["start_ts"] else None,
                    "last_run_status": r["status"],
                    "cases_processed": r["cases_processed"],
                    "browser_count": r["browser_count"] if _has_browser else 0,
                    "db_count": r["db_count"] if _has_browser else 0,
                    "delta": r["delta"] if _has_browser else 0,
                }
        except Exception:
            runs_by_county = {}

        # ── Parser drift from county_ingestion_runs ─────────────────────────
        try:
            cir_rows = conn.execute("""
                SELECT cir.county, cir.browser_count, cir.db_count, cir.delta, cir.status
                FROM county_ingestion_runs cir
                INNER JOIN (
                    SELECT county, MAX(run_ts) max_ts FROM county_ingestion_runs GROUP BY county
                ) latest ON cir.county = latest.county AND cir.run_ts = latest.max_ts
            """).fetchall()
            drift_by_county = {r["county"]: dict(r) for r in cir_rows}
        except Exception:
            drift_by_county = {}

        # ── Evidence doc counts per county ─────────────────────────────────
        try:
            ev_rows = conn.execute("""
                SELECT LOWER(SUBSTR(ed.asset_id, 17,
                       INSTR(SUBSTR(ed.asset_id, 17), ':') - 1)) as county,
                       COUNT(DISTINCT l.id) as leads_with_evidence
                FROM evidence_documents ed
                JOIN leads l ON l.id = ed.asset_id
                WHERE ed.asset_id LIKE 'FORECLOSURE:CO:%'
                GROUP BY county
            """).fetchall()
            evidence_by_county = {r["county"]: r["leads_with_evidence"] for r in ev_rows}
        except Exception:
            evidence_by_county = {}

        # ── Build per-county health records ────────────────────────────────
        counties_out = []
        healthy = warning = critical = 0
        for r in quality_rows:
            county = r["county"] or ""
            platform = r["platform_type"] or "unknown"
            total = r["total"] or 0
            gold = r["gold"] or 0
            silver = r["silver"] or 0
            bronze = r["bronze"] or 0
            has_sale_date = r["has_sale_date"] or 0
            has_overbid = r["has_overbid"] or 0
            leads_with_ev = evidence_by_county.get(county, 0)

            gold_pct = round(gold / max(gold + silver + bronze, 1) * 100, 1)
            sale_date_coverage_pct = round(has_sale_date / max(total, 1) * 100, 1) if total > 0 else 0
            extraction_rate_pct = round(has_overbid / max(total - (r["reject"] or 0), 1) * 100, 1) if total > 0 else 0
            evidence_pct = round(leads_with_ev / max(total, 1) * 100, 1) if total > 0 else 0

            run = runs_by_county.get(county, {})
            last_run_age_days = run.get("last_run_age_days")
            last_run_status = run.get("last_run_status")
            browser_count = run.get("browser_count", 0) or 0
            db_count = run.get("db_count", 0) or 0
            delta = run.get("delta", 0) or 0

            # Drift from county_ingestion_runs (more granular)
            drift_info = drift_by_county.get(county, {})
            cir_browser = drift_info.get("browser_count") or 0
            cir_db = drift_info.get("db_count") or 0
            cir_delta = drift_info.get("delta") or 0
            parser_drift = cir_browser > 0 and abs(cir_delta) > max(2, cir_browser * 0.05)

            # Counties with platform_type='unknown' are paper-only or unresearched —
            # they have no automated scraper and should NOT count as CRITICAL.
            is_unsupported = platform == "unknown"

            # Health score (0-100)
            if is_unsupported:
                # Unsupported counties get a neutral mid-range score so they
                # don't drag down the CRITICAL count.
                health_score = 50
                alert = "NO_PLATFORM"
            else:
                s = 0
                if gold_pct >= 30:   s += 25
                elif gold_pct >= 10: s += 15
                elif gold_pct >= 1:  s += 5
                s += min(25, int(sale_date_coverage_pct * 0.25))
                s += min(20, int(extraction_rate_pct * 0.20))
                s += min(20, int(evidence_pct * 0.20))
                if last_run_age_days is not None and last_run_age_days <= 7:   s += 10
                elif last_run_age_days is None or last_run_age_days > 30:       s -= 10
                if total == 0: s = 0
                health_score = max(0, min(100, s))

                # Alert (worst-first priority)
                alert = None
                if total == 0:                                      alert = "NO_DATA"
                elif last_run_age_days and last_run_age_days > 30: alert = "STALE_30D"
                elif last_run_age_days and last_run_age_days > 7:  alert = "STALE_7D"
                elif parser_drift:                                  alert = "PARSER_DRIFT"
                elif gold == 0 and silver == 0 and bronze > 0:    alert = "ALL_BRONZE"

            if is_unsupported:
                # Count unsupported counties as warning, not critical
                warning += 1
            elif health_score >= 70:   healthy += 1
            elif health_score >= 40: warning += 1
            else:                    critical += 1

            counties_out.append({
                "county": county,
                "platform_type": platform,
                "total": total,
                "gold": gold, "silver": silver, "bronze": bronze,
                "gold_pct": gold_pct,
                "health_score": health_score,
                "sale_date_coverage_pct": sale_date_coverage_pct,
                "extraction_rate_pct": extraction_rate_pct,
                "evidence_pct": evidence_pct,
                "last_run_age_days": last_run_age_days,
                "last_run_status": last_run_status,
                "browser_count": cir_browser or browser_count,
                "db_count": cir_db or db_count,
                "delta": cir_delta or delta,
                "parser_drift": parser_drift,
                "alert": alert,
            })

        # Persist health scores back to county_profiles
        for rec in counties_out:
            try:
                conn.execute("""
                    UPDATE county_profiles SET
                        health_score = ?, sale_date_coverage_pct = ?,
                        evidence_pct = ?, extraction_rate_pct = ?,
                        last_health_check_ts = ?, health_alert = ?
                    WHERE county = ?
                """, [
                    rec["health_score"], int(rec["sale_date_coverage_pct"]),
                    int(rec["evidence_pct"]), int(rec["extraction_rate_pct"]),
                    now_ts, rec["alert"], rec["county"],
                ])
            except Exception:
                pass
        conn.commit()
        conn.close()

        counties_out.sort(key=lambda x: (-x["total"], -x["health_score"]))
        return {
            "counties": counties_out,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": {"healthy": healthy, "warning": warning, "critical": critical, "total": len(counties_out)},
        }

    return await _run_in_db(_query)


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


@app.get("/api/admin/override-log")
async def admin_override_log_endpoint(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    """Paginated list of admin override actions only (separate from general audit log)."""
    user = _require_user(request)
    if not _effective_admin(user):
        raise HTTPException(403, detail="Admin required.")
    conn = _get_conn()
    try:
        offset = (page - 1) * limit
        rows = conn.execute(
            "SELECT * FROM admin_override_log "
            "WHERE action IN ('admin_override_unlock', 'admin_force_unlock', 'admin_preview') "
            "ORDER BY created_ts DESC LIMIT ? OFFSET ?",
            [limit, offset]
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM admin_override_log "
            "WHERE action IN ('admin_override_unlock', 'admin_force_unlock', 'admin_preview')"
        ).fetchone()[0]
        return {
            "entries": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "pages": (total + limit - 1) // limit,
        }
    finally:
        conn.close()


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

        # Field evidence — evidence_documents.asset_id = lead.id (UUID)
        field_evidence = []
        try:
            rows = conn.execute(
                """SELECT fe.* FROM field_evidence fe
                   JOIN evidence_documents ed ON ed.id = fe.evidence_doc_id
                   WHERE ed.asset_id = ?
                   ORDER BY fe.created_ts DESC""",
                [lead_id],
            ).fetchall()
            field_evidence = [dict(r) for r in rows]
        except Exception:
            pass

        # Evidence documents — asset_id = lead.id (UUID), not canonical key
        evidence_docs = []
        try:
            rows = conn.execute(
                "SELECT id, asset_id, filename, doc_family, bytes, retrieved_ts FROM evidence_documents WHERE asset_id = ? ORDER BY retrieved_ts DESC",
                [lead_id],
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
    """Admin: reject attorney verification. reason_code required."""
    admin = _require_user(request)
    if not _is_admin(admin):
        raise HTTPException(status_code=403, detail="Admin only.")
    body = await request.json()
    user_id = body.get("user_id", "")
    reason_code = str(body.get("reason_code", body.get("reason", ""))).strip()

    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required.")

    conn = _get_conn()
    try:
        _admin_override_log(conn, admin["user_id"], "attorney_reject", reason_code,
                            target_user_id=user_id, old_value="PENDING", new_value="REJECTED")
        conn.execute(
            "UPDATE users SET attorney_status = 'REJECTED', verified_attorney = 0 WHERE user_id = ?",
            [user_id],
        )
        _audit_log(conn, user_id, "attorney_rejected", {
            "rejected_by": admin["user_id"],
            "reason": reason_code,
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
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    reason_code = str(body.get("reason_code", body.get("reason", ""))).strip() if body else ""
    conn = _get_conn()
    try:
        row = conn.execute("SELECT email, is_admin FROM users WHERE user_id = ?", [user_id]).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found.")
        if row["is_admin"]:
            raise HTTPException(status_code=400, detail="Cannot deactivate admin accounts.")
        _admin_override_log(conn, admin["user_id"], "deactivate_user", reason_code or "admin_action",
                            target_user_id=user_id, old_value="active", new_value="inactive")
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
    reason_code = str(body.get("reason_code", note)).strip()
    if delta == 0:
        raise HTTPException(status_code=400, detail="delta must be non-zero.")

    conn = _get_conn()
    try:
        row = conn.execute("SELECT email FROM users WHERE user_id = ?", [user_id]).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found.")
        now_iso = datetime.now(timezone.utc).isoformat()
        # Insert a non-expiring ledger entry for positive, or consume from balance for negative
        import time as _t
        if delta > 0:
            conn.execute(
                "INSERT INTO unlock_ledger_entries "
                "(id, user_id, qty_total, qty_remaining, source, expires_ts) "
                "VALUES (?, ?, ?, ?, 'admin_adjustment', NULL)",
                [str(uuid.uuid4()), user_id, delta, delta],
            )
        else:
            # Burn credits: reduce qty_remaining across entries
            remove = abs(delta)
            entries = conn.execute(
                "SELECT id, qty_remaining FROM unlock_ledger_entries "
                "WHERE user_id = ? AND qty_remaining > 0 "
                "ORDER BY CASE WHEN expires_ts IS NULL THEN 1 ELSE 0 END, expires_ts, created_at",
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
        _admin_override_log(conn, admin["user_id"], "adjust_credits", reason_code or "admin_action",
                            target_user_id=user_id,
                            old_value=None, new_value=str(delta))
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
    reason_code = str(body.get("reason_code", body.get("reason", ""))).strip()
    allowed = ("public", "approved_attorney", "admin")
    if new_role not in allowed:
        raise HTTPException(status_code=400, detail=f"role must be one of: {', '.join(allowed)}")
    conn = _get_conn()
    try:
        row = conn.execute("SELECT email, role FROM users WHERE user_id = ?", [user_id]).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found.")
        _admin_override_log(conn, admin["user_id"], "set_role", reason_code or "admin_action",
                            target_user_id=user_id, old_value=row["role"], new_value=new_role)
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
    """Admin: manually override a lead's data_grade. reason_code required."""
    admin = _require_user(request)
    if not _is_admin(admin):
        raise HTTPException(status_code=403, detail="Admin only.")
    body = await request.json()
    new_grade = str(body.get("grade", "")).strip().upper()
    allowed_grades = ("GOLD", "SILVER", "BRONZE", "REJECT")
    if new_grade not in allowed_grades:
        raise HTTPException(status_code=400, detail=f"grade must be one of: {', '.join(allowed_grades)}")
    reason_code = str(body.get("reason_code", body.get("reason", ""))).strip()
    conn = _get_conn()
    try:
        row = conn.execute("SELECT county, case_number, data_grade FROM leads WHERE id = ?", [lead_id]).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Lead not found.")
        _admin_override_log(conn, admin["user_id"], "grade_override", reason_code,
                            target_lead_id=lead_id, old_value=row["data_grade"], new_value=new_grade)
        conn.execute("UPDATE leads SET data_grade = ?, updated_at = datetime('now') WHERE id = ?", [new_grade, lead_id])
        _audit_log(conn, admin["user_id"], "grade_override", {
            "lead_id": lead_id, "old_grade": row["data_grade"], "new_grade": new_grade,
            "reason": reason_code, "county": row["county"], "case_number": row["case_number"],
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


def _compute_lead_completeness(row: dict) -> int:
    """Compute data completeness score 0-100.
    Weights reflect what attorneys actually need to work a case.
    """
    score = 0
    if row.get("case_number"):                                       score += 5
    if row.get("county"):                                            score += 5
    if row.get("winning_bid") or row.get("opening_bid"):             score += 10
    if row.get("total_debt") or row.get("overbid_amount"):           score += 10
    surplus = row.get("surplus_amount") or row.get("overbid_amount") or 0
    if surplus and float(surplus) > 0:                               score += 15
    sale_date = row.get("sale_date") or row.get("scheduled_sale_date")
    if sale_date:                                                     score += 15
    if row.get("owner_name") and row.get("owner_name", "").strip():  score += 20
    if row.get("property_address") and row.get("property_address", "").strip(): score += 20
    return min(score, 100)


def _compute_data_tier(row: dict) -> str:
    """Classify lead data quality tier for display and filtering.
    ENRICHED  — has owner + address + sale_date + surplus > 0
    PARTIAL   — has some identifying fields but incomplete
    MONITORING — raw scraper record, case number only
    """
    owner    = bool(row.get("owner_name", "").strip() if row.get("owner_name") else False)
    addr     = bool(row.get("property_address", "").strip() if row.get("property_address") else False)
    sale     = bool(row.get("sale_date") or row.get("scheduled_sale_date"))
    surplus  = float(row.get("surplus_amount") or row.get("overbid_amount") or 0) > 0
    pool_src = row.get("pool_source", "UNVERIFIED")

    if pool_src in ("VOUCHER", "LEDGER", "HTML_MATH") and owner and addr and sale and surplus:
        return "ENRICHED"
    if (owner or addr) and (sale or surplus):
        return "PARTIAL"
    if owner or addr or sale or surplus:
        return "PARTIAL"
    return "MONITORING"


@app.get("/api/leads/pre-sale")
@limiter.limit("100/minute")
async def get_presale_leads(
    request: Request,
    county: Optional[str] = Query(None),
    has_data: bool = Query(False),
    data_tier: Optional[str] = Query(None),
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
            base_where = (" WHERE (processing_status = 'PRE_SALE'"
                         " OR (scheduled_sale_date IS NOT NULL AND scheduled_sale_date > date('now'))"
                         " OR (sale_date IS NOT NULL AND sale_date > date('now')))")
            params: list = []
            if county:
                base_where += " AND county = ?"
                params.append(county)
            if has_data:
                base_where += " AND (owner_name IS NOT NULL AND owner_name != '' OR surplus_amount > 0)"
            if data_tier == "ENRICHED":
                base_where += (" AND owner_name IS NOT NULL AND owner_name != ''"
                               " AND property_address IS NOT NULL AND property_address != ''"
                               " AND (sale_date IS NOT NULL OR scheduled_sale_date IS NOT NULL)"
                               " AND COALESCE(surplus_amount, overbid_amount, 0) > 0")
            elif data_tier == "PARTIAL":
                base_where += (" AND (owner_name IS NOT NULL OR property_address IS NOT NULL"
                               " OR COALESCE(surplus_amount, overbid_amount, 0) > 0)")
            elif data_tier == "MONITORING":
                base_where += (" AND (owner_name IS NULL OR owner_name = '')"
                               " AND (property_address IS NULL OR property_address = '')"
                               " AND COALESCE(surplus_amount, overbid_amount, 0) = 0")

            total = conn.execute(
                f"SELECT COUNT(*) FROM leads{base_where}", params
            ).fetchone()[0]

            county_rows = conn.execute(
                f"""SELECT county,
                           COUNT(*) cnt,
                           SUM(CASE WHEN owner_name IS NOT NULL AND owner_name != '' THEN 1 ELSE 0 END) with_owner,
                           SUM(CASE WHEN COALESCE(surplus_amount, overbid_amount, 0) > 0 THEN 1 ELSE 0 END) with_surplus,
                           SUM(CASE WHEN sale_date IS NOT NULL OR scheduled_sale_date IS NOT NULL THEN 1 ELSE 0 END) with_sale_date,
                           SUM(CASE WHEN owner_name IS NOT NULL AND owner_name != ''
                                    AND property_address IS NOT NULL AND property_address != ''
                                    AND (sale_date IS NOT NULL OR scheduled_sale_date IS NOT NULL)
                                    AND COALESCE(surplus_amount, overbid_amount, 0) > 0
                               THEN 1 ELSE 0 END) fully_enriched,
                           SUM(COALESCE(surplus_amount, overbid_amount, 0)) pipeline_surplus
                    FROM leads{base_where}
                    GROUP BY county ORDER BY pipeline_surplus DESC, cnt DESC""",
                params,
            ).fetchall()

            # Order: fully enriched first (completeness DESC), then by surplus
            rows = conn.execute(
                f"""SELECT id, county, case_number, owner_name, property_address,
                           scheduled_sale_date, sale_date, ned_recorded_date,
                           opening_bid, surplus_amount, overbid_amount, winning_bid, total_debt,
                           lender_name, ned_source, data_grade, ingestion_source, pool_source,
                           updated_at
                    FROM leads{base_where}
                    ORDER BY
                        (CASE WHEN owner_name IS NOT NULL AND owner_name != '' THEN 20 ELSE 0 END
                         + CASE WHEN property_address IS NOT NULL AND property_address != '' THEN 20 ELSE 0 END
                         + CASE WHEN sale_date IS NOT NULL OR scheduled_sale_date IS NOT NULL THEN 15 ELSE 0 END
                         + CASE WHEN COALESCE(surplus_amount, overbid_amount, 0) > 0 THEN 15 ELSE 0 END
                         + CASE WHEN winning_bid IS NOT NULL OR opening_bid IS NOT NULL THEN 10 ELSE 0 END
                         + CASE WHEN total_debt IS NOT NULL OR overbid_amount IS NOT NULL THEN 10 ELSE 0 END
                         + CASE WHEN case_number IS NOT NULL THEN 5 ELSE 0 END
                         + CASE WHEN county IS NOT NULL THEN 5 ELSE 0 END) DESC,
                        COALESCE(surplus_amount, overbid_amount, 0) DESC,
                        county ASC
                    LIMIT ? OFFSET ?""",
                params + [limit, offset],
            ).fetchall()
        finally:
            conn.close()

        def _enrich_lead(r: dict) -> dict:
            completeness = _compute_lead_completeness(r)
            tier = _compute_data_tier(r)
            sale = r.get("sale_date") or r.get("scheduled_sale_date")
            # Expected action date = 6 months after sale (C.R.S. § 38-38-111(5) restriction)
            expected_action_date = None
            if sale:
                try:
                    import datetime as _dt
                    sale_dt = _dt.date.fromisoformat(sale[:10])
                    expected_action_date = (sale_dt + _dt.timedelta(days=183)).isoformat()
                except Exception:
                    pass
            return {**r, "data_completeness": completeness, "data_tier": tier, "expected_action_date": expected_action_date}

        return {
            "count": len(rows),
            "total": total,
            "limit": limit,
            "offset": offset,
            "county_breakdown": [dict(r) for r in county_rows],
            "leads": [_enrich_lead(dict(r)) for r in rows],
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
        # Use resolved lead UUID for evidence_documents lookup (asset_id = lead.id)
        evidence_asset_id = lead_row["id"] if lead_row else None
        rows = conn.execute(
            """SELECT id, asset_id, filename, doc_type, doc_family,
                      file_path, file_sha256, bytes, content_type, retrieved_ts
               FROM evidence_documents
               WHERE asset_id = ?
               ORDER BY doc_family, filename""",
            [evidence_asset_id or asset_id],
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
    _is_verified_atty = (
        user.get("role") in ("approved_attorney", "admin")
        or user.get("attorney_status") in ("VERIFIED", "APPROVED")
        or user.get("verified_attorney") == 1
        or _effective_admin(user, request)
    )
    if not _is_verified_atty:
        raise HTTPException(status_code=403, detail="Attorney verification required to access evidence documents.")

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


# ── EPIC 2A: Global Search Endpoint ─────────────────────────────────

@app.get("/api/search")
@limiter.limit("60/minute")
async def search_leads(request: Request, q: str = "", limit: int = Query(20, ge=1, le=100)):
    """Search leads by case_number, property_address, owner_name, or county. Requires auth."""
    user = _require_user(request)
    if not q or len(q.strip()) < 2:
        return []

    def _search(q=q, limit=limit):
        conn = _thread_conn()
        try:
            term = f"%{q.strip()}%"
            rows = conn.execute("""
                SELECT id as asset_id, case_number, property_address, county,
                       data_grade, overbid_amount
                FROM leads
                WHERE case_number LIKE ? OR property_address LIKE ?
                   OR owner_name LIKE ? OR county = ?
                ORDER BY
                  CASE data_grade WHEN 'GOLD' THEN 1 WHEN 'SILVER' THEN 2 WHEN 'BRONZE' THEN 3 ELSE 4 END,
                  overbid_amount DESC
                LIMIT ?
            """, [term, term, term, q.strip().lower(), limit]).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    return await _run_in_db(_search)


# ── EPIC 2C: Case Timeline Endpoint ─────────────────────────────────

@app.get("/api/lead/{asset_id}/timeline")
async def get_lead_timeline(asset_id: str, request: Request):
    """Return chronological case events from pipeline_events + audit_log."""
    user = _require_user(request)

    def _timeline(asset_id=asset_id):
        conn = _thread_conn()
        try:
            events = []
            # pipeline_events
            if _table_exists_conn(conn, "pipeline_events"):
                rows = conn.execute("""
                    SELECT event_type, notes, created_at as ts
                    FROM pipeline_events WHERE asset_id = ?
                    ORDER BY created_at ASC
                """, [asset_id]).fetchall()
                for r in rows:
                    events.append({
                        "ts": r["ts"],
                        "event_type": r["event_type"],
                        "notes": r["notes"],
                        "source": "pipeline",
                    })
            # audit_log for this lead
            if _table_exists_conn(conn, "audit_log"):
                rows = conn.execute("""
                    SELECT action as event_type, meta_json as notes, created_at as ts
                    FROM audit_log WHERE resource_id = ? OR meta_json LIKE ?
                    ORDER BY created_at ASC
                    LIMIT 50
                """, [asset_id, f"%{asset_id}%"]).fetchall()
                for r in rows:
                    events.append({
                        "ts": r["ts"],
                        "event_type": r["event_type"],
                        "notes": r["notes"],
                        "source": "audit",
                    })
            events.sort(key=lambda x: x.get("ts") or "")
            return events
        finally:
            conn.close()

    return await _run_in_db(_timeline)


# ── EPIC 2E: Coverage Map Endpoint ──────────────────────────────────

@app.get("/api/coverage-map")
async def get_coverage_map():
    """Return county array for CO coverage choropleth. No auth required."""
    def _map():
        conn = _thread_conn()
        try:
            rows = conn.execute("""
                SELECT
                    cp.county as county_slug,
                    cp.platform_type,
                    cp.access_method,
                    cp.last_verified_ts as last_scraped_at,
                    COALESCE(cp.digital_accessible, 0) as digital_accessible,
                    COUNT(CASE WHEN l.data_grade = 'GOLD' THEN 1 END) as gold_count,
                    COUNT(CASE WHEN l.data_grade = 'SILVER' THEN 1 END) as silver_count,
                    COUNT(CASE WHEN l.data_grade = 'BRONZE' THEN 1 END) as bronze_count,
                    COUNT(l.id) as total_leads
                FROM county_profiles cp
                LEFT JOIN leads l ON l.county = cp.county
                GROUP BY cp.county
            """).fetchall()

            result = []
            for r in rows:
                gold = r["gold_count"] or 0
                silver = r["silver_count"] or 0
                bronze = r["bronze_count"] or 0
                total = r["total_leads"] or 0

                if gold > 0 or silver > 0:
                    status = "active"
                elif bronze > 0:
                    status = "partial"
                elif r["digital_accessible"]:
                    status = "configured"
                else:
                    status = "no_data"

                county_slug = r["county_slug"]
                county_name = county_slug.replace("_", " ").title() + " County"

                result.append({
                    "county_slug": county_slug,
                    "county_name": county_name,
                    "status": status,
                    "gold_count": gold,
                    "silver_count": silver,
                    "bronze_count": bronze,
                    "total_leads": total,
                    "last_scraped_at": r["last_scraped_at"],
                    "access_method": r["access_method"] or r["platform_type"] or "unknown",
                })
            return result
        finally:
            conn.close()

    return await _run_in_db(_map)


# ── EPIC 2I: API Key Endpoints ───────────────────────────────────────

@app.post("/api/admin/users/{user_id}/api-key")
async def generate_api_key(user_id: str, request: Request):
    """Generate a new API key for a user. Admin only."""
    _require_admin_or_api_key(request)
    import secrets as _secrets
    raw_key = "vf_" + _secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    now_str = datetime.now(timezone.utc).isoformat()

    def _store(user_id=user_id, key_hash=key_hash, now_str=now_str):
        conn = _thread_conn()
        try:
            conn.execute(
                "UPDATE users SET api_key_hash = ?, api_key_created_at = ? WHERE user_id = ?",
                [key_hash, now_str, user_id]
            )
            conn.commit()
        finally:
            conn.close()

    await _run_in_db(_store)
    return {
        "api_key": raw_key,
        "created_at": now_str,
        "note": "Store this key — it will not be shown again.",
    }


@app.get("/api/admin/users/{user_id}/api-key-status")
async def get_api_key_status(user_id: str, request: Request):
    """Return whether a user has an API key configured. Admin only."""
    _require_admin_or_api_key(request)

    def _status(user_id=user_id):
        conn = _thread_conn()
        try:
            row = conn.execute(
                "SELECT api_key_hash, api_key_created_at FROM users WHERE user_id = ?",
                [user_id]
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="User not found")
            return {"has_key": bool(row["api_key_hash"]), "created_at": row["api_key_created_at"]}
        finally:
            conn.close()

    return await _run_in_db(_status)


@app.delete("/api/admin/users/{user_id}/api-key")
async def revoke_api_key(user_id: str, request: Request):
    """Revoke a user's API key. Admin only."""
    _require_admin_or_api_key(request)

    def _revoke(user_id=user_id):
        conn = _thread_conn()
        try:
            conn.execute(
                "UPDATE users SET api_key_hash = NULL, api_key_created_at = NULL WHERE user_id = ?",
                [user_id]
            )
            conn.commit()
        finally:
            conn.close()

    await _run_in_db(_revoke)
    return {"status": "revoked"}


# ── EPIC 4A: Attorney Cases Endpoints ───────────────────────────────

@app.get("/api/my-cases")
async def list_my_cases(request: Request):
    """List all attorney cases for the authenticated user."""
    user = _require_user(request)
    user_id = user["user_id"]

    def _list(user_id=user_id):
        conn = _thread_conn()
        try:
            rows = conn.execute("""
                SELECT ac.id, ac.asset_id, ac.stage, ac.outcome_type, ac.notes,
                       ac.created_at, ac.updated_at,
                       l.case_number, l.county, l.data_grade, l.overbid_amount,
                       l.property_address, l.sale_date
                FROM attorney_cases ac
                JOIN leads l ON l.id = ac.asset_id
                WHERE ac.user_id = ?
                ORDER BY ac.updated_at DESC
            """, [user_id]).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    return await _run_in_db(_list)


class AttorneyCaseCreate(BaseModel):
    asset_id: str
    stage: str = "LEADS"
    notes: Optional[str] = None


@app.post("/api/my-cases")
async def create_my_case(body: AttorneyCaseCreate, request: Request):
    """Create a new attorney case tracker entry."""
    user = _require_user(request)
    user_id = user["user_id"]
    import uuid as _uuid
    case_id = _uuid.uuid4().hex

    def _create(user_id=user_id, case_id=case_id):
        conn = _thread_conn()
        try:
            conn.execute("""
                INSERT INTO attorney_cases (id, asset_id, user_id, stage, notes)
                VALUES (?, ?, ?, ?, ?)
            """, [case_id, body.asset_id, user_id, body.stage, body.notes])
            conn.commit()
            return {"id": case_id, "asset_id": body.asset_id, "stage": body.stage}
        finally:
            conn.close()

    return await _run_in_db(_create)


_VALID_CASE_STAGES = {"LEADS", "CONTACTED", "RETAINER_SIGNED", "FILED", "FUNDS_RELEASED"}
_VALID_OUTCOME_TYPES = {"WON", "LOST", "SETTLED", "WITHDRAWN", "PENDING"}


class AttorneyCasePatch(BaseModel):
    stage: Optional[str] = None
    notes: Optional[str] = None
    outcome_type: Optional[str] = None
    outcome_notes: Optional[str] = None
    outcome_funds_cents: Optional[int] = None

    def validate_stage(self) -> None:
        if self.stage and self.stage.upper() not in _VALID_CASE_STAGES:
            raise ValueError(f"Invalid stage. Must be one of: {sorted(_VALID_CASE_STAGES)}")
        if self.outcome_type and self.outcome_type.upper() not in _VALID_OUTCOME_TYPES:
            raise ValueError(f"Invalid outcome_type. Must be one of: {sorted(_VALID_OUTCOME_TYPES)}")


@app.patch("/api/my-cases/{case_id}")
async def update_my_case(case_id: str, body: AttorneyCasePatch, request: Request):
    """Update stage, notes, or outcome for an attorney case."""
    user = _require_user(request)
    user_id = user["user_id"]
    try:
        body.validate_stage()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    def _update(user_id=user_id, case_id=case_id):
        conn = _thread_conn()
        try:
            row = conn.execute(
                "SELECT id FROM attorney_cases WHERE id = ? AND user_id = ?",
                [case_id, user_id]
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Case not found")
            updates = []
            vals = []
            if body.stage is not None:
                updates.append("stage = ?"); vals.append(body.stage)
            if body.notes is not None:
                updates.append("notes = ?"); vals.append(body.notes)
            if body.outcome_type is not None:
                updates.append("outcome_type = ?"); vals.append(body.outcome_type)
            if body.outcome_notes is not None:
                updates.append("outcome_notes = ?"); vals.append(body.outcome_notes)
            if body.outcome_funds_cents is not None:
                updates.append("outcome_funds_cents = ?"); vals.append(body.outcome_funds_cents)
            if updates:
                updates.append("updated_at = datetime('now')")
                conn.execute(
                    f"UPDATE attorney_cases SET {', '.join(updates)} WHERE id = ?",
                    vals + [case_id]
                )
                conn.commit()
            return {"status": "updated"}
        finally:
            conn.close()

    return await _run_in_db(_update)


@app.delete("/api/my-cases/{case_id}")
async def delete_my_case(case_id: str, request: Request):
    """Delete an attorney case tracker entry."""
    user = _require_user(request)
    user_id = user["user_id"]

    def _delete(user_id=user_id, case_id=case_id):
        conn = _thread_conn()
        try:
            conn.execute(
                "DELETE FROM attorney_cases WHERE id = ? AND user_id = ?",
                [case_id, user_id]
            )
            conn.commit()
        finally:
            conn.close()

    await _run_in_db(_delete)
    return {"status": "deleted"}


@app.post("/api/my-cases/{case_id}/outcome")
async def record_case_outcome(case_id: str, request: Request):
    """Record the outcome (funds recovered, notes) for an attorney case."""
    user = _require_user(request)
    user_id = user["user_id"]
    try:
        body = await request.json()
    except Exception:
        body = {}

    def _outcome(user_id=user_id, case_id=case_id, body=body):
        conn = _thread_conn()
        try:
            conn.execute("""
                UPDATE attorney_cases
                SET outcome_type = ?, outcome_notes = ?, outcome_funds_cents = ?,
                    updated_at = datetime('now')
                WHERE id = ? AND user_id = ?
            """, [body.get("outcome_type"), body.get("notes"), body.get("funds_recovered"),
                  case_id, user_id])
            conn.commit()
        finally:
            conn.close()

    await _run_in_db(_outcome)
    return {"status": "recorded"}


# ── EPIC 4C: Title Stack Endpoint ───────────────────────────────────

@app.get("/api/lead/{asset_id}/title-stack")
async def get_title_stack(asset_id: str, request: Request):
    """Return lien records ordered by priority with risk assessment."""
    user = _require_user(request)

    def _stack(asset_id=asset_id):
        conn = _thread_conn()
        try:
            rows = conn.execute("""
                SELECT id, lien_type, lienholder_name, priority, amount_cents, is_open, source
                FROM lien_records WHERE asset_id = ?
                ORDER BY priority ASC, amount_cents DESC
            """, [asset_id]).fetchall()
            liens = [dict(r) for r in rows]
            total_open = sum(r["amount_cents"] for r in liens if r["is_open"])
            open_count = len([r for r in liens if r["is_open"]])
            if len(liens) == 0:
                risk = "LOW"
            elif open_count <= 2:
                risk = "MEDIUM"
            else:
                risk = "HIGH"
            return {"liens": liens, "risk_score": risk, "total_open_cents": total_open}
        finally:
            conn.close()

    return await _run_in_db(_stack)


# ── EPIC 4E: Territory Locking Endpoints ────────────────────────────

@app.get("/api/territories")
async def list_territories(request: Request):
    """List territories locked by the authenticated user."""
    user = _require_user(request)
    user_id = user["user_id"]

    def _list(user_id=user_id):
        conn = _thread_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM attorney_territories WHERE user_id = ? ORDER BY locked_at DESC",
                [user_id]
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    return await _run_in_db(_list)


class TerritoryCreate(BaseModel):
    territory_type: str
    territory_value: str


@app.post("/api/territories")
async def lock_territory(body: TerritoryCreate, request: Request):
    """Lock a territory (county/zip). Requires Sovereign tier."""
    user = _require_user(request)
    user_id = user["user_id"]
    if user.get("tier") not in ("sovereign",):
        raise HTTPException(status_code=403, detail="Territory locking requires Sovereign tier.")

    def _lock(user_id=user_id):
        conn = _thread_conn()
        try:
            conn.execute("""
                INSERT OR IGNORE INTO attorney_territories (user_id, territory_type, territory_value)
                VALUES (?, ?, ?)
            """, [user_id, body.territory_type, body.territory_value])
            conn.commit()
            return {"status": "locked", "territory": body.territory_value}
        finally:
            conn.close()

    return await _run_in_db(_lock)


@app.delete("/api/territories/{territory_id}")
async def release_territory(territory_id: int, request: Request):
    """Release a locked territory."""
    user = _require_user(request)
    user_id = user["user_id"]

    def _release(user_id=user_id, territory_id=territory_id):
        conn = _thread_conn()
        try:
            conn.execute(
                "DELETE FROM attorney_territories WHERE id = ? AND user_id = ?",
                [territory_id, user_id]
            )
            conn.commit()
        finally:
            conn.close()

    await _run_in_db(_release)
    return {"status": "released"}


# ── PDF Intake Endpoint ──────────────────────────────────────────────

from fastapi import UploadFile, File, Form as FastAPIForm


@app.post("/api/intake/pdf-upload")
async def pdf_intake(
    request: Request,
    file: UploadFile = File(...),
    county: str = FastAPIForm(...),
    case_number: str = FastAPIForm(...),
    sale_date: Optional[str] = FastAPIForm(None),
    overbid_amount: Optional[float] = FastAPIForm(None),
):
    """Accept PDF upload for paper-only counties. Creates lead + queues for OCR."""
    import uuid as _uuid
    asset_id = str(_uuid.uuid4())
    pdf_bytes = await file.read()

    # Store PDF to vault
    vault_dir = VAULT_ROOT / county
    vault_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = vault_dir / f"{case_number.replace('/', '_')}.pdf"
    pdf_path.write_bytes(pdf_bytes)

    def _create_lead(asset_id=asset_id):
        conn = _thread_conn()
        try:
            conn.execute("""
                INSERT OR IGNORE INTO leads
                    (id, county, case_number, sale_date, overbid_amount,
                     data_grade, intake_method, verification_state, evidence_storage_location)
                VALUES (?, ?, ?, ?, ?, 'BRONZE', 'pdf_upload', 'RAW', ?)
            """, [asset_id, county, case_number, sale_date, overbid_amount, str(pdf_path)])
            conn.commit()
        finally:
            conn.close()

    await _run_in_db(_create_lead)
    return {
        "asset_id": asset_id,
        "status": "queued",
        "message": "PDF received — queued for OCR extraction",
    }


# ── EPIC 4D: Court Filing Automation ────────────────────────────────

@app.post("/api/lead/{asset_id}/court-filing")
async def generate_court_filing(asset_id: str, request: Request):
    """Generate court filing ZIP — Motion, Notice, Affidavit, Certificate, Exhibits.

    Credit cost: 3 credits (CREDIT_COSTS['filing_pack']) — deducted atomically.
    Admin users are exempt from credit deduction.
    Returns 402 if insufficient credits.
    """
    from verifuse_v2.server.auth import get_current_user as _gcu
    user = _gcu(request)
    user_id = user.get("user_id", "")
    import zipfile, io, textwrap

    # ── 3-credit deduction (skip for admin) ─────────────────────────────
    if not _effective_admin(user):
        _cost = CREDIT_COSTS["filing_pack"]  # 3
        _cf_conn = _get_conn()
        try:
            _cf_conn.execute("BEGIN IMMEDIATE")
            _cf_debits = _fifo_spend(_cf_conn, user_id, _cost)
            if not _cf_debits:
                _cf_conn.execute("ROLLBACK")
                _bal_conn = _get_conn()
                try:
                    _bal = _ledger_balance(_bal_conn, user_id)
                finally:
                    _bal_conn.close()
                raise HTTPException(
                    status_code=402,
                    detail=f"Court Filing Packet requires {_cost} credits. You have {_bal} credit{'s' if _bal != 1 else ''}. Purchase a credit pack on the Pricing page.",
                )
            _audit_log(_cf_conn, user_id, "court_filing_debit", {"asset_id": asset_id, "credits_spent": _cost})
            _cf_conn.execute("COMMIT")
        except HTTPException:
            raise
        except Exception as _cfe:
            log.error("court_filing credit deduct failed user=%s asset=%s: %s", user_id, asset_id, _cfe)
            try:
                _cf_conn.execute("ROLLBACK")
            except Exception:
                pass
            raise HTTPException(500, detail="Credit deduction failed. Please try again.")
        finally:
            _cf_conn.close()

    TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "court_filings"

    def _filing(asset_id=asset_id):
        conn = _thread_conn()
        try:
            row = conn.execute("""
                SELECT case_number, county, sale_date, overbid_amount,
                       property_address, owner_name, calc_hash, pool_source, audit_grade
                FROM leads WHERE id = ?
            """, [asset_id]).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Lead not found")
            return dict(row)
        finally:
            conn.close()

    lead = await _run_in_db(_filing)

    def _render_template(tmpl_path: Path, vars_: dict) -> str:
        text = tmpl_path.read_text() if tmpl_path.exists() else ""
        for k, v in vars_.items():
            text = text.replace(f"{{{{{k}}}}}", str(v or ""))
        return text

    county = lead.get("county", "")
    county_upper = county.replace("_", " ").upper()

    filing_vars = {
        "court_district": "18th",  # Default — attorneys must verify
        "county_upper": county_upper,
        "county_name": county.replace("_", " ").title(),
        "case_number": lead.get("case_number", ""),
        "property_address": lead.get("property_address", ""),
        "sale_date": lead.get("sale_date", ""),
        "overbid_amount": f"{float(lead.get('overbid_amount') or 0):,.2f}",
        "claimant_name": "[CLAIMANT NAME — ATTORNEY TO COMPLETE]",
        "claimant_relationship": "[RELATIONSHIP — e.g., former owner, heir]",
        "attorney_name": user.get("full_name", "[ATTORNEY NAME]"),
        "attorney_bar_number": user.get("bar_number", "[BAR NUMBER]"),
        "attorney_firm": user.get("firm_name", "[FIRM NAME]"),
        "attorney_address": "[ATTORNEY ADDRESS]",
        "attorney_phone": "[ATTORNEY PHONE]",
        "attorney_email": user.get("email", "[ATTORNEY EMAIL]"),
        "filing_date": datetime.now(timezone.utc).strftime("%B %d, %Y"),
        "owner_name": lead.get("owner_name") or "[OWNER NAME — VERIFY]",
        "calculation_hash": lead.get("calc_hash") or "NOT_COMPUTED",
        "calc_engine_version": "surplus_calc_v2",
        "data_sources": lead.get("pool_source") or "UNVERIFIED",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for tmpl_file, out_name in [
            ("motion_for_disbursement.txt", "01_Motion_for_Disbursement.txt"),
            ("notice_of_claim.txt",         "02_Notice_of_Claim.txt"),
            ("affidavit_of_representation.txt", "03_Affidavit_of_Representation.txt"),
            ("certificate_of_service.txt",  "04_Certificate_of_Service.txt"),
            ("exhibit_a_trustee_sale.txt",  "Exhibit_A_Trustee_Sale.txt"),
            ("exhibit_b_property_record.txt", "Exhibit_B_Property_Record.txt"),
        ]:
            tmpl_path = TEMPLATES_DIR / tmpl_file
            content = _render_template(tmpl_path, filing_vars)
            zf.writestr(out_name, content)
        # Add a README
        readme = textwrap.dedent(f"""
            VeriFuse Court Filing Package
            =============================
            Case: {lead.get('case_number')} — {county_upper} County
            Property: {lead.get('property_address')}
            Overbid: ${filing_vars['overbid_amount']}

            IMPORTANT: Review and complete all placeholders before filing.
            Attorney fees are capped at 10% per HB25-1224 (C.R.S. § 38-38-111).
            Verify court district number before filing.

            Generated: {filing_vars['filing_date']}
        """).strip()
        zf.writestr("README.txt", readme)

    buf.seek(0)
    case_num = (lead.get("case_number") or asset_id[:8]).replace("/", "_")
    filename = f"verifuse_filing_{case_num}.zip"

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN OPS CENTER — Pipeline Command Center
# POST /api/admin/ops/run       — trigger a pipeline job
# GET  /api/admin/ops/jobs      — list recent jobs
# GET  /api/admin/ops/jobs/{id} — get job status + output
# POST /api/admin/ops/promote-presale — scan existing leads → PRE_SALE
# ═══════════════════════════════════════════════════════════════════════════════

# ── Allowed commands whitelist (security: never exec arbitrary shell) ──────────
_OPS_WHITELIST: dict[str, list[str]] = {
    # Pre-sale pipeline
    "pending-sales":        ["pending-sales"],
    "pre-sale-scan":        ["pre-sale-scan"],
    # Post-sale scrapers
    "scraper-run-window":   ["scraper-run-window"],
    "scraper-run":          ["scraper-run"],
    "sale-info-backfill":   ["sale-info-backfill"],
    # Extraction
    "extract-batch":        ["extract-batch"],
    "gate4-run-all":        ["gate4-run-all"],
    # Promotion
    "promote-eligible":     ["promote-eligible"],
    # DB ops
    "backup-db":            ["backup-db"],
    "migrate":              ["migrate"],
    # Scraper enum
    "scraper-enum":         ["scraper-enum"],
    # Denver
    "denver-scrape":        ["denver-scrape"],
    # Tax lien
    "tax-lien-run":         ["tax-lien-run"],
    # Assessor
    "assessor-lookup":      ["assessor-lookup"],
    # Owner enrichment + data quality
    "enrich-owners":        ["enrich-owners"],
    "enrich-bronze":        ["enrich-owners", "--all-counties", "--limit", "500"],
    "backfill-sale-dates":  ["pre-sale-scan"],  # triggers promote + date copy via API
    "state-machine-run":    ["promote-eligible"],
    # Unclaimed property
    "unclaimed-seed":           ["unclaimed-seed"],
    "unclaimed-property-run":   ["unclaimed-property-run"],
    "tax-deed-seed":            ["tax-deed-seed"],
    # Promote pre-sale
    "promote-presale":      ["promote-presale"],
    # SOTA verification
    "verify-sota":          ["verify-sota", "--all-gold"],
    # Evidence audit
    "evidence-audit":       ["evidence-audit"],
    # Unclaimed crossref
    "unclaimed-crossref":   ["unclaimed-crossref"],
    # Coverage report
    "coverage-report":      ["coverage-report"],
    # Alert dispatch
    "dispatch-alerts":      ["dispatch-alerts"],
    # OCR processor
    "ocr-processor":        ["ocr-processor"],
}

# ── Background job executor (separate from DB executor) ───────────────────────
_OPS_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=2,  # max 2 concurrent pipeline jobs (scraper is resource-heavy)
    thread_name_prefix="vf-ops",
)

_OUTPUT_MAX_BYTES = 65_536  # 64 KB max job output stored in DB


def _run_ops_job(job_id: str, vf_args: list[str]) -> None:
    """Execute a bin/vf command in a subprocess and track output in ops_jobs."""
    import subprocess
    import threading

    proj_root = str(Path(VERIFUSE_DB_PATH).parent.parent.parent)
    vf_bin = str(Path(proj_root) / "bin" / "vf")
    # Use explicit bash path — subprocess environment may not have /usr/bin/env bash
    bash_bin = "/bin/bash"

    conn = _get_conn()
    try:
        started = int(_time.time())
        conn.execute(
            "UPDATE ops_jobs SET status='RUNNING', started_at=? WHERE id=?",
            [started, job_id],
        )
        conn.commit()
    finally:
        conn.close()

    output_chunks: list[str] = []
    exit_code = -1

    try:
        proc = subprocess.Popen(
            [bash_bin, vf_bin] + vf_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=proj_root,
            env={**os.environ,
                 "VERIFUSE_DB_PATH": VERIFUSE_DB_PATH,
                 # Ensure venv python comes first, then system utils
                 "PATH": str(Path(proj_root) / ".venv" / "bin") + ":/usr/bin:/bin:/usr/local/bin:" + os.environ.get("PATH", ""),
                 # Ensure project root is in Python path for module imports
                 "PYTHONPATH": proj_root + ":" + os.environ.get("PYTHONPATH", "")},
        )

        def _stream():
            for line in proc.stdout:  # type: ignore[union-attr]
                output_chunks.append(line)
                # Flush partial output to DB every 20 lines
                if len(output_chunks) % 20 == 0:
                    _flush_output(job_id, output_chunks)

        t = threading.Thread(target=_stream, daemon=True)
        t.start()
        proc.wait(timeout=1800)  # 30-min hard cap
        t.join(timeout=5)
        exit_code = proc.returncode

    except subprocess.TimeoutExpired:
        proc.kill()  # type: ignore[possibly-undefined]
        output_chunks.append("\n[TIMEOUT] Job exceeded 30-minute limit and was killed.\n")
        exit_code = -9
    except Exception as exc:
        output_chunks.append(f"\n[ERROR] {exc}\n")
        exit_code = -1
    finally:
        finished = int(_time.time())
        status = "SUCCESS" if exit_code == 0 else "FAILED"
        raw_output = "".join(output_chunks)
        if len(raw_output.encode()) > _OUTPUT_MAX_BYTES:
            # Keep last 64KB
            raw_output = "...[truncated]\n" + raw_output[-_OUTPUT_MAX_BYTES:]

        conn2 = _get_conn()
        try:
            conn2.execute(
                "UPDATE ops_jobs SET status=?, finished_at=?, output=?, exit_code=? WHERE id=?",
                [status, finished, raw_output, exit_code, job_id],
            )
            conn2.commit()
        finally:
            conn2.close()

    log.info("[ops_job] %s finished: exit=%d status=%s", job_id, exit_code, status)


def _flush_output(job_id: str, chunks: list[str]) -> None:
    """Write partial output to DB without changing status (live tail)."""
    try:
        raw = "".join(chunks)
        if len(raw.encode()) > _OUTPUT_MAX_BYTES:
            raw = "...[truncated]\n" + raw[-_OUTPUT_MAX_BYTES:]
        c = _get_conn()
        c.execute("UPDATE ops_jobs SET output=? WHERE id=?", [raw, job_id])
        c.commit()
        c.close()
    except Exception:
        pass


class OpsRunRequest(BaseModel):
    command: str
    county: Optional[str] = None
    extra_args: list[str] = []


@app.post("/api/admin/ops/run")
@limiter.limit("20/minute")
async def ops_run(body: OpsRunRequest, request: Request):
    """Trigger a pipeline job from the Admin Ops Center.

    Security: command must be in _OPS_WHITELIST. Args are passed as a fixed
    list — no shell interpolation possible.
    """
    user = _require_user(request)
    if not _effective_admin(user, request):
        raise HTTPException(status_code=403, detail="Admin only.")

    if body.command not in _OPS_WHITELIST:
        raise HTTPException(
            status_code=400,
            detail=f"Command '{body.command}' not allowed. Allowed: {sorted(_OPS_WHITELIST.keys())}",
        )

    # Build safe arg list: base command + optional county + extra args (whitelist-validated)
    base_args = list(_OPS_WHITELIST[body.command])
    if body.county:
        # County must be a simple slug: only lowercase letters, digits, underscore
        import re as _re
        if not _re.match(r'^[a-z_]{2,30}$', body.county):
            raise HTTPException(status_code=400, detail="Invalid county slug.")
        base_args += ["--county", body.county]

    # Validate extra_args: only allow safe flag patterns
    safe_extras: list[str] = []
    for arg in body.extra_args[:8]:
        if _re.match(r'^(--[a-z][a-z0-9-]{1,30}(=[a-zA-Z0-9._-]{1,60})?)$|^([0-9]{1,6})$', arg):
            safe_extras.append(arg)
        else:
            raise HTTPException(status_code=400, detail=f"Unsafe extra arg: {arg!r}")
    vf_args = base_args + safe_extras

    job_id = str(uuid.uuid4())
    now = int(_time.time())

    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO ops_jobs (id, command, args_json, status, triggered_by, triggered_at, county)
               VALUES (?, ?, ?, 'QUEUED', ?, ?, ?)""",
            [job_id, body.command, json.dumps(vf_args), user.get("email", "admin"), now, body.county],
        )
        conn.commit()
    finally:
        conn.close()

    # Fire-and-forget in the ops executor
    _OPS_EXECUTOR.submit(_run_ops_job, job_id, vf_args)

    log.info("[ops] %s triggered job %s: %s", user.get("email"), job_id, vf_args)
    return {"job_id": job_id, "status": "QUEUED", "command": body.command, "args": vf_args}


@app.get("/api/admin/ops/jobs")
@limiter.limit("60/minute")
async def ops_jobs_list(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None),
):
    """List recent ops jobs (admin only)."""
    user = _require_user(request)
    if not _effective_admin(user, request):
        raise HTTPException(status_code=403, detail="Admin only.")

    def _run():
        conn = _thread_conn()
        try:
            where = "WHERE 1=1"
            params: list = []
            if status:
                where += " AND status = ?"
                params.append(status.upper())
            rows = conn.execute(
                f"""SELECT id, command, args_json, status, triggered_by,
                           triggered_at, started_at, finished_at, exit_code, county,
                           SUBSTR(COALESCE(output,''), -2000) as output_tail
                    FROM ops_jobs {where}
                    ORDER BY triggered_at DESC LIMIT ?""",
                params + [limit],
            ).fetchall()
        finally:
            conn.close()
        return {"jobs": [dict(r) for r in rows]}

    return await _run_in_db(_run)


@app.get("/api/admin/ops/jobs/{job_id}")
@limiter.limit("120/minute")
async def ops_job_detail(job_id: str, request: Request):
    """Get full output of an ops job (admin only). Poll at 2s for live tail."""
    user = _require_user(request)
    if not _effective_admin(user, request):
        raise HTTPException(status_code=403, detail="Admin only.")

    def _run():
        conn = _thread_conn()
        try:
            row = conn.execute(
                "SELECT * FROM ops_jobs WHERE id = ?", [job_id]
            ).fetchone()
        finally:
            conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Job not found.")
        d = dict(row)
        # Calculate duration
        if d.get("started_at") and d.get("finished_at"):
            d["duration_s"] = d["finished_at"] - d["started_at"]
        elif d.get("started_at"):
            d["duration_s"] = int(_time.time()) - d["started_at"]
        else:
            d["duration_s"] = None
        return d

    return await _run_in_db(_run)


@app.post("/api/admin/ops/promote-presale")
@limiter.limit("5/minute")
async def ops_promote_presale(request: Request, county: Optional[str] = Query(None)):
    """Scan existing PENDING leads with future scheduled_sale_date or sale_date
    and promote them to processing_status='PRE_SALE'. Safe to run anytime.
    """
    user = _require_user(request)
    if not _effective_admin(user, request):
        raise HTTPException(status_code=403, detail="Admin only.")

    def _run():
        conn = _thread_conn()
        try:
            where = ""
            params: list = []
            if county:
                where = " AND county = ?"
                params.append(county)

            # Promote leads with future scheduled_sale_date
            r1 = conn.execute(
                f"""UPDATE leads
                    SET processing_status = 'PRE_SALE',
                        ned_source = COALESCE(ned_source, 'govsoft_active'),
                        updated_at = datetime('now')
                    WHERE processing_status != 'PRE_SALE'
                      AND data_grade NOT IN ('GOLD', 'SILVER')
                      AND (
                          (scheduled_sale_date IS NOT NULL AND scheduled_sale_date > date('now'))
                          OR
                          (sale_date IS NOT NULL AND sale_date > date('now'))
                      ){where}""",
                params,
            )
            promoted_count = r1.rowcount
            conn.commit()

            # Also count how many PRE_SALE leads now exist
            total = conn.execute(
                f"SELECT COUNT(*) FROM leads WHERE processing_status='PRE_SALE'{where}",
                params,
            ).fetchone()[0]
        finally:
            conn.close()

        return {
            "promoted": promoted_count,
            "total_pre_sale": total,
            "county_filter": county,
            "message": f"Promoted {promoted_count} leads to PRE_SALE. Total PRE_SALE: {total}",
        }

    return await _run_in_db(_run)


@app.post("/api/admin/backfill-sale-dates")
@limiter.limit("10/minute")
async def admin_backfill_sale_dates(request: Request):
    """Backfill sale_date from scheduled_sale_date for BRONZE leads where sale_date is NULL."""
    user = _require_user(request)
    if not _effective_admin(user, request):
        raise HTTPException(status_code=403, detail="Admin only.")

    def _run():
        conn = _thread_conn()
        try:
            candidates = conn.execute(
                "SELECT COUNT(*) FROM leads WHERE data_grade = 'BRONZE' "
                "AND sale_date IS NULL AND scheduled_sale_date IS NOT NULL AND scheduled_sale_date != ''"
            ).fetchone()[0]
            result = conn.execute(
                "UPDATE leads SET sale_date = scheduled_sale_date, updated_at = datetime('now') "
                "WHERE data_grade = 'BRONZE' AND sale_date IS NULL "
                "AND scheduled_sale_date IS NOT NULL AND scheduled_sale_date != ''"
            )
            updated = result.rowcount
            conn.commit()
            _audit_log(conn, user["user_id"], "backfill_sale_dates", {"candidates": candidates, "updated": updated})
            conn.commit()
            log.info("backfill_sale_dates: updated %d leads", updated)
            return {"ok": True, "candidates_found": candidates, "updated": updated,
                    "message": f"Backfilled sale_date for {updated} BRONZE leads from scheduled_sale_date"}
        finally:
            conn.close()

    return await _run_in_db(_run)


@app.post("/api/admin/state-machine-backfill")
@limiter.limit("5/minute")
async def admin_state_machine_backfill(request: Request):
    """Recompute and persist verification_state for all non-REJECT leads. Idempotent."""
    user = _require_user(request)
    if not _effective_admin(user, request):
        raise HTTPException(status_code=403, detail="Admin only.")

    def _run():
        conn = _thread_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM leads WHERE data_grade != 'REJECT' LIMIT 25000"
            ).fetchall()
            state_counts: dict[str, int] = {}
            updated = 0
            for row in rows:
                d = dict(row)
                computed = _compute_verification_state(d)
                stored = d.get("verification_state") or "RAW"
                if computed != stored:
                    conn.execute(
                        "UPDATE leads SET verification_state = ?, updated_at = datetime('now') WHERE id = ?",
                        [computed, d["id"]],
                    )
                    updated += 1
                state_counts[computed] = state_counts.get(computed, 0) + 1
            conn.commit()
            _audit_log(conn, user["user_id"], "state_machine_backfill",
                       {"total_processed": len(rows), "updated": updated, "states": state_counts})
            conn.commit()
            log.info("state_machine_backfill: processed=%d updated=%d", len(rows), updated)
            return {"ok": True, "total_processed": len(rows), "updated": updated,
                    "state_distribution": state_counts,
                    "message": f"Processed {len(rows)} leads, updated {updated} verification states"}
        finally:
            conn.close()

    return await _run_in_db(_run)


@app.get("/api/admin/ops/pipeline-summary")
@limiter.limit("30/minute")
async def ops_pipeline_summary(request: Request):
    """Real-time pipeline health snapshot for the Ops Center dashboard."""
    user = _require_user(request)
    if not _effective_admin(user, request):
        raise HTTPException(status_code=403, detail="Admin only.")

    def _run():
        conn = _thread_conn()
        try:
            # Grade distribution
            grades = {r["data_grade"]: r["cnt"] for r in conn.execute(
                "SELECT data_grade, COUNT(*) as cnt FROM leads GROUP BY data_grade"
            ).fetchall()}

            # Processing status distribution
            statuses = {r["processing_status"]: r["cnt"] for r in conn.execute(
                "SELECT processing_status, COUNT(*) as cnt FROM leads GROUP BY processing_status"
            ).fetchall()}

            # PRE_SALE leads
            pre_sale = conn.execute(
                "SELECT COUNT(*) FROM leads WHERE processing_status='PRE_SALE'"
            ).fetchone()[0]

            # Future-dated (candidates for PRE_SALE promotion)
            future_dated = conn.execute(
                """SELECT COUNT(*) FROM leads
                   WHERE processing_status != 'PRE_SALE'
                     AND data_grade NOT IN ('GOLD','SILVER')
                     AND (
                         (scheduled_sale_date IS NOT NULL AND scheduled_sale_date > date('now'))
                         OR (sale_date IS NOT NULL AND sale_date > date('now'))
                     )"""
            ).fetchone()[0]

            # Recent job history
            jobs = conn.execute(
                """SELECT command, status, triggered_at, finished_at, exit_code
                   FROM ops_jobs ORDER BY triggered_at DESC LIMIT 10"""
            ).fetchall()

            # Ingestion runs last 24h
            cutoff = int(_time.time()) - 86400
            runs_24h = conn.execute(
                "SELECT mode, status, COUNT(*) as cnt FROM ingestion_runs WHERE start_ts > ? GROUP BY mode, status",
                [cutoff],
            ).fetchall()

            # BRONZE with SALE_INFO snapshots (Gate 4 ready)
            # html_snapshots.asset_id = 'FORECLOSURE:CO:{COUNTY_UPPER}:{CASE_NUMBER}'
            # Join via case_number substring match (county_upper in asset_id)
            gate4_ready = conn.execute(
                """SELECT COUNT(DISTINCT l.id)
                   FROM leads l
                   INNER JOIN html_snapshots h
                     ON h.asset_id LIKE '%' || l.case_number || '%'
                   WHERE l.data_grade = 'BRONZE'
                     AND l.case_number IS NOT NULL
                     AND h.snapshot_type = 'SALE_INFO'"""
            ).fetchone()[0]

            # Snapshot counts
            snapshot_counts = conn.execute(
                "SELECT snapshot_type, COUNT(*) as cnt FROM html_snapshots GROUP BY snapshot_type"
            ).fetchall()

        finally:
            conn.close()

        return {
            "grade_distribution": grades,
            "status_distribution": statuses,
            "pre_sale_leads": pre_sale,
            "pre_sale_promotion_candidates": future_dated,
            "gate4_ready": gate4_ready,
            "snapshot_counts": {r["snapshot_type"]: r["cnt"] for r in snapshot_counts},
            "recent_jobs": [dict(r) for r in jobs],
            "runs_24h": [dict(r) for r in runs_24h],
        }

    return await _run_in_db(_run)


# ═══════════════════════════════════════════════════════════════════════════════
# ALTERNATIVE SURPLUS STREAMS
# GET /api/unclaimed-property   — query unclaimed property leads
# GET /api/tax-deed-surplus     — query tax deed surplus leads
# ═══════════════════════════════════════════════════════════════════════════════


@app.get("/api/unclaimed-property")
@limiter.limit("60/minute")
async def get_unclaimed_property(
    request: Request,
    county: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """Query unclaimed property leads (C.R.S. § 38-13-101).

    No auth required — surplus amounts are public record from CO Treasury.
    Returns leads with surplus_stream='UNCLAIMED_PROPERTY'.
    """
    limit = min(limit, 200)

    def _run():
        conn = _thread_conn()
        try:
            params: list = ["UNCLAIMED_PROPERTY"]
            where_extra = ""
            if county:
                where_extra = " AND lower(county) = lower(?)"
                params.append(county)
            params.extend([limit, offset])

            rows = conn.execute(
                f"""SELECT id, county, case_number, data_grade, processing_status,
                           overbid_amount, estimated_surplus, owner_name,
                           ned_source, updated_at, ingestion_source
                    FROM leads
                    WHERE surplus_stream = ?{where_extra}
                    ORDER BY estimated_surplus DESC
                    LIMIT ? OFFSET ?""",
                params,
            ).fetchall()

            total = conn.execute(
                f"SELECT COUNT(*) FROM leads WHERE surplus_stream = ?{where_extra}",
                ["UNCLAIMED_PROPERTY"] + ([county] if county else []),
            ).fetchone()[0]

            by_county = {
                r["county"]: r["cnt"]
                for r in conn.execute(
                    "SELECT county, COUNT(*) as cnt FROM leads WHERE surplus_stream='UNCLAIMED_PROPERTY'"
                    " GROUP BY county ORDER BY cnt DESC"
                ).fetchall()
            }

            total_value = conn.execute(
                "SELECT COALESCE(SUM(estimated_surplus),0) FROM leads WHERE surplus_stream='UNCLAIMED_PROPERTY'"
            ).fetchone()[0]

        finally:
            conn.close()

        return {
            "statute": "C.R.S. § 38-13-101",
            "program": "Colorado Great Colorado Payback",
            "total": total,
            "total_value": total_value,
            "by_county": by_county,
            "leads": [
                {
                    "id": r["id"],
                    "county": r["county"],
                    "case_number": r["case_number"],
                    "data_grade": r["data_grade"],
                    "amount": r["estimated_surplus"],
                    "owner": r["owner_name"],
                    "description": r["ned_source"],
                    "updated_at": r["updated_at"],
                }
                for r in rows
            ],
        }

    return await _run_in_db(_run)


@app.get("/api/tax-deed-surplus")
@limiter.limit("60/minute")
async def get_tax_deed_surplus(
    request: Request,
    county: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """Query tax deed surplus leads (C.R.S. § 39-12-111).

    No auth required — surplus amounts are public record from county treasurers.
    Returns leads with surplus_stream='TAX_DEED_SURPLUS'.
    """
    limit = min(limit, 200)

    def _run():
        conn = _thread_conn()
        try:
            params: list = ["TAX_DEED_SURPLUS"]
            where_extra = ""
            if county:
                where_extra = " AND lower(county) = lower(?)"
                params.append(county)
            params.extend([limit, offset])

            rows = conn.execute(
                f"""SELECT id, county, case_number, data_grade, processing_status,
                           overbid_amount, estimated_surplus, owner_name,
                           sale_date, ned_source, updated_at
                    FROM leads
                    WHERE surplus_stream = ?{where_extra}
                    ORDER BY estimated_surplus DESC
                    LIMIT ? OFFSET ?""",
                params,
            ).fetchall()

            total = conn.execute(
                f"SELECT COUNT(*) FROM leads WHERE surplus_stream = ?{where_extra}",
                ["TAX_DEED_SURPLUS"] + ([county] if county else []),
            ).fetchone()[0]

            total_value = conn.execute(
                "SELECT COALESCE(SUM(estimated_surplus),0) FROM leads WHERE surplus_stream='TAX_DEED_SURPLUS'"
            ).fetchone()[0]

            by_county = {
                r["county"]: r["cnt"]
                for r in conn.execute(
                    "SELECT county, COUNT(*) as cnt FROM leads WHERE surplus_stream='TAX_DEED_SURPLUS'"
                    " GROUP BY county ORDER BY cnt DESC"
                ).fetchall()
            }

        finally:
            conn.close()

        return {
            "statute": "C.R.S. § 39-12-111",
            "total": total,
            "total_value": total_value,
            "by_county": by_county,
            "leads": [
                {
                    "id": r["id"],
                    "county": r["county"],
                    "case_number": r["case_number"],
                    "data_grade": r["data_grade"],
                    "amount": r["estimated_surplus"],
                    "owner": r["owner_name"],
                    "sale_date": r["sale_date"],
                    "description": r["ned_source"],
                    "updated_at": r["updated_at"],
                }
                for r in rows
            ],
        }

    return await _run_in_db(_run)


# ── C2: Filing Outcome Intelligence ─────────────────────────────────

@app.get("/api/intelligence/county-outcomes")
async def county_outcomes(county: str = Query(None), request: Request = None):
    """County-level filing outcome intelligence from case_outcomes table."""
    conn = _get_conn()
    try:
        # Check if case_outcomes table exists
        has_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='case_outcomes'"
        ).fetchone()
        if not has_table:
            return {"county": county, "total_filed": 0, "win_rate": 0.0, "avg_recovery_days": None,
                    "avg_amount_recovered": None, "message": "Outcome data collection not yet started"}
        where = "WHERE county = ?" if county else ""
        params = [county] if county else []
        row = conn.execute(
            f"SELECT COUNT(*) as total, "
            f"SUM(CASE WHEN result='won' OR result='settled' THEN 1 ELSE 0 END) as wins, "
            f"AVG(time_to_recovery_days) as avg_days, "
            f"AVG(amount_recovered_cents) as avg_amount "
            f"FROM case_outcomes {where}",
            params
        ).fetchone()
        if not row or not row["total"]:
            return {"county": county, "total_filed": 0, "win_rate": 0.0, "avg_recovery_days": None,
                    "avg_amount_recovered": None}
        total = row["total"] or 0
        wins = row["wins"] or 0
        return {
            "county": county,
            "total_filed": total,
            "win_rate": round(wins / total, 2) if total > 0 else 0.0,
            "avg_recovery_days": round(row["avg_days"]) if row["avg_days"] else None,
            "avg_amount_recovered": round(row["avg_amount"] / 100) if row["avg_amount"] else None,
            "top_outcome_factors": ["lien_density", "surplus_size", "claim_window"],
        }
    finally:
        conn.close()


# ── C3: Owner Contact Intelligence ──────────────────────────────────

@app.get("/api/lead/{lead_id}/owner-contact")
async def get_owner_contact(lead_id: str, request: Request):
    """Owner contact intel (assessor + mailing address).

    Pricing:
      - Enterprise (sovereign): 10 free per calendar month — tracked via audit_log
      - Investigator/Partner: requires 1 skip_trace token (purchased for $29 via Stripe)
      - Admin: always free
    Skip trace tokens live in unlock_ledger_entries with source='skip_trace'.
    """
    user = _require_user(request)
    tier = user.get("tier", "associate")
    user_id = user["user_id"]
    is_admin = _effective_admin(user)
    now_ts = _epoch_now()
    _skip_credit_id: str | None = None

    if not is_admin:
        if tier == "sovereign":
            # Enterprise: 10 free skip traces per calendar month
            _cnt_conn = _get_conn()
            try:
                st_count = _cnt_conn.execute(
                    "SELECT COUNT(*) FROM audit_log WHERE user_id=? AND action='skip_trace_run' "
                    "AND created_at >= date('now','start of month')",
                    [user_id],
                ).fetchone()[0]
            finally:
                _cnt_conn.close()
            if st_count >= 10:
                raise HTTPException(
                    status_code=429,
                    detail="Skip trace monthly limit reached (10/month on Enterprise). Resets at the start of next month.",
                )
        else:
            # Investigator / Partner: need a skip_trace token in the ledger
            _tok_conn = _get_conn()
            try:
                credit_row = _tok_conn.execute(
                    "SELECT id FROM unlock_ledger_entries "
                    "WHERE user_id=? AND source='skip_trace' AND qty_remaining>0 "
                    "AND (expires_ts IS NULL OR expires_ts > ?) "
                    "ORDER BY purchased_ts ASC LIMIT 1",
                    [user_id, now_ts],
                ).fetchone()
            finally:
                _tok_conn.close()
            if not credit_row:
                raise HTTPException(
                    status_code=402,
                    detail="Skip trace requires a $29 purchase. Click 'SKIP TRACE — $29' to buy one skip trace credit.",
                )
            _skip_credit_id = credit_row["id"]

    # Fetch contact data
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", [lead_id]).fetchone()
        if not row:
            raise HTTPException(404, detail="Lead not found.")
        row = dict(row)
        contact_json = row.get("owner_contact_json")
        if contact_json:
            try:
                result = json.loads(contact_json)
            except Exception:
                result = None
        else:
            result = None
        if result is None:
            result = {
                "mailing_address": row.get("property_address"),
                "address_source": "property_record",
                "address_confidence": "MEDIUM",
                "forwarding_address": None,
                "last_verified": row.get("updated_at", "")[:10] if row.get("updated_at") else None,
                "note": None,
            }
    finally:
        conn.close()

    # Deduct / log usage AFTER successful data fetch
    if not is_admin:
        _log_conn = _get_conn()
        try:
            _log_conn.execute("BEGIN IMMEDIATE")
            if tier == "sovereign":
                _audit_log(_log_conn, user_id, "skip_trace_run", {"lead_id": lead_id, "tier": "sovereign"})
            else:
                # Consume the skip_trace token
                _log_conn.execute(
                    "UPDATE unlock_ledger_entries SET qty_remaining = qty_remaining - 1 WHERE id = ? AND qty_remaining > 0",
                    [_skip_credit_id],
                )
                _audit_log(_log_conn, user_id, "skip_trace_run", {"lead_id": lead_id, "tier": tier, "entry_id": _skip_credit_id})
            _log_conn.execute("COMMIT")
        except Exception as _le:
            log.error("skip_trace log/deduct failed for user=%s: %s", user_id, _le)
            try:
                _log_conn.execute("ROLLBACK")
            except Exception:
                pass
        finally:
            _log_conn.close()

    return result


# ── C6: Evidence Preview ─────────────────────────────────────────────

@app.get("/api/lead/{lead_id}/evidence-preview")
async def evidence_preview(lead_id: str, request: Request):
    """Return document metadata (no file content) — no unlock required, just registered user."""
    user = _require_user(request)
    conn = _get_conn()
    try:
        docs = conn.execute(
            """SELECT id, doc_family, filename, recording_number, doc_type,
                      bytes AS file_size_bytes, retrieved_ts AS created_at
               FROM evidence_documents WHERE asset_id=? ORDER BY retrieved_ts DESC""",
            [lead_id],
        ).fetchall()
        return {"docs": [dict(d) for d in docs], "count": len(docs)}
    finally:
        conn.close()


# ── C4: Market Velocity Intelligence ────────────────────────────────

@app.get("/api/intelligence/market-velocity")
async def market_velocity(request: Request):
    """Real-time pipeline velocity metrics."""
    conn = _get_conn()
    try:
        # Average days GOLD leads sit before first unlock
        velocity_rows = conn.execute(
            "SELECT l.county, "
            "COUNT(DISTINCT l.id) as gold_count, "
            "AVG(JULIANDAY('now') - JULIANDAY(l.updated_at)) as avg_days_gold "
            "FROM leads l "
            "WHERE l.data_grade = 'GOLD' "
            "GROUP BY l.county "
            "ORDER BY gold_count DESC "
            "LIMIT 20"
        ).fetchall()
        county_metrics = []
        for r in velocity_rows:
            county_metrics.append({
                "county": r["county"],
                "gold_count": r["gold_count"],
                "avg_days_as_gold": round(r["avg_days_gold"] or 0, 1),
            })
        # Most urgent county (highest urgency = most gold leads + shortest claim window)
        urgency_row = conn.execute(
            "SELECT county, COUNT(*) as cnt FROM leads "
            "WHERE data_grade = 'GOLD' AND claim_deadline IS NOT NULL "
            "AND claim_deadline > date('now') AND claim_deadline < date('now', '+90 days') "
            "GROUP BY county ORDER BY cnt DESC LIMIT 1"
        ).fetchone()
        return {
            "county_velocity": county_metrics,
            "most_urgent_county": urgency_row["county"] if urgency_row else None,
            "most_urgent_count": urgency_row["cnt"] if urgency_row else 0,
        }
    finally:
        conn.close()
