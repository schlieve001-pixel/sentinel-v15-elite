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
    "scout": {
        "monthly_price_cents": 4900,   # $49/month
        "credits": 25,
        "daily_limit": 100,
        "sessions": 1,
        "label": "Scout",
    },
    "operator": {
        "monthly_price_cents": 14900,  # $149/month
        "credits": 100,
        "daily_limit": 500,
        "sessions": 2,
        "label": "Operator",
    },
    "sovereign": {
        "monthly_price_cents": 49900,  # $499/month
        "credits": 500,
        "daily_limit": None,           # Unlimited
        "sessions": 5,
        "label": "Sovereign",
    },
}

STARTER_PACK: dict = {
    "credits": 10,
    "price_cents": 1900,    # $19.00
    "expiry_days": 30,
}

FOUNDERS_MAX_SLOTS: int = 100

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
    return TIERS.get(tier, TIERS["scout"])["credits"]


def get_daily_limit(tier: str) -> Optional[int]:
    """Daily API lead view limit. None = unlimited."""
    return TIERS.get(tier, TIERS["scout"])["daily_limit"]


def get_session_limit(tier: str) -> int:
    """Concurrent session limit."""
    return TIERS.get(tier, TIERS["scout"])["sessions"]


# ── Stripe price map builder ──────────────────────────────────────────

def build_price_map(mode: str) -> dict[str, dict]:
    """Build Stripe price_id → {tier, monthly_credits, kind} map.

    Reads env vars:
      STRIPE_TEST_PRICE_SCOUT / STRIPE_LIVE_PRICE_SCOUT
      STRIPE_TEST_PRICE_OPERATOR / STRIPE_LIVE_PRICE_OPERATOR
      STRIPE_TEST_PRICE_SOVEREIGN / STRIPE_LIVE_PRICE_SOVEREIGN
      STRIPE_TEST_PRICE_STARTER / STRIPE_LIVE_PRICE_STARTER

    Returns empty dict if no env vars are configured (dev mode).
    """
    prefix = "STRIPE_LIVE_PRICE_" if mode == "live" else "STRIPE_TEST_PRICE_"
    definitions = {
        "SCOUT":     {"tier": "scout",     "monthly_credits": get_monthly_credits("scout"),     "kind": "subscription"},
        "OPERATOR":  {"tier": "operator",  "monthly_credits": get_monthly_credits("operator"),  "kind": "subscription"},
        "SOVEREIGN": {"tier": "sovereign", "monthly_credits": get_monthly_credits("sovereign"), "kind": "subscription"},
        "STARTER":   {"tier": "starter",   "monthly_credits": STARTER_PACK["credits"],          "kind": "starter"},
    }
    price_map: dict[str, dict] = {}
    for name, info in definitions.items():
        price_id = os.environ.get(f"{prefix}{name}", "")
        if price_id and price_id != "price_PLACEHOLDER":
            price_map[price_id] = info
    return price_map
