"""
VERIFUSE V2 — Product API (FastAPI)

Serves leads from the production database with obfuscated PII,
generates dossier/motion PDFs, enforces honeypot + blacklist,
and manages auth/credits (Phase 2).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from verifuse_v2.contracts.schemas import EntityRecord, OutcomeRecord, SignalRecord
from verifuse_v2.db import database as db
from verifuse_v2.server.dossier_gen import generate_dossier
from verifuse_v2.server.motion_gen import generate_motion
from verifuse_v2.server.auth import (
    get_current_user,
    get_optional_user,
    register_user,
    login_user,
    require_admin,
    is_admin_user,
    verify_attorney,
)
from verifuse_v2.server.billing import create_checkout_session, handle_stripe_webhook
from verifuse_v2.server.obfuscator import text_to_image

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# ── Honeypot ─────────────────────────────────────────────────────────

HONEYPOT_ID = "TRAP_999"

# In-memory blacklist (persists for server lifetime)
_blacklisted_ips: set[str] = set()

# ── Anti-scraping rate limiter ───────────────────────────────────────

from collections import defaultdict

# Track API calls per IP per day: {ip: {"date": "2026-02-11", "count": 0}}
_rate_limits: dict[str, dict] = defaultdict(lambda: {"date": "", "count": 0})

ANON_DAILY_LIMIT = 20  # Unauthenticated users get 20 lead views/day

# ── App ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="VeriFuse V2 — Product API",
    version="2.0.0",
    description="Colorado Surplus Intelligence Platform",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",       # Vite dev server
        "http://localhost:3000",
        "https://verifuse.tech",
        "https://app.verifuse.tech",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Startup ──────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    db.init_db()
    # Ensure admin column exists (migration for existing DBs)
    try:
        with db.get_db() as conn:
            conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
    except Exception:
        pass  # Column already exists
    try:
        with db.get_db() as conn:
            conn.execute("ALTER TABLE users ADD COLUMN attorney_verified_at TEXT")
    except Exception:
        pass
    try:
        with db.get_db() as conn:
            conn.execute("ALTER TABLE unlocks ADD COLUMN disclaimer_accepted INTEGER DEFAULT 0")
    except Exception:
        pass
    # Upgrade CTO to admin if they exist
    db.upgrade_to_admin("schlieve001@gmail.com", credits=9999)
    log.info("Database initialized")


# ── Helpers ──────────────────────────────────────────────────────────

def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _compute_claim_deadline(sale_date: str | None) -> dict:
    """Compute the real 180-day claim deadline from sale_date.

    C.R.S. § 38-38-111: Surplus must be claimed within ~180 days
    of the foreclosure sale. After that, funds may escheat to the
    state via the Great Colorado Payback.
    """
    CLAIM_WINDOW_DAYS = 180
    if not sale_date:
        return {"claim_deadline": None, "days_to_claim": None, "deadline_passed": None}
    try:
        dt = datetime.fromisoformat(sale_date)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        deadline = dt + timedelta(days=CLAIM_WINDOW_DAYS)
        now = datetime.now(timezone.utc)
        days_left = (deadline - now).days
        return {
            "claim_deadline": deadline.strftime("%Y-%m-%d"),
            "days_to_claim": max(days_left, 0),
            "deadline_passed": days_left < 0,
        }
    except (ValueError, TypeError):
        return {"claim_deadline": None, "days_to_claim": None, "deadline_passed": None}


def _compute_restriction_period(sale_date: str | None) -> dict:
    """Compute the C.R.S. § 38-38-111 restriction period.

    For the first 6 months after sale: compensation agreements are PROHIBITED.
    Months 7-30: funds at State Treasurer, agreements still VOID.
    After ~2.5 years: finder agreements allowed (20% cap, then 30%).
    Attorney-client agreements exempt per C.R.S. § 38-13-1302(5).
    """
    RESTRICTION_DAYS = 180  # 6 months — public trustee holds funds
    BLACKOUT_DAYS = 912     # ~2.5 years — total finder fee blackout
    if not sale_date:
        return {
            "restriction_status": "UNKNOWN",
            "restriction_end_date": None,
            "blackout_end_date": None,
            "days_until_actionable": None,
        }
    try:
        dt = datetime.fromisoformat(sale_date)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        restriction_end = dt + timedelta(days=RESTRICTION_DAYS)
        blackout_end = dt + timedelta(days=BLACKOUT_DAYS)
        now = datetime.now(timezone.utc)
        days_since_sale = (now - dt).days

        if days_since_sale < RESTRICTION_DAYS:
            status = "RESTRICTED"
        elif days_since_sale < BLACKOUT_DAYS:
            status = "WATCHLIST"
        else:
            status = "ACTIONABLE"

        return {
            "restriction_status": status,
            "restriction_end_date": restriction_end.strftime("%Y-%m-%d"),
            "blackout_end_date": blackout_end.strftime("%Y-%m-%d"),
            "days_until_actionable": max((restriction_end - now).days, 0),
        }
    except (ValueError, TypeError):
        return {
            "restriction_status": "UNKNOWN",
            "restriction_end_date": None,
            "blackout_end_date": None,
            "days_until_actionable": None,
        }


def _surplus_verified(lead: dict) -> bool:
    """Check if surplus math is verifiable (has both bid and indebtedness)."""
    surplus = lead.get("estimated_surplus") or 0
    indebtedness = lead.get("total_indebtedness") or 0
    overbid = lead.get("overbid_amount") or 0
    # Verified if we have either: overbid > 0 OR (indebtedness > 0 and surplus > 0)
    return overbid > 0 or (indebtedness > 0 and surplus > 0)


def _compute_data_age_days(updated_at: str | None) -> int | None:
    """Compute how many days since the data was last refreshed.

    Bug fix: previously always returned 0 because it was never computed.
    Now uses updated_at timestamp from the database.
    """
    if not updated_at:
        return None
    try:
        dt = datetime.fromisoformat(updated_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).days
    except (ValueError, TypeError):
        return None


def _obfuscate_lead(lead: dict) -> dict:
    """Convert a raw database lead into an obfuscated API response.

    SECURITY: No raw PII text is ever sent to the browser.
    - Owner name → rendered as Base64 PNG image (OCR-resistant)
    - Property address → truncated to county only (full address is paid data)
    - All sensitive text stays server-side until credit-gated unlock
    """
    owner = lead.get("owner_of_record") or ""
    address = lead.get("property_address") or ""
    sale_date = lead.get("sale_date")
    deadline = _compute_claim_deadline(sale_date)
    restriction = _compute_restriction_period(sale_date)

    # Truncate address to city/county only — no street number or name
    address_hint = ""
    if address:
        parts = [p.strip() for p in address.split(",")]
        if len(parts) >= 2:
            address_hint = ", ".join(parts[-2:])  # "Denver, CO 80203"
        else:
            address_hint = lead.get("county", "") + ", CO"

    data_age = _compute_data_age_days(lead.get("updated_at"))

    return {
        "asset_id": lead["asset_id"],
        "county": lead.get("county", ""),
        "state": lead.get("state", "CO"),
        "case_number": lead.get("case_number", ""),
        "asset_type": lead.get("asset_type", ""),
        "estimated_surplus": lead.get("estimated_surplus", 0),
        "surplus_verified": _surplus_verified(lead),
        "data_grade": lead.get("data_grade", ""),
        "record_class": lead.get("record_class", ""),
        "sale_date": sale_date,
        # Real 180-day deadline — replaces bogus "5 years from sale_date"
        "claim_deadline": deadline["claim_deadline"],
        "days_to_claim": deadline["days_to_claim"],
        "deadline_passed": deadline["deadline_passed"],
        # C.R.S. § 38-38-111 restriction period
        "restriction_status": restriction["restriction_status"],
        "restriction_end_date": restriction["restriction_end_date"],
        "blackout_end_date": restriction["blackout_end_date"],
        "days_until_actionable": restriction["days_until_actionable"],
        # Address is city/county only — street-level is behind unlock
        "address_hint": address_hint,
        # PII fields are obfuscated — raw text NEVER in response
        "owner_img": text_to_image(owner) if owner else None,
        "completeness_score": lead.get("completeness_score", 0),
        "confidence_score": lead.get("confidence_score", 0),
        # Data freshness — how many days since last update
        "data_age_days": data_age,
    }


def _honeypot_lead() -> dict:
    """Generate the honeypot trap record."""
    trap_sale = "2024-11-01"
    deadline = _compute_claim_deadline(trap_sale)
    restriction = _compute_restriction_period(trap_sale)
    return {
        "asset_id": HONEYPOT_ID,
        "county": "Arapahoe",
        "state": "CO",
        "case_number": "2024-HT-999",
        "asset_type": "FORECLOSURE_SURPLUS",
        "estimated_surplus": 5_000_000.00,
        "surplus_verified": True,
        "data_grade": "GOLD",
        "record_class": "ATTORNEY",
        "sale_date": trap_sale,
        "claim_deadline": deadline["claim_deadline"],
        "days_to_claim": deadline["days_to_claim"],
        "deadline_passed": deadline["deadline_passed"],
        "restriction_status": restriction["restriction_status"],
        "restriction_end_date": restriction["restriction_end_date"],
        "blackout_end_date": restriction["blackout_end_date"],
        "days_until_actionable": restriction["days_until_actionable"],
        "address_hint": "Arapahoe, CO",
        "owner_img": text_to_image("J. Doe Revocable Trust"),
        "completeness_score": 1.0,
        "confidence_score": 0.95,
        "data_age_days": 1,
    }


# ── Middleware ────────────────────────────────────────────────────────

@app.middleware("http")
async def blacklist_check(request: Request, call_next):
    ip = _client_ip(request)
    if ip in _blacklisted_ips:
        log.warning("Blocked blacklisted IP: %s", ip)
        return JSONResponse(status_code=403, content={"detail": "Access denied."})
    return await call_next(request)


# ── Auth endpoints ────────────────────────────────────────────────────

@app.post("/api/auth/register")
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


## NOTE: /api/auth/me moved below admin endpoints with admin flag support


# ── Public endpoints (no auth required) ──────────────────────────────

@app.get("/api/stats")
async def get_stats():
    """Dashboard summary stats (public — used on landing page)."""
    return db.get_lead_stats()


@app.get("/api/counties")
async def get_counties():
    """County-level summary: lead counts, surplus totals, and statute rules.

    Public endpoint — used on landing page to show coverage map.
    """
    counties = db.get_county_summary()
    statutes = db.get_statute_authority()

    # Build a lookup of statute rules by county
    statute_map = {}
    for s in statutes:
        statute_map[s["county"]] = {
            "statute_citation": s["statute_citation"],
            "statute_years": s["statute_years"],
            "requires_court": bool(s["requires_court"]),
            "fee_cap_pct": s["fee_cap_pct"],
            "confidence": s["confidence"],
        }

    result = []
    for c in counties:
        entry = {
            "county": c["county"],
            "lead_count": c["lead_count"],
            "total_surplus": round(c["total_surplus"], 2),
            "avg_surplus": round(c["avg_surplus"], 2),
            "max_surplus": round(c["max_surplus"], 2),
            "gold_count": c["gold_count"],
            "attorney_count": c["attorney_count"],
        }
        if c["county"] in statute_map:
            entry["statute"] = statute_map[c["county"]]
        result.append(entry)

    return {"count": len(result), "counties": result}


@app.get("/api/user/unlocks")
async def get_user_unlock_history(request: Request):
    """Get the authenticated user's unlock history with lead details."""
    user = get_current_user(request)
    unlocks = db.get_user_unlocks(user["user_id"])

    return {
        "user_id": user["user_id"],
        "credits_remaining": user["credits_remaining"],
        "total_unlocks": len(unlocks),
        "unlocks": [
            {
                "asset_id": u["asset_id"],
                "county": u["county"],
                "owner": u["owner_of_record"],
                "surplus": u["estimated_surplus"],
                "address": u["property_address"],
                "unlocked_at": u["created_at"],
            }
            for u in unlocks
        ],
    }


@app.get("/api/leads")
async def get_leads(
    request: Request,
    county: Optional[str] = Query(None),
    min_surplus: float = Query(0.0),
    grade: Optional[str] = Query(None),
    bucket: Optional[str] = Query(None),  # "actionable" or "watchlist"
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Return leads with obfuscated PII. Honeypot injected.

    bucket=actionable: sold > 6 months ago (compensation agreements allowed)
    bucket=watchlist: sold < 6 months ago (C.R.S. § 38-38-111 restriction)
    """
    # Anti-scraping: rate limit check
    ip = _client_ip(request)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _rate_limits[ip]["date"] != today:
        _rate_limits[ip] = {"date": today, "count": 0}
    _rate_limits[ip]["count"] += 1

    # Check user tier for limit (admin bypasses)
    from verifuse_v2.server.billing import TIER_DAILY_API_LIMIT
    user = get_optional_user(request)
    daily_limit = ANON_DAILY_LIMIT
    if user:
        if is_admin_user(user):
            daily_limit = 999999  # Admin bypasses rate limits
        else:
            daily_limit = TIER_DAILY_API_LIMIT.get(user.get("tier", "recon"), 50)
    if _rate_limits[ip]["count"] > daily_limit:
        raise HTTPException(status_code=429, detail="Daily API limit reached. Upgrade your plan for higher limits.")

    # Enforce $1,000 minimum — no junk data
    raw_leads = db.get_leads(
        county=county,
        min_surplus=max(min_surplus, 1000.0),
        grade=grade,
        limit=limit,
        offset=offset,
    )

    leads = [_obfuscate_lead(l) for l in raw_leads]

    # Filter by restriction bucket if requested
    if bucket == "actionable":
        leads = [l for l in leads if l["restriction_status"] in ("ACTIONABLE", "WATCHLIST", "UNKNOWN")]
    elif bucket == "watchlist":
        leads = [l for l in leads if l["restriction_status"] == "RESTRICTED"]

    # Inject honeypot
    leads.append(_honeypot_lead())

    return {"count": len(leads), "leads": leads}


# ── Auth-required endpoints (Phase 2 will add @require_auth) ─────────

@app.get("/api/lead/{asset_id}")
async def get_lead_detail(asset_id: str, request: Request):
    """Get detailed (but still obfuscated) view of a single lead."""
    ip = _client_ip(request)
    if asset_id == HONEYPOT_ID:
        log.critical("SECURITY EVENT — Honeypot detail from IP %s", ip)
        _blacklisted_ips.add(ip)
        raise HTTPException(status_code=403, detail="Access denied.")

    lead = db.get_lead_by_id(asset_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")

    return _obfuscate_lead(lead)


@app.get("/api/dossier/{asset_id}")
async def get_dossier(asset_id: str, request: Request):
    """Generate and return a Dossier PDF (free teaser — no credits)."""
    ip = _client_ip(request)
    if asset_id == HONEYPOT_ID:
        log.critical("SECURITY EVENT — Honeypot dossier from IP %s", ip)
        _blacklisted_ips.add(ip)
        raise HTTPException(status_code=403, detail="Access denied.")

    lead = db.get_lead_by_id(asset_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")

    # Build contract objects from database row for PDF generation
    signal = SignalRecord(
        signal_id=lead["asset_id"],
        county=lead.get("county", "Denver"),
        signal_type="FORECLOSURE_FILED",
        case_number=lead.get("case_number", ""),
        event_date=lead.get("sale_date", ""),
        source_url=lead.get("recorder_link", ""),
        property_address=lead.get("property_address"),
    )
    outcome = OutcomeRecord(
        signal_id=lead["asset_id"],
        outcome_type="OVERBID" if (lead.get("estimated_surplus") or 0) > 100 else "NO_SURPLUS",
        gross_amount=lead.get("overbid_amount"),
        net_amount=lead.get("estimated_surplus"),
        holding_entity="Trustee",
        confidence_score=lead.get("confidence_score", 0),
        source_url=lead.get("recorder_link", ""),
    )
    entity = EntityRecord(
        signal_id=lead["asset_id"],
        entity_type="OWNER",
        name=lead.get("owner_of_record"),
        mailing_address=lead.get("property_address"),
        contact_score=int((lead.get("completeness_score") or 0) * 100),
    )

    # Determine restriction status for disclaimer page
    from verifuse_v2.server.api import _compute_restriction_period
    restriction = _compute_restriction_period(lead.get("sale_date"))
    is_restricted = restriction["restriction_status"] == "RESTRICTED"

    try:
        pdf_path = generate_dossier(signal, outcome, entity, is_restricted=is_restricted)
    except Exception as exc:
        log.error("Dossier generation failed for %s: %s", asset_id, exc)
        raise HTTPException(status_code=500, detail="Dossier generation failed.")

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=Path(pdf_path).name,
    )


@app.post("/api/unlock/{asset_id}")
async def unlock_lead(asset_id: str, request: Request):
    """Unlock a lead: deduct credit, return raw PII + generate motion PDF.

    Phase 2 will add real auth. For now, returns raw data for testing.
    """
    ip = _client_ip(request)

    # Honeypot trap
    if asset_id == HONEYPOT_ID:
        log.critical("SECURITY EVENT — Honeypot unlock from IP %s at %s",
                     ip, datetime.now(timezone.utc).isoformat())
        _blacklisted_ips.add(ip)
        raise HTTPException(status_code=403, detail="Access denied.")

    lead = db.get_lead_by_id(asset_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")

    # Auth + credit check (admin bypasses)
    user = get_optional_user(request)
    if user:
        if not is_admin_user(user):
            # Already unlocked? Return without deducting
            if not db.has_unlocked(user["user_id"], asset_id):
                if not db.record_unlock(user["user_id"], asset_id):
                    raise HTTPException(status_code=402, detail="Insufficient credits. Upgrade your plan.")
    # If no auth header, allow for now (testing mode) — Phase 4 will enforce

    # Generate motion PDF
    pdf_path: str | None = None
    surplus = lead.get("estimated_surplus") or 0
    if surplus > 100:
        try:
            outcome = OutcomeRecord(
                signal_id=lead["asset_id"],
                outcome_type="OVERBID",
                gross_amount=lead.get("overbid_amount"),
                net_amount=surplus,
                holding_entity="Trustee",
                confidence_score=lead.get("confidence_score", 0),
                source_url=lead.get("recorder_link", ""),
            )
            entity = EntityRecord(
                signal_id=lead["asset_id"],
                entity_type="OWNER",
                name=lead.get("owner_of_record"),
                mailing_address=lead.get("property_address"),
            )
            pdf_path = generate_motion(outcome, entity)
        except Exception as exc:
            log.error("Motion generation failed for %s: %s", asset_id, exc)

    # Return raw (unobfuscated) data — this is the paid product
    return {
        "asset_id": asset_id,
        "owner_name": lead.get("owner_of_record"),
        "property_address": lead.get("property_address"),
        "county": lead.get("county"),
        "case_number": lead.get("case_number"),
        "estimated_surplus": surplus,
        "total_indebtedness": lead.get("total_indebtedness"),
        "overbid_amount": lead.get("overbid_amount"),
        "sale_date": lead.get("sale_date"),
        "days_remaining": lead.get("days_remaining"),
        "statute_window": lead.get("statute_window"),
        "recorder_link": lead.get("recorder_link"),
        "data_grade": lead.get("data_grade"),
        "confidence_score": lead.get("confidence_score"),
        "motion_pdf": pdf_path,
    }


@app.get("/api/motion/{asset_id}")
async def download_motion(asset_id: str):
    """Download a previously generated motion PDF."""
    motions_dir = DATA_DIR / "motions"
    if not motions_dir.exists():
        raise HTTPException(status_code=404, detail="No motions available.")

    case_ref = asset_id[:12].upper()
    for pdf in motions_dir.glob(f"motion_{case_ref}_*.pdf"):
        return FileResponse(path=str(pdf), media_type="application/pdf", filename=pdf.name)

    raise HTTPException(status_code=404, detail="Motion not found.")


# ── Stripe endpoints ──────────────────────────────────────────────────

@app.post("/api/billing/checkout")
async def api_checkout(request: Request):
    """Create a Stripe Checkout session for subscription signup."""
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
    user = require_admin(request)
    stats = db.get_lead_stats()
    with db.get_db() as conn:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_unlocks = conn.execute("SELECT COUNT(*) FROM unlocks").fetchone()[0]
        total_events = conn.execute("SELECT COUNT(*) FROM pipeline_events").fetchone()[0]
        # Data quality metrics
        zero_indebtedness = conn.execute(
            "SELECT COUNT(*) FROM assets WHERE total_indebtedness = 0 AND estimated_surplus > 0"
        ).fetchone()[0]
        high_confidence_bad = conn.execute(
            "SELECT COUNT(*) FROM assets WHERE confidence_score > 0.8 AND total_indebtedness = 0"
        ).fetchone()[0]
    stats.update({
        "total_users": total_users,
        "total_unlocks": total_unlocks,
        "total_events": total_events,
        "zero_indebtedness_count": zero_indebtedness,
        "high_confidence_bad_data": high_confidence_bad,
    })
    return stats


@app.get("/api/admin/leads")
async def admin_leads(request: Request, limit: int = Query(500, ge=1, le=5000)):
    """Get all leads with raw unobfuscated data (admin only)."""
    user = require_admin(request)
    return {"leads": db.get_all_leads_raw(limit=limit)}


@app.post("/api/admin/regrade")
async def admin_regrade(request: Request):
    """Trigger a full regrade of all assets (admin only)."""
    user = require_admin(request)
    from verifuse_v2.daily_healthcheck import regrade_all_assets
    result = regrade_all_assets()
    return {"status": "ok", "result": result}


@app.post("/api/admin/dedup")
async def admin_dedup(request: Request):
    """Trigger deduplication of all assets (admin only)."""
    user = require_admin(request)
    result = db.deduplicate_assets()
    return {"status": "ok", "result": result}


@app.get("/api/admin/users")
async def admin_users(request: Request):
    """Get all users (admin only)."""
    user = require_admin(request)
    return {"users": db.get_all_users()}


@app.post("/api/admin/upgrade-user")
async def admin_upgrade_user(request: Request):
    """Upgrade a user to admin (admin only)."""
    user = require_admin(request)
    body = await request.json()
    email = body.get("email", "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email required.")
    success = db.upgrade_to_admin(email)
    if not success:
        raise HTTPException(status_code=404, detail="User not found.")
    return {"status": "ok", "email": email}


# ── Restricted lead unlock (attorney only) ──────────────────────────

@app.post("/api/unlock-restricted/{asset_id}")
async def unlock_restricted_lead(asset_id: str, request: Request):
    """Unlock a RESTRICTED lead — requires verified attorney status.

    C.R.S. § 38-13-1302(5) exempts attorney-client agreements from
    the compensation agreement prohibition in C.R.S. § 38-38-111.
    """
    user = get_current_user(request)

    # Require bar_number
    if not verify_attorney(user):
        raise HTTPException(
            status_code=403,
            detail="Attorney verification required. Please update your bar number in your profile.",
        )

    # Require disclaimer acceptance
    body = await request.json()
    if not body.get("disclaimer_accepted"):
        raise HTTPException(
            status_code=400,
            detail="You must accept the legal disclaimer before unlocking restricted leads.",
        )

    lead = db.get_lead_by_id(asset_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")

    # Check admin bypass
    if not is_admin_user(user):
        # Deduct credit
        if not db.has_unlocked(user["user_id"], asset_id):
            if not db.record_unlock(user["user_id"], asset_id):
                raise HTTPException(status_code=402, detail="Insufficient credits.")

    # Record disclaimer acceptance
    with db.get_db() as conn:
        conn.execute("""
            UPDATE unlocks SET disclaimer_accepted = 1
            WHERE user_id = ? AND asset_id = ?
        """, [user["user_id"], asset_id])

    return {
        "asset_id": asset_id,
        "owner_name": lead.get("owner_of_record"),
        "property_address": lead.get("property_address"),
        "county": lead.get("county"),
        "case_number": lead.get("case_number"),
        "estimated_surplus": lead.get("estimated_surplus", 0),
        "total_indebtedness": lead.get("total_indebtedness"),
        "overbid_amount": lead.get("overbid_amount"),
        "sale_date": lead.get("sale_date"),
        "disclaimer_accepted": True,
        "attorney_exemption": "C.R.S. § 38-13-1302(5)",
    }


# ── Auth-aware leads (admin bypass) ─────────────────────────────────

@app.get("/api/auth/me")
async def api_me_v2(request: Request):
    """Get current user profile with admin flag."""
    user = get_current_user(request)
    unlocks = db.get_user_unlocks(user["user_id"])
    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "full_name": user["full_name"],
        "firm_name": user["firm_name"],
        "bar_number": user.get("bar_number", ""),
        "tier": user["tier"],
        "credits_remaining": user["credits_remaining"],
        "unlocked_assets": len(unlocks),
        "is_active": bool(user["is_active"]),
        "is_admin": bool(user.get("is_admin", 0)),
    }


@app.get("/health")
async def health():
    stats = db.get_lead_stats()
    return {
        "status": "ok",
        "engine": "product_api",
        "version": "2.0.0",
        "assets": stats["total_assets"],
        "attorney_ready": stats["attorney_ready"],
        "total_surplus": stats["total_claimable_surplus"],
    }
