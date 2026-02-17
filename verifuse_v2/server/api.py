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

# ── API Key for machine-to-machine auth (admin/scraper endpoints) ────
VERIFUSE_API_KEY = os.environ.get("VERIFUSE_API_KEY", "")

# ── Stripe guard ─────────────────────────────────────────────────────
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")

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

# ── Database connection (strict VERIFUSE_DB_PATH) ───────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(VERIFUSE_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


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
    motion_pdf: Optional[str] = None


class PreviewLead(BaseModel):
    """Public preview — ZERO PII, ZERO internal IDs. Explicit SELECT (no SELECT *)."""
    preview_key: str  # HMAC hash for React key ONLY — not usable for lookups
    county: Optional[str] = None
    sale_date: Optional[str] = None  # YYYY-MM only (anti-triangulation)
    data_grade: Optional[str] = None
    confidence_score: Optional[float] = None
    estimated_surplus: Optional[float] = None  # COALESCED + ROUND(x,2) — exact to the penny
    restriction_status: Optional[str] = None
    days_until_actionable: Optional[int] = None


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

    return "ACTIONABLE"


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
    surplus = _safe_float(row.get("estimated_surplus")) or _safe_float(row.get("surplus_amount")) or 0.0
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
    surplus = _safe_float(row.get("surplus_amount")) or _safe_float(row.get("estimated_surplus")) or 0.0
    bid = _safe_float(row.get("winning_bid")) or 0.0
    debt = _safe_float(row.get("total_debt")) or 0.0
    conf = _safe_float(row.get("confidence_score")) or 0.0
    status = _compute_status(row)
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

    verified = bid > 0 and debt > 0 and conf >= 0.7

    pk = _compute_preview_key(row) if is_preview_eligible(row) else None

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
        confidence_score=round(conf, 2) if conf else None,
        data_age_days=data_age_days,
        preview_key=pk,
    ).model_dump()


def _row_to_full(row: dict) -> dict:
    """Convert a leads row to FullAsset dict. NULL-safe."""
    safe = _row_to_safe(row)
    safe.update({
        "owner_name": row.get("owner_name"),
        "property_address": row.get("property_address"),
        "winning_bid": _safe_float(row.get("winning_bid")),
        "total_debt": _safe_float(row.get("total_debt")),
        "total_indebtedness": _safe_float(row.get("total_debt")),
        "surplus_amount": _safe_float(row.get("surplus_amount")),
        "overbid_amount": _safe_float(row.get("overbid_amount")),
        "recorder_link": row.get("recorder_link"),
        "motion_pdf": row.get("motion_pdf"),
    })
    return safe


def _row_to_preview(row: dict) -> dict:
    """Convert a leads row to PreviewLead dict. ZERO PII, ZERO internal IDs."""
    county = row.get("county")
    sale_date_raw = row.get("sale_date")
    data_grade = row.get("data_grade")
    confidence = _safe_float(row.get("confidence_score"))
    surplus = _safe_float(row.get("estimated_surplus")) or 0.0

    # Truncate sale_date to YYYY-MM (anti-triangulation)
    sale_date_display = (sale_date_raw or "")[:7] if sale_date_raw else None

    # HMAC preview_key — stable, id-only salt (24 hex chars)
    preview_key = _compute_preview_key(row)
    # Pop id so it's not in output
    row.pop("id", None)

    # Compute status + days
    status = _compute_status(row)
    days_until_actionable = None
    if sale_date_raw:
        restriction_end = _compute_restriction_end(sale_date_raw)
        if restriction_end:
            today = datetime.now(timezone.utc).date()
            days_until_actionable = max(0, (restriction_end - today).days) if restriction_end > today else 0

    return PreviewLead(
        preview_key=preview_key,
        county=county,
        sale_date=sale_date_display,
        data_grade=data_grade,
        confidence_score=round(confidence, 2) if confidence else None,
        estimated_surplus=round(surplus, 2),
        restriction_status=status,
        days_until_actionable=days_until_actionable,
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
    """Check email verification. Raises 403 if not verified and not admin."""
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
        f"ROUND(COALESCE(estimated_surplus, surplus_amount, 0), 2) as estimated_surplus, "
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
                 "ROUND(COALESCE(estimated_surplus, surplus_amount, 0), 2) as estimated_surplus, "
                 f"data_grade, {claim_deadline_expr} "
                 "FROM leads WHERE COALESCE(estimated_surplus, surplus_amount, 0) > 100 "
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

    log.info(
        "Titanium API v4.1 BOOT — DB: %s | inode: %s | sha256: %s | leads: %s | columns: %d",
        VERIFUSE_DB_PATH, inode, sha, rows, len(_LEADS_COLUMNS),
    )


# ── Health ──────────────────────────────────────────────────────────

@app.get("/health")
async def health():
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
                   COALESCE(SUM(COALESCE(estimated_surplus, surplus_amount, 0)), 0) as verified_surplus
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
            "SELECT COALESCE(SUM(COALESCE(estimated_surplus, surplus_amount, 0)), 0) FROM leads WHERE COALESCE(estimated_surplus, surplus_amount, 0) > 0"
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
    conn = _get_conn()
    try:
        where = " WHERE COALESCE(estimated_surplus, surplus_amount, 0) > 100"
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
        order = " ORDER BY COALESCE(estimated_surplus, surplus_amount, 0) DESC, sale_date DESC, county ASC, id ASC"
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
    # Check if user is admin (for reject visibility)
    user = _get_user_from_request(request)
    is_admin_user = user and _is_admin(user)

    conn = _get_conn()
    try:
        where = " WHERE 1=1"
        params: list = []

        if not include_zombies:
            where += " AND COALESCE(estimated_surplus, surplus_amount, 0) > 100"
        if not include_reject or not is_admin_user:
            where += " AND data_grade != 'REJECT'"
        if county:
            where += " AND county = ?"
            params.append(county)
        if min_surplus > 0:
            where += " AND COALESCE(estimated_surplus, surplus_amount, 0) >= ?"
            params.append(min_surplus)
        if grade:
            where += " AND data_grade = ?"
            params.append(grade)

        # Count for pagination
        total = conn.execute(f"SELECT COUNT(*) FROM leads{where}", params).fetchone()[0]

        query = f"SELECT *, {_claim_deadline_expr} FROM leads{where}"
        query += " ORDER BY COALESCE(estimated_surplus, surplus_amount, 0) DESC, sale_date DESC, county ASC, id ASC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()

    # Determine which leads the current user has unlocked (paginated set only)
    lead_ids = [dict(row)["id"] for row in rows]
    unlocked_ids: set[str] = set()
    if user and lead_ids:
        placeholders = ",".join(["?"] * len(lead_ids))
        conn2 = _get_conn()
        try:
            u_rows = conn2.execute(
                f"SELECT lead_id FROM lead_unlocks WHERE user_id = ? AND lead_id IN ({placeholders})",
                [user["user_id"]] + lead_ids
            ).fetchall()
            unlocked_ids = {r["lead_id"] for r in u_rows}
        finally:
            conn2.close()

    leads = []
    for row in rows:
        try:
            r = dict(row)
            safe = _row_to_safe(r)
            safe["unlocked_by_me"] = r["id"] in unlocked_ids
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


# ── POST /api/leads/{id}/unlock — Double Gate + Atomic Credits ──────

@app.post("/api/leads/{lead_id}/unlock")
@limiter.limit("10/minute")
async def unlock_lead(lead_id: str, request: Request):
    """Unlock a lead with Double Gate enforcement.

    RESTRICTED: requires is_verified_attorney + (OPERATOR or SOVEREIGN tier)
    ACTIONABLE: any paid user with credits >= 1
    EXPIRED: cannot unlock
    """
    user = _require_user(request)
    _check_email_verified(user, request)
    now = datetime.now(timezone.utc).isoformat()

    # Admin bypass
    if _effective_admin(user, request):
        conn = _get_conn()
        try:
            row = conn.execute("SELECT * FROM leads WHERE id = ?", [lead_id]).fetchone()
        finally:
            conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Lead not found.")
        result = _row_to_full(dict(row))
        result["ok"] = True
        result["credits_remaining"] = -1
        return result

    # Fetch lead
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", [lead_id]).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Lead not found.")

    lead = dict(row)
    status = _compute_status(lead)

    # ── Gate 1: EXPIRED check ────────────────────────────────────
    if status == "EXPIRED":
        raise HTTPException(
            status_code=410,
            detail="This lead has expired. Claim deadline has passed.",
        )

    # ── Gate 2: RESTRICTED — Double Gate ─────────────────────────
    if status == "RESTRICTED":
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

    # ── Gate 3: Atomic credit deduction (BEGIN IMMEDIATE) ────────
    conn = _get_conn()
    credits_after = 0
    try:
        conn.execute("BEGIN IMMEDIATE")

        # Check if already unlocked
        existing = conn.execute(
            "SELECT 1 FROM lead_unlocks WHERE user_id = ? AND lead_id = ?",
            [user["user_id"], lead_id],
        ).fetchone()

        if existing:
            # Already unlocked — return full asset with current credits
            credits_row = conn.execute(
                "SELECT credits_remaining FROM users WHERE user_id = ?",
                [user["user_id"]],
            ).fetchone()
            credits_after = credits_row[0] if credits_row else 0
            conn.execute("COMMIT")
            result = _row_to_full(lead)
            result["ok"] = True
            result["credits_remaining"] = credits_after
            return result

        # Check credits
        credits = conn.execute(
            "SELECT credits_remaining FROM users WHERE user_id = ?",
            [user["user_id"]],
        ).fetchone()

        if not credits or credits[0] <= 0:
            conn.execute("ROLLBACK")
            raise HTTPException(
                status_code=402,
                detail="Insufficient credits. Upgrade your plan.",
            )

        # Deduct 1 credit
        conn.execute(
            "UPDATE users SET credits_remaining = credits_remaining - 1 WHERE user_id = ?",
            [user["user_id"]],
        )

        # Record unlock
        ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if not ip and request.client:
            ip = request.client.host

        conn.execute("""
            INSERT INTO lead_unlocks (user_id, lead_id, unlocked_at, ip_address, plan_tier)
            VALUES (?, ?, ?, ?, ?)
        """, [user["user_id"], lead_id, now, ip, user.get("tier", "recon")])

        # Audit trail
        conn.execute("""
            INSERT INTO pipeline_events
            (asset_id, event_type, old_value, new_value, actor, reason, created_at)
            VALUES (?, 'LEAD_UNLOCK', ?, ?, ?, ?, ?)
        """, [
            lead_id,
            f"credits={credits[0]}",
            f"credits={credits[0] - 1}",
            user["user_id"],
            f"tier={user.get('tier')} status={status}",
            now,
        ])

        conn.execute("COMMIT")
        credits_after = credits[0] - 1

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
    result["ok"] = True
    result["credits_remaining"] = credits_after
    return result


# ── POST /api/billing/upgrade — Tier upgrade + credit refill ────────

@app.post("/api/billing/upgrade")
async def billing_upgrade(request: Request):
    """Update tier and refill credits."""
    user = _require_user(request)
    body = await request.json()
    new_tier = body.get("tier", "").lower()

    valid_tiers = {
        "recon": 5,
        "operator": 25,
        "sovereign": 100,
    }

    if new_tier not in valid_tiers:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid tier. Choose from: {list(valid_tiers.keys())}",
        )

    credits = valid_tiers[new_tier]
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
    conn = _get_conn()
    try:
        total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        with_surplus = conn.execute(
            "SELECT COUNT(*) FROM leads WHERE COALESCE(estimated_surplus, surplus_amount, 0) > 1000"
        ).fetchone()[0]
        gold_count = conn.execute(
            "SELECT COUNT(*) FROM leads WHERE data_grade = 'GOLD'"
        ).fetchone()[0]
        total_surplus = conn.execute(
            "SELECT COALESCE(SUM(COALESCE(estimated_surplus, surplus_amount, 0)), 0) FROM leads WHERE COALESCE(estimated_surplus, surplus_amount, 0) > 0"
        ).fetchone()[0]
        counties = conn.execute("""
            SELECT county, COUNT(*) as cnt,
                   COALESCE(SUM(COALESCE(estimated_surplus, surplus_amount, 0)), 0) as total
            FROM leads
            WHERE COALESCE(estimated_surplus, surplus_amount, 0) > 0
            GROUP BY county ORDER BY total DESC
        """).fetchall()

        # Verified pipeline: GOLD+SILVER+BRONZE, surplus > 100, not expired
        vp_row = conn.execute(f"""
            SELECT COUNT(*) as cnt,
                   COALESCE(SUM(COALESCE(estimated_surplus, surplus_amount, 0)), 0) as total
            FROM leads
            WHERE data_grade IN ('GOLD', 'SILVER', 'BRONZE')
              AND COALESCE(estimated_surplus, surplus_amount, 0) > 100
              {_EXPIRED_FILTER}
        """).fetchone()

        # Total raw volume: ALL leads
        raw_row = conn.execute("""
            SELECT COUNT(*) as cnt,
                   COALESCE(SUM(COALESCE(estimated_surplus, surplus_amount, 0)), 0) as total
            FROM leads
        """).fetchone()
    finally:
        conn.close()

    return {
        "total_leads": total,
        "total_assets": total,
        "attorney_ready": with_surplus,
        "with_surplus": with_surplus,
        "gold_grade": gold_count,
        "total_claimable_surplus": round(total_surplus, 2),
        "counties": [dict(r) for r in counties],
        "verified_pipeline": {
            "count": vp_row["cnt"],
            "total_surplus": round(vp_row["total"], 2),
        },
        "total_raw_volume": {
            "count": raw_row["cnt"],
            "total_surplus": round(raw_row["total"], 2),
        },
    }


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
    user, token = register_user(
        email=email, password=password,
        full_name=body.get("full_name", ""),
        firm_name=body.get("firm_name", ""),
        bar_number=body.get("bar_number", ""),
        tier=body.get("tier", "recon"),
    )
    return {"token": token, "user": {
        "user_id": user["user_id"], "email": user["email"],
        "tier": user["tier"], "credits_remaining": user["credits_remaining"],
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
    return {"token": token, "user": {
        "user_id": user["user_id"], "email": user["email"],
        "tier": user["tier"], "credits_remaining": user["credits_remaining"],
    }}


@app.get("/api/auth/me")
async def api_me(request: Request):
    user = _require_user(request)
    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "full_name": user.get("full_name", ""),
        "firm_name": user.get("firm_name", ""),
        "tier": user["tier"],
        "credits_remaining": user["credits_remaining"],
        "attorney_status": user.get("attorney_status", "NONE"),
        "is_admin": bool(user.get("is_admin", 0)),
        "email_verified": bool(user.get("email_verified", 0)),
    }


# ── Email Verification ──────────────────────────────────────────────

@app.post("/api/auth/send-verification")
@limiter.limit("3/minute")
async def send_verification(request: Request):
    """Send a 6-digit verification code to the user's email."""
    user = _require_user(request)

    code = "".join(random.choices(string.digits, k=6))
    now = datetime.now(timezone.utc).isoformat()

    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE users SET email_verify_code = ?, email_verify_sent_at = ? WHERE user_id = ?",
            [code, now, user["user_id"]],
        )
        conn.commit()
    finally:
        conn.close()

    # Send via SMTP if configured, otherwise log (dev mode)
    smtp_host = os.environ.get("SMTP_HOST")
    if smtp_host:
        try:
            import smtplib
            from email.mime.text import MIMEText
            msg = MIMEText(f"Your VeriFuse verification code is: {code}\n\nThis code expires in 10 minutes.")
            msg["Subject"] = "VeriFuse Email Verification"
            msg["From"] = os.environ.get("SMTP_FROM", "noreply@verifuse.tech")
            msg["To"] = user["email"]
            with smtplib.SMTP(smtp_host, int(os.environ.get("SMTP_PORT", 587))) as s:
                s.starttls()
                s.login(os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASS", ""))
                s.send_message(msg)
            log.info("Verification email sent to %s", user["email"])
        except Exception as e:
            log.error("SMTP send failed: %s", e)
            raise HTTPException(status_code=500, detail="Failed to send verification email.")
    else:
        log.info("DEV MODE: Verification code for %s: %s", user["email"], code)

    return {"ok": True, "message": "Verification code sent."}


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
    conn = _get_conn()
    try:
        row = conn.execute(f"SELECT *, {_claim_deadline_expr} FROM leads WHERE id = ?", [lead_id]).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Lead not found.")

    result = _row_to_safe(dict(row))

    # Check if current user has unlocked this lead
    user = _get_user_from_request(request)
    is_unlocked = False
    if user:
        conn2 = _get_conn()
        try:
            u_row = conn2.execute(
                "SELECT 1 FROM lead_unlocks WHERE user_id = ? AND lead_id = ?",
                [user["user_id"], lead_id]
            ).fetchone()
            is_unlocked = bool(u_row)
        finally:
            conn2.close()
    result["unlocked_by_me"] = is_unlocked

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

    if tier not in ("recon", "operator", "sovereign"):
        raise HTTPException(
            status_code=400,
            detail="Invalid tier. Choose from: recon, operator, sovereign",
        )

    try:
        from verifuse_v2.server.billing import create_checkout_session
        checkout_url = create_checkout_session(
            user_id=user["user_id"],
            email=user["email"],
            tier=tier,
        )
        return {"checkout_url": checkout_url}
    except HTTPException:
        raise
    except Exception as e:
        log.error("Checkout failed: %s", e)
        raise HTTPException(status_code=503, detail="Billing service unavailable.")


# ── GET /api/counties — County breakdown ───────────────────────────

@app.get("/api/counties")
async def get_counties():
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT county, COUNT(*) as lead_count,
                   COALESCE(SUM(COALESCE(estimated_surplus, surplus_amount, 0)), 0) as total_surplus,
                   COALESCE(AVG(COALESCE(estimated_surplus, surplus_amount, 0)), 0) as avg_surplus,
                   COALESCE(MAX(COALESCE(estimated_surplus, surplus_amount, 0)), 0) as max_surplus
            FROM leads
            WHERE COALESCE(estimated_surplus, surplus_amount, 0) > 0
            GROUP BY county ORDER BY total_surplus DESC
        """).fetchall()
    finally:
        conn.close()

    return {
        "count": len(rows),
        "counties": [dict(r) for r in rows],
    }


# ── Admin endpoints ──────────────────────────────────────────────────

@app.get("/api/admin/leads")
async def admin_leads(
    request: Request,
    limit: int = Query(100, ge=1, le=1000),
):
    """Get all leads with raw data (admin only)."""
    _require_api_key(request)
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM leads ORDER BY COALESCE(estimated_surplus, surplus_amount, 0) DESC LIMIT ?", [limit]
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
async def admin_users(request: Request):
    """Get all users (admin only)."""
    _require_api_key(request)
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT user_id, email, full_name, firm_name, tier, credits_remaining, "
            "is_admin, is_active, email_verified, created_at, last_login_at FROM users"
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
            f"ROUND(COALESCE(estimated_surplus, surplus_amount, 0), 2) as estimated_surplus, "
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
            ORDER BY COALESCE(estimated_surplus, surplus_amount, 0) DESC
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
