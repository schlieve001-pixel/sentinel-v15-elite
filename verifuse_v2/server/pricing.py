"""
VeriFuse vNEXT — Canonical Pricing & Entitlements

Single source of truth for tier credits, rate limits, and dynamic pricing.
Import from here — never hardcode tier constants elsewhere.

Phase 0 semantics:
  - 1 unlock = 1 credit (get_credit_cost exists but is NOT called from unlock)
  - Dynamic pricing deferred to Phase 1
"""

from __future__ import annotations

import os
from typing import Optional


# ── Tier definitions ──────────────────────────────────────────────────

TIERS: dict[str, dict] = {
    "associate": {
        "monthly_price_cents": 19900,  # $199/month (Investigator)
        "credits": 30,
        "daily_limit": None,
        "sessions": 1,
        "label": "Investigator",
        "rollover_days": 30,
        "max_bank_multiplier": 1.5,    # max 45 banked
        "access": ["foreclosure_overbid", "tax_deed"],
    },
    "partner": {
        "monthly_price_cents": 39900,  # $399/month
        "credits": 75,
        "daily_limit": None,
        "sessions": 2,
        "label": "Partner",
        "rollover_days": 60,
        "max_bank_multiplier": 1.5,    # max 113 banked
        "access": ["foreclosure_overbid", "tax_lien", "tax_deed", "unclaimed_property"],
    },
    "sovereign": {
        "monthly_price_cents": 89900,  # $899/month (Enterprise)
        "credits": 200,
        "daily_limit": None,
        "sessions": 5,
        "label": "Enterprise",
        "rollover_days": 90,
        "max_bank_multiplier": 1.5,    # max 300 banked
        "access": ["foreclosure_overbid", "tax_lien", "tax_deed", "hoa", "unclaimed_property", "estate_cases", "api", "county_reports"],
    },
}

# ── Rollover configuration (per-tier, also available as flat dicts) ───

ROLLOVER_DAYS: dict[str, int] = {
    "associate": 30,
    "partner":   60,
    "sovereign": 90,
}

MAX_BANK_MULTIPLIER: dict[str, float] = {
    "associate": 1.5,   # 30 credits/mo * 1.5 = max 45 banked
    "partner":   1.5,   # 100 credits/mo * 1.5 = max 150 banked
    "sovereign": 1.5,   # 250 credits/mo * 1.5 = max 375 banked
}

# ── Credit costs (universal currency) ────────────────────────────────
#
# 1 credit  = 1 standard lead unlock
# 3 credits = 1 Filing Pack (motion template + owner address + lien summary + evidence bundle)
# 5 credits = 1 Premium Dossier (Filing Pack + heir notification letter)
# 2 credits = 1 Tax Lien Report (per county, per month)

CREDIT_COSTS: dict[str, int] = {
    "standard_unlock":   1,
    "filing_pack":       3,
    "premium_dossier":   5,
    "tax_lien_report":   2,
    "rtf_unlock":        3,   # READY_TO_FILE leads cost 3 credits (premium tier)
}

# ── One-time credit packs ─────────────────────────────────────────────

STARTER_PACK: dict = {
    "credits": 10,
    "price_cents": 4900,    # $49.00 one-time
    "expiry_days": 90,
    "label": "Starter Pack",
}

INVESTIGATION_PACK: dict = {
    "credits": 25,
    "price_cents": 9900,    # $99.00 one-time
    "expiry_days": 90,
    "label": "Investigation Pack",
}

# ── Add-on cash prices ────────────────────────────────────────────────

ADD_ON_CASH_PRICES: dict[str, int] = {
    "filing_pack":       4900,   # $49/case
    "premium_dossier":   7900,   # $79/case
    "tax_lien_report":   2900,   # $29/county/month
    "bulk_co_report":    29900,  # $299: all 64 counties, one surplus type, one month
}

FOUNDERS_MAX_SLOTS: int = 100
FOUNDERS_BONUS_SLOTS: int = 10   # First 10 get locked founding pricing + 5 extra credits

# ── Signup & welcome bonuses ──────────────────────────────────────────
#
# Every new registration gets SIGNUP_BONUS_CREDITS free (no card required).
# On first subscription payment, users get FIRST_MONTH_BONUS[tier] extra credits
# stacked on top of their normal monthly allocation.
#
# First-month totals:
#   Investigator: 30 + 10 = 40 credits
#   Partner:      75 + 25 = 100 credits
#   Enterprise:  200 + 50 = 250 credits
#
# Founding attorneys (first 10): +5 additional on top of the above.

SIGNUP_BONUS_CREDITS: int = 3   # Free credits on registration — no card required

FIRST_MONTH_BONUS: dict[str, int] = {
    "associate": 10,   # First month: 30 + 10 = 40 credits
    "partner":   25,   # First month: 75 + 25 = 100 credits
    "sovereign": 50,   # First month: 200 + 50 = 250 credits
}

ROLES: list[str] = ["public", "pending", "approved_attorney", "admin"]


# ── Dynamic pricing ───────────────────────────────────────────────────

def get_credit_cost(opportunity_score: float) -> int:
    """Return credit cost based on opportunity score.

    Phase 0: defined here for future use.
    NOT called from the unlock endpoint in Phase 0 (cost hardcoded to 1).

    85+   → 3 credits (Elite Opportunity)
    70-84 → 2 credits (Verified Lead)
    0-69  → 1 credit  (Standard)
    """
    if opportunity_score >= 85:
        return 3
    if opportunity_score >= 70:
        return 2
    return 1


# ── Tier helpers ──────────────────────────────────────────────────────

def get_monthly_credits(tier: str) -> int:
    """Credits granted per billing cycle for a tier."""
    return TIERS.get(tier, TIERS["associate"])["credits"]


def get_daily_limit(tier: str) -> Optional[int]:
    """Daily API lead view limit. None = unlimited."""
    return TIERS.get(tier, TIERS["associate"])["daily_limit"]


def get_session_limit(tier: str) -> int:
    """Concurrent session limit."""
    return TIERS.get(tier, TIERS["associate"])["sessions"]


def get_rollover_days(tier: str) -> int:
    """Credit rollover window in days for a tier."""
    return ROLLOVER_DAYS.get(tier, 30)


def get_max_bank(tier: str) -> int:
    """Maximum credits that can be banked (carried over) for a tier."""
    monthly = get_monthly_credits(tier)
    multiplier = MAX_BANK_MULTIPLIER.get(tier, 1.5)
    return int(monthly * multiplier)


# ── Stripe price map builder ──────────────────────────────────────────

def build_price_map(mode: str) -> dict[str, dict]:
    """Build Stripe price_id → {tier, monthly_credits, kind} map.

    Reads env vars:
      STRIPE_TEST_PRICE_ASSOCIATE / STRIPE_LIVE_PRICE_ASSOCIATE
      STRIPE_TEST_PRICE_PARTNER   / STRIPE_LIVE_PRICE_PARTNER
      STRIPE_TEST_PRICE_SOVEREIGN / STRIPE_LIVE_PRICE_SOVEREIGN
      STRIPE_TEST_PRICE_ASSOCIATE_ANNUAL / STRIPE_LIVE_PRICE_ASSOCIATE_ANNUAL
      STRIPE_TEST_PRICE_PARTNER_ANNUAL   / STRIPE_LIVE_PRICE_PARTNER_ANNUAL
      STRIPE_TEST_PRICE_SOVEREIGN_ANNUAL / STRIPE_LIVE_PRICE_SOVEREIGN_ANNUAL
      STRIPE_TEST_PRICE_STARTER   / STRIPE_LIVE_PRICE_STARTER
      STRIPE_TEST_PRICE_INVESTIGATION / STRIPE_LIVE_PRICE_INVESTIGATION

    Returns empty dict if no env vars are configured (dev mode).
    """
    prefix = "STRIPE_LIVE_PRICE_" if mode == "live" else "STRIPE_TEST_PRICE_"
    definitions = {
        "ASSOCIATE":        {"tier": "associate", "monthly_credits": get_monthly_credits("associate"), "kind": "subscription"},
        "PARTNER":          {"tier": "partner",   "monthly_credits": get_monthly_credits("partner"),   "kind": "subscription"},
        "SOVEREIGN":        {"tier": "sovereign", "monthly_credits": get_monthly_credits("sovereign"), "kind": "subscription"},
        "ASSOCIATE_ANNUAL": {"tier": "associate", "monthly_credits": get_monthly_credits("associate"), "kind": "subscription"},
        "PARTNER_ANNUAL":   {"tier": "partner",   "monthly_credits": get_monthly_credits("partner"),   "kind": "subscription"},
        "SOVEREIGN_ANNUAL": {"tier": "sovereign", "monthly_credits": get_monthly_credits("sovereign"), "kind": "subscription"},
        "STARTER":          {"tier": "starter",   "monthly_credits": STARTER_PACK["credits"],          "kind": "starter"},
        "INVESTIGATION":    {"tier": "none",      "monthly_credits": INVESTIGATION_PACK["credits"],    "kind": "investigation"},
    }
    price_map: dict[str, dict] = {}
    for name, info in definitions.items():
        price_id = os.environ.get(f"{prefix}{name}", "")
        if price_id and price_id != "price_PLACEHOLDER":
            price_map[price_id] = info
    return price_map
