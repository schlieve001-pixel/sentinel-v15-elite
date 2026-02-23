# DUAL-TRACK STRATEGY: Cash Now + Moat Later

> Architecture Bible for VeriFuse Intelligence Platform.
> Sprint: Intelligence Architecture v2.
> Status: Blueprint — do NOT merge until scoring engine is validated.

---

## Track 1: Revenue Acceleration (Cash Now)

### 1.1 Dynamic Pricing

Credit cost scales with opportunity quality. Higher-scoring leads
cost more because they convert better.

| Score Range | Tier Label | Credit Cost | Signal |
|-------------|-----------|-------------|--------|
| 85-100 | Elite Opportunity | 3 credits | High surplus, fresh data, strong market signal |
| 70-84 | Verified Lead | 2 credits | Solid data, moderate confidence |
| 0-69 | Standard | 1 credit | Early signal, lower confidence or older data |

**Implementation:** `OpportunityEngine.get_credit_cost(score)` returns 1, 2, or 3.
Cost is computed at unlock time. Frontend displays cost on the unlock button.

### 1.2 Subscription Tiers

Aggressive per-credit pricing that rewards volume. Founding member rates.

| Tier | Monthly | Credits | Per Credit | Daily API | Sessions |
|------|---------|---------|-----------|-----------|----------|
| **Scout** | $49 | 25 | $1.96 | 100 | 1 |
| **Operator** | $149 | 100 | $1.49 | 500 | 2 |
| **Sovereign** | $499 | 500 | $0.99 | Unlimited | 5 |

**Operator is "Most Popular"** — best value inflection point.

**Risk Reduction (conversion drivers):**
- Cancel anytime — no contract
- Unused credits roll over 30 days
- Founding member rates locked in

**Urgency (no deception):**
- "Founding member rates" — implies future price increase
- "First 100 subscribers" — real scarcity
- NO fake countdown timers

### 1.3 Revenue Model

| Metric | Current (flat 1cr) | Dynamic Pricing |
|--------|-------------------|-----------------|
| Avg credits/unlock | 1.0 | ~1.8 (weighted) |
| Operator revenue/user | $149 → 100 unlocks | $149 → 55-100 unlocks |
| Revenue per unlock | $1.49 | $2.68 |
| Gross margin lift | Baseline | **+80%** |

---

## Track 2: The Data Moat (Moat Later)

### 2.1 The 3-Score System

Every lead gets three independent scores. Together they form the
**VeriFuse Intelligence Index** — proprietary, defensible, impossible
for competitors to replicate without our data flywheel.

| Score | Measures | Range | Key Inputs |
|-------|----------|-------|------------|
| **Opportunity** | Value potential | 0-100 | Surplus vs median, equity ratio, distress signals |
| **Confidence** | Data quality + freshness | 0-100 | Source count, data age, verification status |
| **Velocity** | Market heat | 0-100 | County turnover, days-on-market, recent unlocks |

**Composite display:** Leads show all three scores. Sort/filter by any dimension.

### 2.2 The Flywheel

```
User Unlocks Lead
       |
       v
Outcome Reporting ("contacted", "contract_signed", "profit_realized")
       |
       v
Better Scoring Weights (ML feedback loop)
       |
       v
Higher Trust in Scores
       |
       v
Higher Willingness to Pay (dynamic pricing justified)
       |
       v
More Users → More Unlocks → Loop continues
```

The `lead_outcomes` table captures this feedback. Every reported outcome
improves the scoring model. This is the data moat — the more users engage,
the better the scores become, the harder it is for competitors to match.

### 2.3 Freshness Decay

Data degrades over time. The scoring engine applies a freshness multiplier:

```
days_old = (today - last_verified).days
decay = max(0.0, 1.0 - (days_old / 365))
adjusted_score = raw_score * decay
```

- 0 days old → 1.0x (full score)
- 180 days old → 0.5x (half score)
- 365+ days old → 0.0x (worthless)

This creates urgency: leads lose value over time, incentivizing faster unlocks.

---

## Schema Dependencies

| Table | Status | Purpose |
|-------|--------|---------|
| `lead_scores` | NEW | 3-score index + pricing tier + algo version |
| `lead_outcomes` | NEW | User-reported outcomes (the flywheel data) |
| `subscriptions` | NEW | Stripe subscription state (recurring revenue) |
| `leads` | EXISTING | Source of truth for scoring inputs |
| `users` | EXISTING | FK target (PK = `user_id`) |
| `lead_unlocks` | EXISTING | Velocity signal (unlock frequency) |

Migration: `verifuse_v2/data/schema_intelligence.sql` — review only.

---

## Scoring Engine Architecture

| Method | Purpose |
|--------|---------|
| `calculate_composite_score(lead)` | Returns `{opportunity, confidence, velocity}` |
| `get_credit_cost(score)` | 0-69→1, 70-84→2, 85+→3 |
| `get_freshness_decay(last_verified)` | 0.0-1.0 multiplier |

Module: `verifuse_v2/core/scoring.py`

---

## UI Components

| Component | Purpose |
|-----------|---------|
| `PricingTiers.tsx` | Scout/Operator/Sovereign cards with per-credit cost |
| `ScoreBadge.tsx` | Visual badge: Elite (85+) / Verified (70-84) / Standard (0-69) |

---

## Risk Register

| Risk | Mitigation |
|------|-----------|
| Dynamic pricing deters users | 1-credit Standard tier preserves accessibility |
| Score manipulation | Scores are server-computed, never client-supplied |
| Stale data inflates scores | Freshness decay auto-degrades old leads |
| Outcome reporting is sparse | Scores work without outcomes; outcomes are a bonus signal |
| Tier confusion (Scout vs Recon) | Clean rename — no backward compatibility needed on new branch |
| Founding member pricing expectations | Lock rate for 12 months minimum |
