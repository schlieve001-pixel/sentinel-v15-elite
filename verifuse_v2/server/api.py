"""
VERIFUSE V2 — Titanium API Guard

Core invariants enforced:
  1. Dynamic Status: RESTRICTED/ACTIONABLE/EXPIRED computed at runtime (UTC).
  2. Hybrid Access Gate: RESTRICTED → attorneys only. ACTIONABLE → paid users. EXPIRED → locked.
  3. Projection Redaction: SafeAsset by default, FullAsset only with valid lead_unlock.
  4. Atomic Transactions: Credit deduction + unlock in BEGIN IMMEDIATE.
  5. Strict CORS, rate limiting, audit everything.
"""

from __future__ import annotations

import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from verifuse_v2.contracts.schemas import EntityRecord, OutcomeRecord, SignalRecord
from verifuse_v2.db import database as db
from verifuse_v2.server.auth import (
    create_token,
    get_current_user,
    get_optional_user,
    hash_password,
    is_admin_user,
    login_user,
    register_user,
    require_admin,
    verify_password,
)
from verifuse_v2.server.billing import (
    TIER_DAILY_API_LIMIT,
    create_checkout_session,
    handle_stripe_webhook,
)
from verifuse_v2.server.models import (
    AttorneyVerifyRequest,
    FullAsset,
    Lead,
    SafeAsset,
    UnlockRequest,
)
from verifuse_v2.server.obfuscator import text_to_image

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# ── Rate Limiter (slowapi) ───────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])

# ── Honeypot ─────────────────────────────────────────────────────────

HONEYPOT_ID = "TRAP_999"
_blacklisted_ips: set[str] = set()

# ── App ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="VeriFuse V2 — Titanium API",
    version="3.0.0",
    description="Colorado Surplus Intelligence Platform (Titanium Spec)",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# STRICT CORS — only trusted origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://verifuse.tech",
        "https://www.verifuse.tech",
        "http://localhost:3000",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


# ── Startup ──────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    db.init_db()
    # Run Titanium migration on startup (idempotent)
    try:
        from verifuse_v2.db.migrate_titanium import migrate
        migrate()
    except Exception as e:
        log.warning("Migration on startup: %s", e)
    # Ensure admin exists
    db.upgrade_to_admin("schlieve001@gmail.com", credits=9999)
    log.info("Titanium API initialized")


# ── Helpers ──────────────────────────────────────────────────────────

def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _get_lead_or_404(asset_id: str) -> Lead:
    """Fetch a lead from DB and return as Lead model, or raise 404."""
    row = db.get_lead_by_id(asset_id)
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found.")
    return Lead.from_row(row)


def _check_unlock(conn: sqlite3.Connection, user_id: str, lead_id: str) -> bool:
    """Check if user has a valid lead_unlock record."""
    row = conn.execute(
        "SELECT 1 FROM lead_unlocks WHERE user_id = ? AND lead_id = ?",
        [user_id, lead_id],
    ).fetchone()
    return row is not None


def _user_unlock_count_last_minute(conn: sqlite3.Connection, user_id: str) -> int:
    """Count unlocks by this user in the last 60 seconds (throttle check)."""
    cutoff = datetime.now(timezone.utc).isoformat()[:19]  # Trim to seconds
    row = conn.execute("""
        SELECT COUNT(*) FROM lead_unlocks
        WHERE user_id = ? AND unlocked_at > datetime(?, '-60 seconds')
    """, [user_id, cutoff]).fetchone()
    return row[0] if row else 0


# ── Middleware ────────────────────────────────────────────────────────

@app.middleware("http")
async def blacklist_check(request: Request, call_next):
    ip = _client_ip(request)
    if ip in _blacklisted_ips:
        log.warning("Blocked blacklisted IP: %s", ip)
        return JSONResponse(status_code=403, content={"detail": "Access denied."})
    return await call_next(request)


@app.middleware("http")
async def enforce_foreign_keys(request: Request, call_next):
    """Ensure PRAGMA foreign_keys = ON for every request cycle."""
    # This runs before each request — the DB connections created
    # during this request will already have FK enforcement from database.py
    return await call_next(request)


# ── Health ───────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    stats = db.get_lead_stats()
    return {
        "status": "ok",
        "engine": "titanium_api",
        "version": "3.0.0",
        "assets": stats["total_assets"],
        "attorney_ready": stats["attorney_ready"],
        "total_surplus": stats["total_claimable_surplus"],
    }


# ── Auth endpoints ───────────────────────────────────────────────────

@app.post("/api/auth/register")
@limiter.limit("5/minute")
async def api_register(request: Request):
    """Register a new attorney account."""
    body = await request.json()
    email = body.get("email", "").strip().lower()
    password = body.get("password", "")
    full_name = body.get("full_name", "")
    firm_name = body.get("firm_name", "")
    bar_number = body.get("bar_number", "")
    tier = body.get("tier", "recon")

    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password required.")

    user, token = register_user(
        email=email, password=password, full_name=full_name,
        firm_name=firm_name, bar_number=bar_number, tier=tier,
    )
    return {
        "token": token,
        "user": {
            "user_id": user["user_id"],
            "email": user["email"],
            "full_name": user["full_name"],
            "firm_name": user["firm_name"],
            "tier": user["tier"],
            "credits_remaining": user["credits_remaining"],
        },
    }


@app.post("/api/auth/login")
@limiter.limit("10/minute")
async def api_login(request: Request):
    """Log in and receive a JWT token."""
    body = await request.json()
    email = body.get("email", "").strip().lower()
    password = body.get("password", "")

    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password required.")

    user, token = login_user(email=email, password=password)
    return {
        "token": token,
        "user": {
            "user_id": user["user_id"],
            "email": user["email"],
            "full_name": user["full_name"],
            "firm_name": user["firm_name"],
            "tier": user["tier"],
            "credits_remaining": user["credits_remaining"],
        },
    }


@app.get("/api/auth/me")
async def api_me(request: Request):
    """Get current user profile."""
    user = get_current_user(request)
    with db.get_db() as conn:
        unlock_count = conn.execute(
            "SELECT COUNT(*) FROM lead_unlocks WHERE user_id = ?",
            [user["user_id"]],
        ).fetchone()[0]
    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "full_name": user["full_name"],
        "firm_name": user["firm_name"],
        "bar_number": user.get("bar_number", ""),
        "attorney_status": user.get("attorney_status", "NONE"),
        "tier": user["tier"],
        "credits_remaining": user["credits_remaining"],
        "unlocked_leads": unlock_count,
        "is_active": bool(user["is_active"]),
        "is_admin": bool(user.get("is_admin", 0)),
    }


# ── Attorney Verification ───────────────────────────────────────────

@app.post("/api/attorney/verify")
async def verify_attorney_status(request: Request):
    """Submit bar number for attorney verification. Sets status to PENDING."""
    user = get_current_user(request)
    body = await request.json()
    bar_number = body.get("bar_number", "").strip()
    bar_state = body.get("bar_state", "CO").strip().upper()

    if not bar_number or len(bar_number) < 3:
        raise HTTPException(status_code=400, detail="Valid bar number required.")

    with db.get_db() as conn:
        conn.execute("""
            UPDATE users SET bar_number = ?, bar_state = ?, attorney_status = 'PENDING'
            WHERE user_id = ?
        """, [bar_number, bar_state, user["user_id"]])

    db.log_pipeline_event(
        user["user_id"], "ATTORNEY_VERIFY_REQUEST",
        old_value=user.get("attorney_status", "NONE"),
        new_value="PENDING",
        actor="api",
        reason=f"bar={bar_number} state={bar_state}",
    )

    return {"status": "PENDING", "bar_number": bar_number, "bar_state": bar_state}


# ── Public endpoints ─────────────────────────────────────────────────

@app.get("/api/stats")
async def get_stats():
    """Dashboard summary stats (public)."""
    return db.get_lead_stats()


@app.get("/api/counties")
async def get_counties():
    """County-level summary (public)."""
    counties = db.get_county_summary()
    statutes = db.get_statute_authority()
    statute_map = {}
    for s in statutes:
        statute_map[s["county"]] = {
            "statute_citation": s["statute_citation"],
            "statute_years": s["statute_years"],
            "requires_court": bool(s["requires_court"]),
            "fee_cap_pct": s["fee_cap_pct"],
        }

    result = []
    for c in counties:
        entry = {
            "county": c["county"],
            "lead_count": c["lead_count"],
            "total_surplus": round(c["total_surplus"], 2),
            "avg_surplus": round(c["avg_surplus"], 2),
            "gold_count": c["gold_count"],
        }
        if c["county"] in statute_map:
            entry["statute"] = statute_map[c["county"]]
        result.append(entry)

    return {"count": len(result), "counties": result}


# ── Lead Browsing (SafeAsset projection) ────────────────────────────

@app.get("/api/leads")
@limiter.limit("100/minute")
async def get_leads(
    request: Request,
    county: Optional[str] = Query(None),
    min_surplus: float = Query(0.0),
    grade: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Return leads as List[SafeAsset]. Expired leads are filtered out.

    SQL Filter: WHERE claim_deadline >= date('now') OR claim_deadline IS NULL
    """
    # Rate limit by tier
    ip = _client_ip(request)
    user = get_optional_user(request)

    # Fetch from DB — only non-expired leads
    with db.get_db() as conn:
        query = """
            SELECT a.*, ls.record_class, ls.work_status
            FROM assets a
            LEFT JOIN legal_status ls ON a.asset_id = ls.asset_id
            WHERE (a.claim_deadline >= date('now') OR a.claim_deadline IS NULL)
              AND a.surplus_amount >= ?
        """
        params: list = [max(min_surplus, 1000.0)]

        if county:
            query += " AND a.county = ?"
            params.append(county)
        if grade:
            query += " AND a.data_grade = ?"
            params.append(grade)

        query += " ORDER BY a.surplus_amount DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()

    # Convert to SafeAsset projections
    leads = []
    for row in rows:
        try:
            lead = Lead.from_row(dict(row))
            safe = SafeAsset.from_lead(lead)

            # Apply status filter if requested
            if status_filter and safe.status != status_filter.upper():
                continue

            leads.append(safe.model_dump())
        except Exception as e:
            log.warning("Lead projection error for %s: %s", dict(row).get("asset_id"), e)
            continue

    # Inject honeypot
    leads.append(_honeypot_safe())

    return {"count": len(leads), "leads": leads}


@app.get("/api/lead/{asset_id}")
@limiter.limit("100/minute")
async def get_lead_detail(asset_id: str, request: Request):
    """Get a single lead as SafeAsset. Or FullAsset if user has unlocked it."""
    ip = _client_ip(request)

    # Honeypot trap
    if asset_id == HONEYPOT_ID:
        log.critical("HONEYPOT HIT — detail from IP %s", ip)
        _blacklisted_ips.add(ip)
        raise HTTPException(status_code=403, detail="Access denied.")

    lead = _get_lead_or_404(asset_id)

    # Check if authenticated user has unlocked this lead
    user = get_optional_user(request)
    if user:
        with db.get_db() as conn:
            if _check_unlock(conn, user["user_id"], asset_id) or is_admin_user(user):
                return FullAsset.from_lead(lead).model_dump()

    # Default: SafeAsset (redacted)
    return SafeAsset.from_lead(lead).model_dump()


# ── Lead Unlock (Atomic Transaction) ────────────────────────────────

@app.post("/api/leads/{asset_id}/unlock")
@limiter.limit("5/minute")
async def unlock_lead(asset_id: str, request: Request):
    """Unlock a lead: atomic credit deduction + record creation.

    Hybrid Access Gate:
      RESTRICTED → Verified attorneys ONLY
      ACTIONABLE → Any paid user
      EXPIRED    → Cannot unlock (locked)

    Returns FullAsset on success.
    """
    user = get_current_user(request)
    ip = _client_ip(request)

    # Honeypot trap
    if asset_id == HONEYPOT_ID:
        log.critical("HONEYPOT HIT — unlock from IP %s user %s", ip, user["user_id"])
        _blacklisted_ips.add(ip)
        raise HTTPException(status_code=403, detail="Access denied.")

    lead = _get_lead_or_404(asset_id)

    # ── Gate 1: Check status ─────────────────────────────────────
    if lead.status == "EXPIRED":
        raise HTTPException(
            status_code=410,
            detail="This lead has expired. The claim deadline has passed.",
        )

    # ── Gate 2: Hybrid access check ──────────────────────────────
    if lead.status == "RESTRICTED":
        # Only verified attorneys can unlock RESTRICTED leads
        attorney_status = user.get("attorney_status", "NONE")
        if attorney_status != "VERIFIED" and not is_admin_user(user):
            raise HTTPException(
                status_code=403,
                detail="RESTRICTED lead: requires verified attorney status. "
                       "Submit your bar number at POST /api/attorney/verify.",
            )

    # ── Gate 3: Atomic credit + unlock (BEGIN IMMEDIATE) ─────────
    # Admin bypasses credit check
    if is_admin_user(user):
        return FullAsset.from_lead(lead).model_dump()

    now = datetime.now(timezone.utc).isoformat()
    conn = db.get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")

        # Check if already unlocked
        existing = conn.execute(
            "SELECT 1 FROM lead_unlocks WHERE user_id = ? AND lead_id = ?",
            [user["user_id"], asset_id],
        ).fetchone()

        if existing:
            conn.execute("COMMIT")
            return FullAsset.from_lead(lead).model_dump()

        # Throttle: max 5 unlocks/min per user
        recent = conn.execute("""
            SELECT COUNT(*) FROM lead_unlocks
            WHERE user_id = ? AND unlocked_at > datetime('now', '-60 seconds')
        """, [user["user_id"]]).fetchone()[0]

        if recent >= 5:
            conn.execute("ROLLBACK")
            raise HTTPException(
                status_code=429,
                detail="Rate limit: max 5 unlocks per minute.",
            )

        # Check credits
        credits_row = conn.execute(
            "SELECT credits_remaining FROM users WHERE user_id = ?",
            [user["user_id"]],
        ).fetchone()

        if not credits_row or credits_row[0] <= 0:
            conn.execute("ROLLBACK")
            raise HTTPException(
                status_code=402,
                detail="Insufficient credits. Upgrade your plan.",
            )

        # ATOMIC: Deduct credit + record unlock
        conn.execute(
            "UPDATE users SET credits_remaining = credits_remaining - 1 WHERE user_id = ?",
            [user["user_id"]],
        )
        conn.execute("""
            INSERT INTO lead_unlocks (user_id, lead_id, unlocked_at, ip_address, plan_tier)
            VALUES (?, ?, ?, ?, ?)
        """, [user["user_id"], asset_id, now, ip, user.get("tier", "recon")])

        # Audit trail
        conn.execute("""
            INSERT INTO pipeline_events
            (asset_id, event_type, old_value, new_value, actor, reason, created_at)
            VALUES (?, 'LEAD_UNLOCK', ?, ?, ?, ?, ?)
        """, [
            asset_id,
            f"credits={credits_row[0]}",
            f"credits={credits_row[0] - 1}",
            user["user_id"],
            f"ip={ip} tier={user.get('tier')} status={lead.status}",
            now,
        ])

        conn.execute("COMMIT")

    except HTTPException:
        raise
    except Exception as e:
        conn.execute("ROLLBACK")
        log.error("Unlock transaction failed: %s", e)
        raise HTTPException(status_code=500, detail="Unlock failed.")
    finally:
        conn.close()

    return FullAsset.from_lead(lead).model_dump()


# ── User endpoints ───────────────────────────────────────────────────

@app.get("/api/user/unlocks")
async def get_user_unlock_history(request: Request):
    """Get the authenticated user's unlock history with lead details."""
    user = get_current_user(request)
    with db.get_db() as conn:
        rows = conn.execute("""
            SELECT lu.lead_id, lu.unlocked_at, lu.plan_tier,
                   a.county, a.surplus_amount, a.data_grade
            FROM lead_unlocks lu
            JOIN assets a ON lu.lead_id = a.asset_id
            WHERE lu.user_id = ?
            ORDER BY lu.unlocked_at DESC
        """, [user["user_id"]]).fetchall()

    return {
        "user_id": user["user_id"],
        "credits_remaining": user["credits_remaining"],
        "total_unlocks": len(rows),
        "unlocks": [dict(r) for r in rows],
    }


# ── Dossier PDF ──────────────────────────────────────────────────────

@app.get("/api/dossier/{asset_id}")
async def get_dossier(asset_id: str, request: Request):
    """Generate and return a Dossier PDF (free teaser — no credits)."""
    ip = _client_ip(request)
    if asset_id == HONEYPOT_ID:
        _blacklisted_ips.add(ip)
        raise HTTPException(status_code=403, detail="Access denied.")

    raw = db.get_lead_by_id(asset_id)
    if not raw:
        raise HTTPException(status_code=404, detail="Lead not found.")

    lead = Lead.from_row(raw)

    signal = SignalRecord(
        signal_id=lead.asset_id,
        county=lead.county,
        signal_type="FORECLOSURE_FILED",
        case_number=lead.case_number or "",
        event_date=lead.sale_date or "",
        source_url=lead.recorder_link or "",
        property_address=lead.property_address,
    )
    outcome = OutcomeRecord(
        signal_id=lead.asset_id,
        outcome_type="OVERBID" if lead.effective_surplus > 100 else "NO_SURPLUS",
        gross_amount=lead.overbid_amount,
        net_amount=lead.effective_surplus,
        holding_entity="Trustee",
        confidence_score=lead.confidence_score,
        source_url=lead.recorder_link or "",
    )
    entity = EntityRecord(
        signal_id=lead.asset_id,
        entity_type="OWNER",
        name=lead.owner_of_record,
        mailing_address=lead.property_address,
        contact_score=int(lead.completeness_score * 100),
    )

    is_restricted = lead.status == "RESTRICTED"

    try:
        from verifuse_v2.server.dossier_gen import generate_dossier
        pdf_path = generate_dossier(signal, outcome, entity, is_restricted=is_restricted)
    except Exception as exc:
        log.error("Dossier generation failed for %s: %s", asset_id, exc)
        raise HTTPException(status_code=500, detail="Dossier generation failed.")

    return FileResponse(path=pdf_path, media_type="application/pdf", filename=Path(pdf_path).name)


# ── Stripe endpoints ────────────────────────────────────────────────

@app.post("/api/billing/checkout")
async def api_checkout(request: Request):
    """Create a Stripe Checkout session."""
    user = get_current_user(request)
    body = await request.json()
    tier = body.get("tier", "operator")
    url = create_checkout_session(user["user_id"], user["email"], tier)
    return {"checkout_url": url}


@app.post("/api/webhooks/stripe")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events."""
    return await handle_stripe_webhook(request)


# ── Admin endpoints ──────────────────────────────────────────────────

@app.get("/api/admin/stats")
async def admin_stats(request: Request):
    """Full system stats (admin only)."""
    require_admin(request)
    stats = db.get_lead_stats()
    with db.get_db() as conn:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_unlocks = conn.execute("SELECT COUNT(*) FROM lead_unlocks").fetchone()[0]
        total_events = conn.execute("SELECT COUNT(*) FROM pipeline_events").fetchone()[0]
    stats.update({
        "total_users": total_users,
        "total_unlocks": total_unlocks,
        "total_events": total_events,
    })
    return stats


@app.get("/api/admin/leads")
async def admin_leads(request: Request, limit: int = Query(500, ge=1, le=5000)):
    """Get all leads with raw data (admin only)."""
    require_admin(request)
    return {"leads": db.get_all_leads_raw(limit=limit)}


@app.post("/api/admin/regrade")
async def admin_regrade(request: Request):
    """Trigger a full regrade of all assets (admin only)."""
    require_admin(request)
    from verifuse_v2.daily_healthcheck import regrade_all_assets
    result = regrade_all_assets()
    return {"status": "ok", "result": result}


@app.post("/api/admin/dedup")
async def admin_dedup(request: Request):
    """Trigger deduplication (admin only)."""
    require_admin(request)
    result = db.deduplicate_assets()
    return {"status": "ok", "result": result}


@app.get("/api/admin/users")
async def admin_users(request: Request):
    """Get all users (admin only)."""
    require_admin(request)
    return {"users": db.get_all_users()}


@app.post("/api/admin/upgrade-user")
async def admin_upgrade_user(request: Request):
    """Upgrade a user to admin (admin only)."""
    require_admin(request)
    body = await request.json()
    email = body.get("email", "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email required.")
    success = db.upgrade_to_admin(email)
    if not success:
        raise HTTPException(status_code=404, detail="User not found.")
    return {"status": "ok", "email": email}


@app.post("/api/admin/verify-attorney")
async def admin_verify_attorney(request: Request):
    """Verify (or reject) an attorney's bar number (admin only)."""
    require_admin(request)
    body = await request.json()
    user_id = body.get("user_id", "")
    action = body.get("action", "verify")  # "verify" or "reject"

    if action not in ("verify", "reject"):
        raise HTTPException(status_code=400, detail="action must be 'verify' or 'reject'")

    new_status = "VERIFIED" if action == "verify" else "REJECTED"
    now = datetime.now(timezone.utc).isoformat()

    with db.get_db() as conn:
        result = conn.execute("""
            UPDATE users SET attorney_status = ?,
                attorney_verified_at = CASE WHEN ? = 'VERIFIED' THEN ? ELSE attorney_verified_at END
            WHERE user_id = ?
        """, [new_status, new_status, now, user_id])

        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found.")

    return {"status": new_status, "user_id": user_id}


# ── Honeypot helpers ─────────────────────────────────────────────────

def _honeypot_safe() -> dict:
    """Generate honeypot as SafeAsset dict."""
    return {
        "asset_id": HONEYPOT_ID,
        "county": "Arapahoe",
        "state": "CO",
        "case_number": "2024-HT-999",
        "asset_type": "FORECLOSURE_SURPLUS",
        "status": "ACTIONABLE",
        "surplus_estimate": 5_000_000.00,
        "data_grade": "GOLD",
        "confidence_score": 0.95,
        "sale_date": "2024-05-01",
        "claim_deadline": "2025-10-28",
        "days_remaining": 999,
        "city_hint": "Arapahoe, CO",
        "surplus_verified": True,
    }
