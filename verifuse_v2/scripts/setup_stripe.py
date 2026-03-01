"""
VeriFuse V2 — Stripe Product & Webhook Setup
=============================================
Creates Stripe products/prices for the canonical VeriFuse pricing tiers
and registers the webhook endpoint.

Products created:
  Associate      $149/mo — 30 credits
  Partner        $399/mo — 100 credits
  Sovereign      $899/mo — 250 credits
  Starter Pack   $49 one-time — 10 credits
  Investigation  $99 one-time — 25 credits
  Filing Pack    $49 one-time — 3 credits
  Premium Dossier $79 one-time — 5 credits

Usage:
    STRIPE_SECRET_KEY=sk_test_... python3 verifuse_v2/scripts/setup_stripe.py [--create] [--webhook]

After running --create, set the printed env vars in /etc/verifuse/verifuse.env
and restart the API service.
"""

from __future__ import annotations

import os
import sys

SUBSCRIPTION_PRODUCTS = [
    {
        "name": "VeriFuse Associate",
        "description": "30 credits/month. Foreclosure surplus, all grades. 1 concurrent session.",
        "price_cents": 14900,
        "tier": "associate",
        "credits": 30,
        "env_key": "ASSOCIATE",
        "recurring": True,
    },
    {
        "name": "VeriFuse Partner",
        "description": "100 credits/month. All surplus streams, bulk CSV export. 2 sessions.",
        "price_cents": 39900,
        "tier": "partner",
        "credits": 100,
        "env_key": "PARTNER",
        "recurring": True,
    },
    {
        "name": "VeriFuse Sovereign",
        "description": "250 credits/month. All streams + estate cases + API + county reports. 5 sessions.",
        "price_cents": 89900,
        "tier": "sovereign",
        "credits": 250,
        "env_key": "SOVEREIGN",
        "recurring": True,
    },
]

ONE_TIME_PRODUCTS = [
    {
        "name": "VeriFuse Starter Pack",
        "description": "10 credits, expires in 90 days. No subscription required.",
        "price_cents": 4900,
        "tier": "starter",
        "credits": 10,
        "env_key": "STARTER",
        "recurring": False,
    },
    {
        "name": "VeriFuse Investigation Pack",
        "description": "25 credits, expires in 90 days. No subscription required.",
        "price_cents": 9900,
        "tier": "investigation",
        "credits": 25,
        "env_key": "INVESTIGATION",
        "recurring": False,
    },
    {
        "name": "VeriFuse Filing Pack",
        "description": "Motion template + owner address + lien summary + evidence bundle. Per case.",
        "price_cents": 4900,
        "tier": "filing_pack",
        "credits": 3,
        "env_key": "FILING_PACK",
        "recurring": False,
    },
    {
        "name": "VeriFuse Premium Dossier",
        "description": "Filing Pack + heir notification letter template. Per case.",
        "price_cents": 7900,
        "tier": "premium_dossier",
        "credits": 5,
        "env_key": "PREMIUM_DOSSIER",
        "recurring": False,
    },
]

WEBHOOK_URL = os.getenv("VERIFUSE_BASE_URL", "https://verifuse.tech") + "/api/webhook"
WEBHOOK_EVENTS = [
    "checkout.session.completed",
    "invoice.payment_succeeded",
    "invoice.payment_failed",
    "customer.subscription.deleted",
    "customer.subscription.updated",
]


def print_instructions():
    print("=" * 70)
    print("  VERIFUSE STRIPE SETUP INSTRUCTIONS")
    print("=" * 70)
    print()
    print("Subscription tiers:")
    for p in SUBSCRIPTION_PRODUCTS:
        print(f"  {p['name']:30s} ${p['price_cents']/100:.2f}/month — {p['credits']} credits")
    print()
    print("One-time products:")
    for p in ONE_TIME_PRODUCTS:
        print(f"  {p['name']:30s} ${p['price_cents']/100:.2f} one-time — {p['credits']} credits")
    print()
    print("Usage:")
    print("  STRIPE_SECRET_KEY=sk_test_... python3 verifuse_v2/scripts/setup_stripe.py --create")
    print("  STRIPE_SECRET_KEY=sk_test_... python3 verifuse_v2/scripts/setup_stripe.py --webhook")
    print()
    print("Webhook endpoint will be registered at:")
    print(f"  {WEBHOOK_URL}")
    print()
    print("=" * 70)


def create_products(stripe) -> dict[str, str]:
    """Create all Stripe products and prices. Returns {env_key: price_id} map."""
    price_ids: dict[str, str] = {}

    print("\n── Subscription Products ──────────────────────────────────────────")
    for p in SUBSCRIPTION_PRODUCTS:
        product = stripe.Product.create(
            name=p["name"],
            description=p["description"],
            metadata={"tier": p["tier"], "credits": str(p["credits"])},
        )
        price = stripe.Price.create(
            product=product.id,
            unit_amount=p["price_cents"],
            currency="usd",
            recurring={"interval": "month"},
            metadata={"tier": p["tier"], "credits": str(p["credits"])},
        )
        price_ids[p["env_key"]] = price.id
        print(f"  {p['name']:30s} → {price.id}")

    print("\n── One-Time Products ──────────────────────────────────────────────")
    for p in ONE_TIME_PRODUCTS:
        product = stripe.Product.create(
            name=p["name"],
            description=p["description"],
            metadata={"tier": p["tier"], "credits": str(p["credits"])},
        )
        price = stripe.Price.create(
            product=product.id,
            unit_amount=p["price_cents"],
            currency="usd",
            metadata={"tier": p["tier"], "credits": str(p["credits"])},
        )
        price_ids[p["env_key"]] = price.id
        print(f"  {p['name']:30s} → {price.id}")

    return price_ids


def register_webhook(stripe) -> str:
    """Register the webhook endpoint. Returns the webhook secret."""
    print(f"\n── Registering Webhook ────────────────────────────────────────────")
    print(f"  URL: {WEBHOOK_URL}")
    endpoint = stripe.WebhookEndpoint.create(
        url=WEBHOOK_URL,
        enabled_events=WEBHOOK_EVENTS,
        description="VeriFuse subscription lifecycle webhook",
    )
    secret = endpoint.secret
    print(f"  Endpoint ID: {endpoint.id}")
    print(f"  Secret:      {secret}")
    return secret


def print_env_block(mode: str, price_ids: dict[str, str], webhook_secret: str | None = None):
    prefix = "STRIPE_TEST_PRICE_" if mode == "test" else "STRIPE_LIVE_PRICE_"
    print("\n── Append to /etc/verifuse/verifuse.env ───────────────────────────")
    print(f"STRIPE_MODE={mode}")
    if webhook_secret:
        print(f"STRIPE_{'TEST' if mode == 'test' else 'LIVE'}_WEBHOOK_SECRET={webhook_secret}")
    for key, price_id in price_ids.items():
        print(f"{prefix}{key}={price_id}")
    print()
    print("Then restart the API:")
    print("  sudo systemctl restart verifuse-api")


if __name__ == "__main__":
    try:
        import stripe as _stripe
    except ImportError:
        print("FATAL: stripe package not installed. Run: pip install stripe")
        sys.exit(1)

    secret_key = os.environ.get("STRIPE_SECRET_KEY")
    if not secret_key and ("--create" in sys.argv or "--webhook" in sys.argv):
        print("FATAL: STRIPE_SECRET_KEY not set")
        sys.exit(1)

    if secret_key:
        _stripe.api_key = secret_key

    mode = "test" if (secret_key or "").startswith("sk_test_") else "live"

    if "--create" not in sys.argv and "--webhook" not in sys.argv:
        print_instructions()
        sys.exit(0)

    price_ids: dict[str, str] = {}
    webhook_secret: str | None = None

    if "--create" in sys.argv:
        price_ids = create_products(_stripe)

    if "--webhook" in sys.argv:
        webhook_secret = register_webhook(_stripe)

    if price_ids or webhook_secret:
        print_env_block(mode, price_ids, webhook_secret)
