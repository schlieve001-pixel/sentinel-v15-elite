"""
VERIFUSE V2 — Titanium API (leads-native)

All queries hit the `leads` table via VERIFUSE_DB_PATH.
SafeAsset fields are Optional[float] = None (Black Screen fix).

Gates:
  RESTRICTED → is_verified_attorney + (OPERATOR or SOVEREIGN)
  ACTIONABLE → any paid user with credits
  EXPIRED    → locked, cannot unlock

Atomic: credit deduction uses BEGIN IMMEDIATE.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, date, timedelta, timezone
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
    """Public projection. All floats are Optional = None (Black Screen fix)."""
    id: Optional[str] = None
    county: Optional[str] = None
    case_number: Optional[str] = None
    status: Optional[str] = None
    surplus_estimate: Optional[float] = None
    data_grade: Optional[str] = None
    confidence_score: Optional[float] = None
    sale_date: Optional[str] = None
    claim_deadline: Optional[str] = None
    days_remaining: Optional[int] = None
    city_hint: Optional[str] = None
    surplus_verified: Optional[bool] = None


class FullAsset(SafeAsset):
    """Unlocked projection with PII."""
    owner_name: Optional[str] = None
    property_address: Optional[str] = None
    winning_bid: Optional[float] = None
    total_debt: Optional[float] = None
    surplus_amount: Optional[float] = None
    overbid_amount: Optional[float] = None


# ── Helpers ──────────────────────────────────────────────────────────

RESTRICTION_DAYS = 180  # C.R.S. § 38-38-111


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
        try:
            sale_dt = date.fromisoformat(str(sale)[:10])
            if today < sale_dt + timedelta(days=RESTRICTION_DAYS):
                return "RESTRICTED"
            return "ACTIONABLE"
        except (ValueError, TypeError):
            pass

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


def _row_to_safe(row: dict) -> dict:
    """Convert a leads row to SafeAsset dict. NULL-safe."""
    surplus = _safe_float(row.get("surplus_amount")) or _safe_float(row.get("estimated_surplus")) or 0.0
    bid = _safe_float(row.get("winning_bid")) or 0.0
    debt = _safe_float(row.get("total_debt")) or 0.0
    conf = _safe_float(row.get("confidence_score")) or 0.0
    status = _compute_status(row)

    days_left = None
    deadline = row.get("claim_deadline")
    if deadline:
        try:
            days_left = (date.fromisoformat(deadline) - datetime.now(timezone.utc).date()).days
        except (ValueError, TypeError):
            pass

    verified = bid > 0 and debt > 0 and conf >= 0.7

    return SafeAsset(
        id=row.get("id"),
        county=row.get("county"),
        case_number=row.get("case_number"),
        status=status,
        surplus_estimate=_round_surplus(surplus),
        data_grade=row.get("data_grade"),
        confidence_score=round(conf, 2) if conf else None,
        sale_date=row.get("sale_date"),
        claim_deadline=deadline,
        days_remaining=days_left,
        city_hint=_extract_city(row.get("property_address"), row.get("county")),
        surplus_verified=verified,
    ).model_dump()


def _row_to_full(row: dict) -> dict:
    """Convert a leads row to FullAsset dict. NULL-safe."""
    safe = _row_to_safe(row)
    safe.update({
        "owner_name": row.get("owner_name"),
        "property_address": row.get("property_address"),
        "winning_bid": _safe_float(row.get("winning_bid")),
        "total_debt": _safe_float(row.get("total_debt")),
        "surplus_amount": _safe_float(row.get("surplus_amount")),
        "overbid_amount": _safe_float(row.get("overbid_amount")),
    })
    return safe


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


def _require_api_key(request: Request) -> None:
    """Check x-verifuse-api-key header for admin/scraper endpoints."""
    if not VERIFUSE_API_KEY:
        return  # No key configured (dev mode)
    key = request.headers.get("x-verifuse-api-key", "")
    if key != VERIFUSE_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing API key.")


# ── Rate Limiter ────────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])

# ── App ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="VeriFuse V2 — Titanium API",
    version="4.0.0",
    description="Colorado Surplus Intelligence Platform",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://verifuse.tech",
        "https://www.verifuse.tech",
        "http://localhost:3000",
        "http://34.69.230.82:4173",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "x-verifuse-api-key"],
)


# ── Startup ─────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    """Run schema patcher on startup (idempotent)."""
    try:
        from verifuse_v2.db.fix_leads_schema import patch_leads_schema
        patch_leads_schema()
    except Exception as e:
        log.warning("Schema patch on startup: %s", e)
    log.info("Titanium API v4 initialized (DB: %s)", VERIFUSE_DB_PATH)


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
                   COALESCE(SUM(surplus_amount), 0) as verified_surplus
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
            "SELECT COALESCE(SUM(surplus_amount), 0) FROM leads WHERE surplus_amount > 0"
        ).fetchone()[0]

    finally:
        conn.close()

    return {
        "status": "ok",
        "engine": "titanium_api_v4",
        "db": VERIFUSE_DB_PATH,
        "wal_pages": wal_pages,
        "total_leads": total,
        "scoreboard": scoreboard,
        "quarantined": quarantined,
        "verified_total": round(verified_total, 2),
    }


# ── GET /api/leads — Paginated, NULL-safe ───────────────────────────

@app.get("/api/leads")
@limiter.limit("100/minute")
async def get_leads(
    request: Request,
    county: Optional[str] = Query(None),
    min_surplus: float = Query(0.0, ge=0),
    grade: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Return paginated leads as SafeAsset. Handles NULLs gracefully."""
    conn = _get_conn()
    try:
        query = "SELECT * FROM leads WHERE 1=1"
        params: list = []

        if county:
            query += " AND county = ?"
            params.append(county)
        if min_surplus > 0:
            query += " AND COALESCE(surplus_amount, estimated_surplus, 0) >= ?"
            params.append(min_surplus)
        if grade:
            query += " AND data_grade = ?"
            params.append(grade)

        # Count for pagination
        count_q = query.replace("SELECT *", "SELECT COUNT(*)")
        total = conn.execute(count_q, params).fetchone()[0]

        query += " ORDER BY COALESCE(surplus_amount, estimated_surplus, 0) DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()

    leads = []
    for row in rows:
        try:
            safe = _row_to_safe(dict(row))
            # Filter out EXPIRED
            if safe.get("status") == "EXPIRED":
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
    now = datetime.now(timezone.utc).isoformat()

    # Admin bypass
    if _is_admin(user):
        conn = _get_conn()
        try:
            row = conn.execute("SELECT * FROM leads WHERE id = ?", [lead_id]).fetchone()
        finally:
            conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Lead not found.")
        return _row_to_full(dict(row))

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
    try:
        conn.execute("BEGIN IMMEDIATE")

        # Check if already unlocked
        existing = conn.execute(
            "SELECT 1 FROM lead_unlocks WHERE user_id = ? AND lead_id = ?",
            [user["user_id"], lead_id],
        ).fetchone()

        if existing:
            conn.execute("COMMIT")
            return _row_to_full(lead)

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

    return _row_to_full(lead)


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
            "SELECT COUNT(*) FROM leads WHERE COALESCE(surplus_amount, 0) > 1000"
        ).fetchone()[0]
        gold_count = conn.execute(
            "SELECT COUNT(*) FROM leads WHERE data_grade = 'GOLD'"
        ).fetchone()[0]
        total_surplus = conn.execute(
            "SELECT COALESCE(SUM(surplus_amount), 0) FROM leads WHERE surplus_amount > 0"
        ).fetchone()[0]
        counties = conn.execute("""
            SELECT county, COUNT(*) as cnt,
                   COALESCE(SUM(surplus_amount), 0) as total
            FROM leads
            WHERE COALESCE(surplus_amount, 0) > 0
            GROUP BY county ORDER BY total DESC
        """).fetchall()
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
    }


# ── Auth endpoints (delegate to auth module) ────────────────────────

@app.post("/api/auth/register")
@limiter.limit("5/minute")
async def api_register(request: Request):
    from verifuse_v2.server.auth import register_user
    body = await request.json()
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
    body = await request.json()
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
    }


# ── GET /api/counties — County breakdown ───────────────────────────

# ── GET /api/lead/{id} — Single lead detail (frontend compat) ─────

@app.get("/api/lead/{lead_id}")
@limiter.limit("100/minute")
async def get_lead_detail(lead_id: str, request: Request):
    """Return a single lead as SafeAsset. Frontend calls GET /api/lead/{id}."""
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", [lead_id]).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Lead not found.")

    d = dict(row)
    safe = _row_to_safe(d)
    # Map SafeAsset fields to frontend Lead interface
    surplus = _safe_float(d.get("surplus_amount")) or _safe_float(d.get("estimated_surplus")) or 0.0
    status = _compute_status(d)

    days_until = None
    restriction_end = None
    sale = d.get("sale_date")
    if sale:
        try:
            sale_dt = date.fromisoformat(str(sale)[:10])
            restriction_end = (sale_dt + timedelta(days=RESTRICTION_DAYS)).isoformat()
            days_until = (sale_dt + timedelta(days=RESTRICTION_DAYS) - datetime.now(timezone.utc).date()).days
        except (ValueError, TypeError):
            pass

    return {
        **safe,
        "asset_id": d.get("id"),
        "state": "CO",
        "asset_type": "Foreclosure Surplus",
        "estimated_surplus": surplus,
        "record_class": d.get("data_grade", "BRONZE"),
        "restriction_status": status,
        "restriction_end_date": restriction_end,
        "blackout_end_date": restriction_end,
        "days_until_actionable": max(0, days_until) if days_until else None,
        "days_to_claim": safe.get("days_remaining"),
        "deadline_passed": (safe.get("days_remaining") or 0) < 0 if safe.get("days_remaining") is not None else None,
        "address_hint": safe.get("city_hint", "CO"),
        "owner_img": None,
        "completeness_score": safe.get("confidence_score") or 0.0,
        "data_age_days": None,
    }


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
    body = await request.json()
    if not body.get("disclaimer_accepted"):
        raise HTTPException(
            status_code=400,
            detail="You must accept the legal disclaimer to unlock restricted leads.",
        )

    # Verify attorney status
    if not _is_admin(user) and not _is_verified_attorney(user):
        raise HTTPException(
            status_code=403,
            detail="RESTRICTED leads require verified attorney status.",
        )
    if not _is_admin(user) and user.get("tier") not in ("operator", "sovereign"):
        raise HTTPException(
            status_code=403,
            detail="RESTRICTED leads require OPERATOR or SOVEREIGN tier.",
        )

    # Delegate to the main unlock handler
    result = await unlock_lead(lead_id, request)
    result["disclaimer_accepted"] = True
    result["attorney_exemption"] = "C.R.S. § 38-13-1302(5)"
    return result


# ── GET /api/dossier/{id} — PDF dossier download ────────────────

@app.get("/api/dossier/{lead_id}")
async def get_dossier(lead_id: str, request: Request):
    """Generate and serve a PDF dossier for an unlocked lead."""
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
    if not _is_admin(user):
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

    # Build dossier data and generate PDF
    import tempfile
    from pathlib import Path

    surplus = _safe_float(lead.get("surplus_amount")) or 0.0
    bid = _safe_float(lead.get("winning_bid")) or 0.0
    status = _compute_status(lead)
    is_restricted = status == "RESTRICTED"

    # Generate simple text-based dossier (avoids fpdf dependency issues)
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
    )


# ── POST /api/billing/checkout — Stripe checkout session ─────────

@app.post("/api/billing/checkout")
async def billing_checkout(request: Request):
    """Create a Stripe checkout session. Frontend calls POST /api/billing/checkout."""
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
                   COALESCE(SUM(surplus_amount), 0) as total_surplus,
                   COALESCE(AVG(surplus_amount), 0) as avg_surplus,
                   COALESCE(MAX(surplus_amount), 0) as max_surplus
            FROM leads
            WHERE COALESCE(surplus_amount, estimated_surplus, 0) > 0
            GROUP BY county ORDER BY total_surplus DESC
        """).fetchall()
    finally:
        conn.close()

    return {
        "count": len(rows),
        "counties": [dict(r) for r in rows],
    }


# ── Admin endpoints (require x-verifuse-api-key) ─────────────────────

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
            "SELECT * FROM leads ORDER BY surplus_amount DESC LIMIT ?", [limit]
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
            "is_admin, is_active, created_at, last_login_at FROM users"
        ).fetchall()
    finally:
        conn.close()
    return {"count": len(rows), "users": [dict(r) for r in rows]}
