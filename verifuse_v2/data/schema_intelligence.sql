-- VeriFuse Intelligence Schema v2 (Dual-Track Architecture)
-- Sprint: Intelligence Architecture v2
-- Status: REVIEW ONLY — Do NOT execute until scoring engine is validated.
--
-- Prerequisites:
--   - `leads` table exists with `id TEXT PRIMARY KEY`
--   - `users` table exists with `user_id TEXT PRIMARY KEY`

-- ── Lead Scores (The Proprietary Index) ─────────────────────────────
-- Three independent scores form the VeriFuse Intelligence Index.
-- Re-scored periodically by OpportunityEngine (cron or on-demand).
-- algo_version tracks which formula produced the score for auditability.

CREATE TABLE IF NOT EXISTS lead_scores (
    lead_id            TEXT PRIMARY KEY,
    opportunity_score  INTEGER NOT NULL DEFAULT 0,  -- 0-100: value potential (surplus, equity, distress)
    confidence_score   INTEGER NOT NULL DEFAULT 0,  -- 0-100: data quality + freshness
    velocity_score     INTEGER NOT NULL DEFAULT 0,  -- 0-100: market heat (turnover, unlock frequency)
    pricing_tier       INTEGER NOT NULL DEFAULT 1,  -- 1, 2, or 3 credits (derived from opportunity_score)
    algo_version       TEXT NOT NULL DEFAULT 'v2-county',
    last_scored_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(lead_id) REFERENCES leads(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_lead_scores_opportunity
    ON lead_scores(opportunity_score DESC);

CREATE INDEX IF NOT EXISTS idx_lead_scores_confidence
    ON lead_scores(confidence_score DESC);

CREATE INDEX IF NOT EXISTS idx_lead_scores_velocity
    ON lead_scores(velocity_score DESC);

CREATE INDEX IF NOT EXISTS idx_lead_scores_tier
    ON lead_scores(pricing_tier);


-- ── Lead Outcomes (The Feedback Loop / Flywheel) ────────────────────
-- Users report what happened after unlocking a lead.
-- This data feeds back into scoring weights over time (ML loop).
-- Status flow: contacted -> contract_signed -> profit_realized
--              contacted -> dead_lead (no conversion)

CREATE TABLE IF NOT EXISTS lead_outcomes (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    lead_id         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'contacted'
                    CHECK(status IN ('contacted', 'contract_signed', 'dead_lead', 'profit_realized')),
    profit_amount   REAL,           -- NULL until profit_realized
    notes           TEXT,           -- Free-form user notes
    reported_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY(lead_id) REFERENCES leads(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_lead_outcomes_user
    ON lead_outcomes(user_id);

CREATE INDEX IF NOT EXISTS idx_lead_outcomes_lead
    ON lead_outcomes(lead_id);

CREATE INDEX IF NOT EXISTS idx_lead_outcomes_status
    ON lead_outcomes(status);


-- ── Subscriptions (Recurring Revenue State) ─────────────────────────
-- Mirrors Stripe subscription state for fast local lookups.
-- Updated by webhook handler on subscription events.
-- Tiers: scout ($49/25cr), operator ($149/100cr), sovereign ($499/500cr).

CREATE TABLE IF NOT EXISTS subscriptions (
    user_id             TEXT PRIMARY KEY,
    stripe_sub_id       TEXT,
    tier                TEXT NOT NULL DEFAULT 'scout'
                        CHECK(tier IN ('scout', 'operator', 'sovereign')),
    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK(status IN ('active', 'past_due', 'cancelled', 'trialing')),
    current_period_end  DATETIME,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_status
    ON subscriptions(status);

CREATE INDEX IF NOT EXISTS idx_subscriptions_tier
    ON subscriptions(tier);
