"""
VeriFuse V2 — Stripe Product Setup Helper
===========================================
Outputs instructions and helper commands for setting up Stripe products.

Products:
  1. Recon      $199/mo — 5 credits
  2. Operator   $399/mo — 25 credits
  3. Sovereign  $699/mo — 100 credits

Usage:
    python -m verifuse_v2.scripts.setup_stripe
    python -m verifuse_v2.scripts.setup_stripe --create  # Creates products via Stripe API

After creating products, update systemd env vars with the price IDs:
    sudo systemctl edit verifuse-api
    Add:
        Environment="STRIPE_PRICE_RECON=price_xxx"
        Environment="STRIPE_PRICE_OPERATOR=price_xxx"
        Environment="STRIPE_PRICE_SOVEREIGN=price_xxx"
    sudo systemctl restart verifuse-api
"""

import os
import sys

PRODUCTS = [
    {
        "name": "VeriFuse Recon",
        "description": "5 lead unlocks/month. Basic surplus intelligence.",
        "price_cents": 19900,
        "tier": "recon",
        "credits": 5,
    },
    {
        "name": "VeriFuse Operator",
        "description": "25 lead unlocks/month. Full attorney tools + restricted access.",
        "price_cents": 39900,
        "tier": "operator",
        "credits": 25,
    },
    {
        "name": "VeriFuse Sovereign",
        "description": "100 lead unlocks/month. Unlimited attorney tools + priority support.",
        "price_cents": 69900,
        "tier": "sovereign",
        "credits": 100,
    },
]


def print_instructions():
    print("=" * 70)
    print("  VERIFUSE STRIPE SETUP INSTRUCTIONS")
    print("=" * 70)
    print()
    print("STEP 1: Create products in Stripe Dashboard")
    print("  https://dashboard.stripe.com/products")
    print()

    for p in PRODUCTS:
        print(f"  Product: {p['name']}")
        print(f"  Price:   ${p['price_cents']/100:.2f}/month (recurring)")
        print(f"  Credits: {p['credits']} unlocks/month")
        print(f"  Tier:    {p['tier']}")
        print()

    print("STEP 2: Copy the Price IDs (price_xxx) for each product")
    print()
    print("STEP 3: Update systemd environment:")
    print("  sudo systemctl edit verifuse-api")
    print("  Add these lines under [Service]:")
    print('    Environment="STRIPE_PRICE_RECON=price_YOUR_RECON_ID"')
    print('    Environment="STRIPE_PRICE_OPERATOR=price_YOUR_OPERATOR_ID"')
    print('    Environment="STRIPE_PRICE_SOVEREIGN=price_YOUR_SOVEREIGN_ID"')
    print()
    print("STEP 4: Restart the API:")
    print("  sudo systemctl restart verifuse-api")
    print()
    print("STEP 5: Configure webhook endpoint in Stripe:")
    print("  Endpoint URL: https://verifuse.tech/api/billing/webhook")
    print("  Events: checkout.session.completed, customer.subscription.updated")
    print()
    print("=" * 70)


def create_products():
    """Create products via Stripe API (requires STRIPE_SECRET_KEY)."""
    try:
        import stripe
    except ImportError:
        print("FATAL: stripe package not installed. Run: pip install stripe")
        sys.exit(1)

    secret_key = os.environ.get("STRIPE_SECRET_KEY")
    if not secret_key:
        print("FATAL: STRIPE_SECRET_KEY not set")
        sys.exit(1)

    stripe.api_key = secret_key

    print("Creating Stripe products...")
    for p in PRODUCTS:
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
            metadata={"tier": p["tier"]},
        )
        print(f"  {p['name']:25s} → product={product.id} price={price.id}")
        print(f'    Environment="STRIPE_PRICE_{p["tier"].upper()}={price.id}"')

    print("\nDone! Copy the Environment lines above into systemd.")


if __name__ == "__main__":
    if "--create" in sys.argv:
        create_products()
    else:
        print_instructions()
