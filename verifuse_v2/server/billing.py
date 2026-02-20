"""
VERIFUSE V2 — Stripe Billing Integration

Manages subscription lifecycle:
  - Checkout session creation
  - Webhook handling (subscription events)
  - Credit reset on billing cycle

Set env vars before use:
  STRIPE_SECRET_KEY=sk_...
  STRIPE_WEBHOOK_SECRET=whsec_...
  VERIFUSE_BASE_URL=https://verifuse.tech
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import stripe
from fastapi import HTTPException, Request

from verifuse_v2.db import database as db
from verifuse_v2.server.pricing import get_monthly_credits, get_daily_limit, get_session_limit

log = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
BASE_URL = os.getenv("VERIFUSE_BASE_URL", "https://verifuse.tech")

# Stripe Price IDs — set via env vars (STRIPE_TEST_PRICE_* / STRIPE_LIVE_PRICE_*)
_stripe_mode = (os.getenv("STRIPE_MODE") or "test").lower()
_price_prefix = "STRIPE_LIVE_PRICE_" if _stripe_mode == "live" else "STRIPE_TEST_PRICE_"

TIER_TO_PRICE: dict[str, str] = {
    "scout": os.getenv(f"{_price_prefix}SCOUT", "") or os.getenv("STRIPE_PRICE_SCOUT", ""),
    "operator": os.getenv(f"{_price_prefix}OPERATOR", "") or os.getenv("STRIPE_PRICE_OPERATOR", ""),
    "sovereign": os.getenv(f"{_price_prefix}SOVEREIGN", "") or os.getenv("STRIPE_PRICE_SOVEREIGN", ""),
}

PRICE_TO_TIER: dict[str, str] = {v: k for k, v in TIER_TO_PRICE.items() if v}


# ── Checkout ─────────────────────────────────────────────────────────

def create_checkout_session(user_id: str, email: str, tier: str) -> str:
    """Create a Stripe Checkout session. Returns the checkout URL.

    The user is redirected to Stripe, pays, and Stripe sends a webhook
    back to /api/webhooks/stripe to activate their subscription.
    """
    price_id = TIER_TO_PRICE.get(tier)
    if not price_id:
        raise HTTPException(
            status_code=400,
            detail=f"No Stripe price configured for tier '{tier}'. Set STRIPE_PRICE_{tier.upper()} env var.",
        )

    if not stripe.api_key:
        raise HTTPException(
            status_code=503,
            detail="Stripe not configured. Set STRIPE_SECRET_KEY env var.",
        )

    session = stripe.checkout.Session.create(
        mode="subscription",
        payment_method_types=["card"],
        customer_email=email,
        metadata={"user_id": user_id, "tier": tier},
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{BASE_URL}/dashboard?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{BASE_URL}/pricing",
    )

    return session.url


# ── Webhook handler ──────────────────────────────────────────────────

async def handle_stripe_webhook(request: Request) -> dict:
    """Process Stripe webhook events.

    Handles:
      - checkout.session.completed → activate subscription
      - customer.subscription.updated → tier change
      - customer.subscription.deleted → deactivate
      - invoice.paid → reset credits monthly
    """
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    if WEBHOOK_SECRET:
        try:
            event = stripe.Webhook.construct_event(payload, sig, WEBHOOK_SECRET)
        except stripe.error.SignatureVerificationError:
            raise HTTPException(status_code=400, detail="Invalid signature.")
    else:
        # Dev mode: parse without verification
        import json
        event = stripe.Event.construct_from(json.loads(payload), stripe.api_key)

    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "checkout.session.completed":
        _handle_checkout_completed(data)
    elif event_type == "customer.subscription.updated":
        _handle_subscription_updated(data)
    elif event_type == "customer.subscription.deleted":
        _handle_subscription_deleted(data)
    elif event_type == "invoice.paid":
        _handle_invoice_paid(data)
    else:
        log.debug("Unhandled Stripe event: %s", event_type)

    return {"status": "ok"}


def _handle_checkout_completed(session: dict) -> None:
    """Activate subscription after successful checkout."""
    user_id = session.get("metadata", {}).get("user_id")
    tier = session.get("metadata", {}).get("tier", "scout")
    customer_id = session.get("customer", "")
    subscription_id = session.get("subscription", "")

    if not user_id:
        log.warning("Checkout completed but no user_id in metadata")
        return

    db.update_user_stripe(user_id, customer_id, subscription_id)
    db.update_user_tier(user_id, tier)
    log.info("Subscription activated: user=%s tier=%s", user_id, tier)


def _handle_subscription_updated(subscription: dict) -> None:
    """Handle tier changes (upgrade/downgrade)."""
    customer_id = subscription.get("customer", "")
    # Find user by stripe_customer_id
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT user_id FROM users WHERE stripe_customer_id = ?",
            [customer_id],
        ).fetchone()
    if not row:
        return

    # Get the new price → tier
    items = subscription.get("items", {}).get("data", [])
    if items:
        price_id = items[0].get("price", {}).get("id", "")
        new_tier = PRICE_TO_TIER.get(price_id)
        if new_tier:
            db.update_user_tier(row["user_id"], new_tier)
            log.info("Subscription updated: user=%s tier=%s", row["user_id"], new_tier)


def _handle_subscription_deleted(subscription: dict) -> None:
    """Deactivate user when subscription is cancelled."""
    customer_id = subscription.get("customer", "")
    with db.get_db() as conn:
        conn.execute(
            "UPDATE users SET is_active = 0, tier = 'scout', credits_remaining = 0, "
            "subscription_status = 'canceled' "
            "WHERE stripe_customer_id = ?",
            [customer_id],
        )
    log.info("Subscription cancelled: customer=%s", customer_id)


def _handle_invoice_paid(invoice: dict) -> None:
    """Reset credits on each billing cycle."""
    customer_id = invoice.get("customer", "")
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT user_id, tier FROM users WHERE stripe_customer_id = ?",
            [customer_id],
        ).fetchone()
    if not row:
        return

    credits = get_monthly_credits(row["tier"])
    with db.get_db() as conn:
        conn.execute(
            "UPDATE users SET credits_remaining = ? WHERE user_id = ?",
            [credits, row["user_id"]],
        )
    log.info("Credits reset: user=%s tier=%s credits=%d", row["user_id"], row["tier"], credits)
