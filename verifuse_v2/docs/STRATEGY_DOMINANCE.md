# STRATEGY DOMINANCE: Intelligence & Growth Architecture

> Sprint Blueprint — Do NOT merge to main until scoring engine is validated.

---

## 1. Opportunity Score Algorithm

The **Opportunity Score** is a 0-100 composite index that ranks leads by
actionability. It replaces flat sorting (surplus DESC) with a multi-factor
signal that accounts for recency, risk, and market dynamics.

### 1.1 Weighted Factors

| Factor | Weight | Input | Source |
|--------|--------|-------|--------|
| **Surplus Strength** | 30% | `estimated_surplus` vs median | `leads` table |
| **Recency** | 20% | Days since `sale_date` | `leads` table |
| **Distress Signal** | 20% | Lien count / foreclosure type | **STUB** (future scraper) |
| **Equity Ratio** | 15% | Est. equity / market value | **STUB** (future data feed) |
| **Market Velocity** | 15% | Local turnover rate | **STUB** (future analytics) |

### 1.2 Surplus Strength — Median Configuration

The scoring engine supports two median scopes, selectable via `algo_version`:

| algo_version | Median Scope | Behavior |
|-------------|-------------|----------|
| `v1-county` | Per-county | Compares surplus against the median for that county. Rewards outliers within a local market. |
| `v1-state` | Statewide | Single median across all CO leads. Simpler but large-surplus counties always score high. |

**Default:** `v1-county` (more granular, better signal).

### 1.3 Factor Formulas

**Surplus Strength (0-100):**
```
ratio = surplus / median_surplus
score = min(100, ratio * 50)
```
Surplus at 2x median = 100. Below median = proportionally lower.

**Recency (0-100):**
```
days = (today - sale_date).days
score = max(0, 100 - (days / 3.65))
```
0 days = 100. 365 days = 0. Older than 1 year = 0.

**Distress Signal (0-100) [STUB]:**
```
score = 50  # Neutral until lien data is available
```
When lien count data is ingested:
- 0 liens = 30
- 1-2 liens = 60
- 3+ liens = 90
- Judicial foreclosure = +10 bonus

**Equity Ratio (0-100) [STUB]:**
```
score = 50  # Neutral until market value data is available
```
When market value data is ingested:
- ratio = estimated_equity / market_value
- score = min(100, ratio * 200)

**Market Velocity (0-100) [STUB]:**
```
score = 50  # Neutral until turnover data is available
```
When analytics pipeline is built:
- velocity = county_sales_last_90d / county_total_properties
- score = min(100, velocity * 1000)

### 1.4 Composite Score

```
opportunity_score = (
    surplus_strength * 0.30 +
    recency * 0.20 +
    distress_signal * 0.20 +
    equity_ratio * 0.15 +
    market_velocity * 0.15
)
```

Rounded to nearest integer. Range: 0-100.

---

## 2. Dynamic Pricing Tiers

Replaces the flat 1-credit-per-unlock model with score-based pricing that
aligns cost with signal quality.

| Score Range | Tier | Credit Cost | Label |
|-------------|------|-------------|-------|
| 85-100 | High Confidence | 3 credits | Premium Intel |
| 50-84 | Standard | 2 credits | Verified Lead |
| 0-49 | Speculative | 1 credit | Early Signal |

### 2.1 Implementation Notes

- Pricing tier is computed at unlock time, NOT at display time
- Frontend shows the credit cost on the unlock button: "UNLOCK (3 CREDITS)"
- Score + tier are logged in `pipeline_events` for audit trail
- Admin bypass: admins always pay 0 credits (existing behavior preserved)
- Transition plan: existing 1-credit unlocks remain honored. New pricing
  applies only after `algo_version >= v1` is activated

### 2.2 Revenue Impact Model

Assuming current unlock distribution:
- 40% of unlocks are high-confidence (3x revenue on those)
- 40% standard (2x revenue)
- 20% speculative (1x, same as today)

Weighted average: 2.2 credits/unlock vs 1.0 today = **2.2x revenue per unlock**.

---

## 3. Growth Loops

### 3.1 Referral Program: Give 5, Get 5

| Event | Referrer Gets | Referee Gets |
|-------|-------------|-------------|
| Referee registers | 0 | 5 credits (standard Recon) |
| Referee completes first unlock | 5 bonus credits | 0 |

**Mechanics:**
- Referral link: `https://verifuse.tech/register?ref={referrer_user_id}`
- `referrals` table tracks status: `pending` -> `converted` (registered) -> `paid` (first unlock)
- Credits are atomic: debit/credit in same transaction as status update
- Cap: 50 referral credits per month per user (anti-abuse)
- Referral links expire after 30 days

### 3.2 Streak Bonuses

| Streak | Bonus |
|--------|-------|
| 2 consecutive weeks with 1+ unlock | 5% credit bonus on next purchase |
| 4 consecutive weeks | 10% bonus |
| 8 consecutive weeks | 15% bonus + "Power User" badge |

**Implementation:** Computed at billing/checkout time by counting distinct
weeks with unlocks in `lead_unlocks`. No separate table needed.

---

## 4. Data Moat Strategy

The scoring engine creates a proprietary data layer that competitors cannot
replicate:

1. **Score history** in `lead_scores` creates temporal signal (trending leads)
2. **Unlock patterns** in `lead_unlocks` reveal which leads attorneys actually
   act on (implicit quality signal)
3. **Referral network** in `referrals` creates viral growth with zero CAC
4. **County-specific SEO pages** capture organic search intent ("surplus funds
   [county name]")

---

## 5. Schema Dependencies

| Table | Status | Notes |
|-------|--------|-------|
| `lead_scores` | NEW | Stores computed scores per lead |
| `referrals` | NEW | Tracks referral chain and payout status |
| `leads` | EXISTING | Source of truth for scoring inputs |
| `users` | EXISTING | FK target for referrals. PK = `user_id` |
| `lead_unlocks` | EXISTING | Used for streak calculation |

Migration file: `verifuse_v2/data/schema_intelligence.sql` (review only, not auto-executed).

---

## 6. Risk Register

| Risk | Mitigation |
|------|-----------|
| Stub factors dilute score quality | Neutral (50) stubs don't bias ranking — real factors still dominate |
| Dynamic pricing deters low-value unlocks | 1-credit speculative tier preserves accessibility |
| Referral abuse (self-referral) | Email domain check + IP dedup + monthly cap |
| Score gaming | Scores are server-computed, never client-supplied |
| Migration breaks production | Schema file is review-only. No auto-execution |
