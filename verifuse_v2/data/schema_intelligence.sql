-- VeriFuse Intelligence & Growth Schema Extension
-- Sprint: Intelligence Architecture
-- Status: REVIEW ONLY — Do NOT execute until scoring engine is validated.
--
-- Prerequisites:
--   - `leads` table exists with `id TEXT PRIMARY KEY`
--   - `users` table exists with `user_id TEXT PRIMARY KEY`

-- ── Lead Scores ─────────────────────────────────────────────────────
-- Stores computed opportunity scores per lead.
-- Re-scored periodically by the scoring engine (cron or on-demand).
-- algo_version tracks which formula produced the score for auditability.

CREATE TABLE IF NOT EXISTS lead_scores (
    lead_id            TEXT PRIMARY KEY,
    opportunity_score  INTEGER NOT NULL DEFAULT 0,  -- 0-100 composite
    surplus_strength   INTEGER NOT NULL DEFAULT 0,  -- 0-100 factor
    recency_score      INTEGER NOT NULL DEFAULT 0,  -- 0-100 factor
    distress_signal    INTEGER NOT NULL DEFAULT 50, -- 0-100 factor (stub: 50)
    equity_ratio       INTEGER NOT NULL DEFAULT 50, -- 0-100 factor (stub: 50)
    market_velocity    INTEGER NOT NULL DEFAULT 50, -- 0-100 factor (stub: 50)
    pricing_tier       INTEGER NOT NULL DEFAULT 1,  -- 1, 2, or 3 credits
    algo_version       TEXT NOT NULL DEFAULT 'v1-county',
    last_scored_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(lead_id) REFERENCES leads(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_lead_scores_opportunity
    ON lead_scores(opportunity_score DESC);

CREATE INDEX IF NOT EXISTS idx_lead_scores_tier
    ON lead_scores(pricing_tier);

-- ── Referrals ───────────────────────────────────────────────────────
-- Tracks referral chain: who referred whom, and payout status.
-- Status flow: pending -> converted (registered) -> paid (first unlock)
-- Credits are awarded atomically when status transitions to 'paid'.

CREATE TABLE IF NOT EXISTS referrals (
    id              TEXT PRIMARY KEY,
    referrer_id     TEXT NOT NULL,
    referee_id      TEXT,           -- NULL until referee registers
    referral_code   TEXT NOT NULL,  -- URL-safe code for referral link
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'converted', 'paid', 'expired')),
    credits_awarded INTEGER NOT NULL DEFAULT 0,  -- credits given to referrer
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    converted_at    DATETIME,       -- when referee registered
    paid_at         DATETIME,       -- when referee completed first unlock
    expires_at      DATETIME,       -- 30 days after creation
    FOREIGN KEY(referrer_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY(referee_id)  REFERENCES users(user_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_referrals_referrer
    ON referrals(referrer_id, status);

CREATE INDEX IF NOT EXISTS idx_referrals_code
    ON referrals(referral_code);

CREATE INDEX IF NOT EXISTS idx_referrals_referee
    ON referrals(referee_id);
