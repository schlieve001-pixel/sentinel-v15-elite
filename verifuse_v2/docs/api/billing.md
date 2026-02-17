# Billing

VeriFuse V2 uses Stripe for subscription management. Users subscribe to a tier, receive monthly credits, and spend credits to unlock lead PII.

---

## Subscription Tiers

| Tier | Price | Credits/Month | Target User | Lead Views/Day | Sessions |
|------|-------|---------------|-------------|----------------|----------|
| **Recon** | $199/mo | 5 | Solo researchers, skip tracers | 50 | 1 |
| **Operator** | $399/mo | 25 | Small law firms, recovery specialists | 200 | 2 |
| **Sovereign** | $699/mo | 100 | Large firms, enterprise operations | 500 | 3 |

### Credit System

- 1 credit = 1 lead unlock (reveals PII: owner name, full address, financial details)
- Credits reset at the start of each billing cycle (Stripe `invoice.paid` webhook)
- Unused credits do not roll over
- Re-unlocking an already-unlocked lead is free (no additional credit charge)
- Admin users have unlimited credits (set to 9999)

### Tier Features

| Feature | Recon | Operator | Sovereign |
|---------|-------|----------|-----------|
| Browse leads (SafeAsset) | Yes | Yes | Yes |
| Unlock ACTIONABLE leads | Yes | Yes | Yes |
| Unlock RESTRICTED leads | No | Yes* | Yes* |
| Text dossier download | Yes | Yes | Yes |
| Word dossier download | Yes | Yes | Yes |
| Rule 7.3 letter generation | No | Yes* | Yes* |
| Case packet download | No | Yes* | Yes* |
| API daily lead views | 50 | 200 | 500 |

*Requires verified attorney status in addition to tier.

---

## Stripe Integration

### Architecture

```
User clicks "Subscribe"
        │
        ▼
POST /api/billing/checkout {tier: "operator"}
        │
        ▼
Server creates Stripe Checkout Session
        │
        ▼
User redirected to Stripe-hosted payment page
        │
        ▼
Payment succeeds → Stripe sends webhook
        │
        ▼
POST /api/billing/webhook (from Stripe)
        │
        ▼
Server updates user tier + credits
```

### Configuration

**Environment Variables:**

```bash
STRIPE_SECRET_KEY=sk_live_...           # Stripe API key
STRIPE_WEBHOOK_SECRET=whsec_...         # Webhook signature verification
STRIPE_PRICE_RECON=price_...            # Recon tier price ID
STRIPE_PRICE_OPERATOR=price_...         # Operator tier price ID
STRIPE_PRICE_SOVEREIGN=price_...        # Sovereign tier price ID
VERIFUSE_BASE_URL=https://verifuse.tech # For checkout success/cancel URLs
```

### Setting Up Stripe Products

Use the setup helper:

```bash
# Print setup instructions
python -m verifuse_v2.scripts.setup_stripe

# Auto-create products via Stripe API
STRIPE_SECRET_KEY=sk_live_... python -m verifuse_v2.scripts.setup_stripe --create
```

**Manual setup via Stripe Dashboard:**

1. Go to https://dashboard.stripe.com/products
2. Create three products:

| Product Name | Price | Billing |
|-------------|-------|---------|
| VeriFuse Recon | $199.00/month | Recurring |
| VeriFuse Operator | $399.00/month | Recurring |
| VeriFuse Sovereign | $699.00/month | Recurring |

3. Copy the `price_xxx` IDs for each product
4. Set the environment variables:
   ```bash
   sudo systemctl edit verifuse-api
   # Add under [Service]:
   Environment="STRIPE_PRICE_RECON=price_YOUR_RECON_ID"
   Environment="STRIPE_PRICE_OPERATOR=price_YOUR_OPERATOR_ID"
   Environment="STRIPE_PRICE_SOVEREIGN=price_YOUR_SOVEREIGN_ID"
   ```
5. Restart: `sudo systemctl restart verifuse-api`

### Webhook Setup

Configure in Stripe Dashboard:

1. Go to https://dashboard.stripe.com/webhooks
2. Add endpoint: `https://verifuse.tech/api/billing/webhook`
3. Select events:
   - `checkout.session.completed`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.paid`
4. Copy the webhook signing secret to `STRIPE_WEBHOOK_SECRET`

### Webhook Event Handling

| Event | Action |
|-------|--------|
| `checkout.session.completed` | Activate subscription: set user tier, refill credits, store `stripe_customer_id` and `stripe_subscription_id` |
| `customer.subscription.updated` | Handle tier change (upgrade/downgrade): map price ID to tier, update credits |
| `customer.subscription.deleted` | Deactivate user: `is_active=0`, `tier='recon'`, `credits_remaining=0` |
| `invoice.paid` | Monthly credit reset: refill credits to tier allocation |

### Webhook Signature Verification

In production, all webhooks are verified using the Stripe signing secret:

```python
event = stripe.Webhook.construct_event(payload, sig, WEBHOOK_SECRET)
```

In dev mode (no `STRIPE_WEBHOOK_SECRET`), events are parsed without verification.

---

## Checkout Flow

### Create Checkout Session

```bash
curl -X POST https://verifuse.tech/api/billing/checkout \
  -H "Authorization: Bearer <jwt_token>" \
  -H "Content-Type: application/json" \
  -d '{"tier": "operator"}'
```

Response:
```json
{"checkout_url": "https://checkout.stripe.com/c/pay/cs_live_..."}
```

The frontend redirects the user to this URL. After payment:
- **Success:** Redirect to `https://verifuse.tech/dashboard?session_id={CHECKOUT_SESSION_ID}`
- **Cancel:** Redirect to `https://verifuse.tech/pricing`

### Direct Tier Upgrade (Admin)

For manual upgrades without Stripe:

```bash
curl -X POST https://verifuse.tech/api/billing/upgrade \
  -H "Authorization: Bearer <jwt_token>" \
  -H "Content-Type: application/json" \
  -d '{"tier": "sovereign"}'
```

This immediately updates the tier and refills credits without going through Stripe. Useful for admin overrides and testing.

---

## Credit Deduction

Credit deduction is atomic to prevent race conditions:

```sql
BEGIN IMMEDIATE;

-- Check if already unlocked (free re-unlock)
SELECT 1 FROM lead_unlocks WHERE user_id = ? AND lead_id = ?;

-- Check credit balance
SELECT credits_remaining FROM users WHERE user_id = ?;

-- Deduct 1 credit
UPDATE users SET credits_remaining = credits_remaining - 1 WHERE user_id = ?;

-- Record the unlock
INSERT INTO lead_unlocks (user_id, lead_id, unlocked_at, ip_address, plan_tier) VALUES (...);

-- Audit trail
INSERT INTO pipeline_events (asset_id, event_type, ...) VALUES (...);

COMMIT;
```

`BEGIN IMMEDIATE` acquires a write lock immediately, preventing another transaction from deducting credits concurrently.

---

## Monitoring Billing

```sql
-- Credit usage by user
SELECT u.email, u.tier, u.credits_remaining,
       COUNT(lu.lead_id) as total_unlocks
FROM users u
LEFT JOIN lead_unlocks lu ON u.user_id = lu.user_id
GROUP BY u.user_id
ORDER BY total_unlocks DESC;

-- Revenue by tier (active subscribers)
SELECT tier, COUNT(*) as subscribers,
       COUNT(*) * CASE tier
           WHEN 'recon' THEN 199
           WHEN 'operator' THEN 399
           WHEN 'sovereign' THEN 699
       END as monthly_revenue
FROM users
WHERE is_active = 1 AND tier != 'recon'
GROUP BY tier;

-- Users at zero credits
SELECT email, tier, credits_remaining, last_login_at
FROM users
WHERE credits_remaining = 0 AND is_active = 1;
```

---

## Anti-Scraping Protections

Each tier has daily API request limits (enforced per user, not per IP):

| Tier | Daily Lead Views | Concurrent Sessions |
|------|-----------------|---------------------|
| Recon | 50 | 1 |
| Operator | 200 | 2 |
| Sovereign | 500 | 3 |

These limits are defined in `verifuse_v2/server/billing.py` (`TIER_DAILY_API_LIMIT` and `TIER_SESSION_LIMIT`).
