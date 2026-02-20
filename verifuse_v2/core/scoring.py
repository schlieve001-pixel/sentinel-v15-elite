"""
VeriFuse Scoring Engine v2 — Dual-Track Architecture

Three independent scores form the VeriFuse Intelligence Index:
  - Opportunity (0-100): Value potential (surplus, equity, distress)
  - Confidence  (0-100): Data quality + freshness
  - Velocity    (0-100): Market heat (turnover, unlock frequency)

Dynamic pricing: get_credit_cost(opportunity_score)
  0-69  → 1 credit (Standard)
  70-84 → 2 credits (Verified)
  85+   → 3 credits (Elite Opportunity)

Algo versions:
  v2-county — Surplus comparison uses per-county median (default)
  v2-state  — Surplus comparison uses statewide median
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from typing import Optional

from verifuse_v2.server.pricing import get_credit_cost as _pricing_get_credit_cost


class OpportunityEngine:
    """Compute the 3-Score Intelligence Index for leads.

    Usage:
        engine = OpportunityEngine(db_path, algo_version="v2-county")
        engine.load_medians()
        scores = engine.calculate_composite_score(lead_row)
        cost = engine.get_credit_cost(scores["opportunity"])
    """

    # ── Opportunity Score weights ────────────────────────────────────
    # These sum to 1.0 and determine the composite opportunity score.
    OPP_WEIGHTS = {
        "surplus_strength": 0.30,
        "recency": 0.20,
        "distress_signal": 0.20,
        "equity_ratio": 0.15,
        "market_velocity": 0.15,
    }

    # ── Dynamic pricing thresholds (canonical values live in pricing.py) ──
    TIER_ELITE = 85       # score >= 85 → 3 credits
    TIER_VERIFIED = 70    # score >= 70 → 2 credits
    # score < 70 → 1 credit

    def __init__(self, db_path: str, algo_version: str = "v2-county"):
        self.db_path = db_path
        self.algo_version = algo_version
        self._county_medians: dict[str, float] = {}
        self._state_median: float = 0.0
        self._county_unlock_counts: dict[str, int] = {}

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ── Data Loading ────────────────────────────────────────────────

    def load_medians(self) -> None:
        """Pre-compute surplus medians and unlock counts.

        Call once before scoring a batch. Auto-called on first score
        if medians are not loaded.
        """
        conn = self._get_conn()
        try:
            # Statewide median (using SQLite OFFSET trick for median)
            row = conn.execute(
                "SELECT COALESCE(estimated_surplus, surplus_amount, 0) AS s "
                "FROM leads WHERE COALESCE(estimated_surplus, surplus_amount, 0) > 100 "
                "ORDER BY s LIMIT 1 OFFSET ("
                "  SELECT COUNT(*) / 2 FROM leads "
                "  WHERE COALESCE(estimated_surplus, surplus_amount, 0) > 100"
                ")"
            ).fetchone()
            self._state_median = float(row["s"]) if row else 1.0

            # Per-county medians
            counties = conn.execute(
                "SELECT DISTINCT county FROM leads WHERE county IS NOT NULL"
            ).fetchall()
            for c_row in counties:
                county = c_row["county"]
                m_row = conn.execute(
                    "SELECT COALESCE(estimated_surplus, surplus_amount, 0) AS s "
                    "FROM leads "
                    "WHERE county = ? AND COALESCE(estimated_surplus, surplus_amount, 0) > 100 "
                    "ORDER BY s LIMIT 1 OFFSET ("
                    "  SELECT COUNT(*) / 2 FROM leads "
                    "  WHERE county = ? "
                    "  AND COALESCE(estimated_surplus, surplus_amount, 0) > 100"
                    ")",
                    [county, county],
                ).fetchone()
                self._county_medians[county] = float(m_row["s"]) if m_row else 1.0

            # County unlock counts (last 90 days) for velocity
            try:
                unlock_rows = conn.execute(
                    "SELECT l.county, COUNT(*) as cnt "
                    "FROM lead_unlocks u JOIN leads l ON u.lead_id = l.id "
                    "WHERE u.unlocked_at >= date('now', '-90 days') "
                    "GROUP BY l.county"
                ).fetchall()
                self._county_unlock_counts = {r["county"]: r["cnt"] for r in unlock_rows}
            except Exception:
                self._county_unlock_counts = {}
        finally:
            conn.close()

    # ── Opportunity Sub-Factors ─────────────────────────────────────

    def _surplus_strength(self, lead: dict) -> int:
        """0-100. Surplus vs median. 2x median = 100."""
        surplus = _safe_float(lead.get("estimated_surplus")) or _safe_float(
            lead.get("surplus_amount")
        ) or 0.0
        if surplus <= 0:
            return 0

        if self.algo_version == "v2-state":
            median = self._state_median
        else:
            county = lead.get("county") or ""
            median = self._county_medians.get(county, self._state_median)

        if median <= 0:
            median = 1.0
        ratio = surplus / median
        return min(100, int(ratio * 50))

    def _recency(self, lead: dict) -> int:
        """0-100. 0 days since sale = 100. 365+ days = 0."""
        sale_date = lead.get("sale_date")
        if not sale_date:
            return 0
        try:
            sale_dt = date.fromisoformat(str(sale_date)[:10])
            days = (datetime.now(timezone.utc).date() - sale_dt).days
            return max(0, min(100, 100 - int(days / 3.65)))
        except (ValueError, TypeError):
            return 0

    def _distress_signal(self, lead: dict) -> int:
        """0-100. STUB: returns 50 until lien data is available."""
        return 50

    def _equity_ratio(self, lead: dict) -> int:
        """0-100. STUB: returns 50 until market value data is available."""
        return 50

    def _market_velocity_factor(self, lead: dict) -> int:
        """0-100. STUB: returns 50 until turnover data is available."""
        return 50

    # ── Confidence Score ────────────────────────────────────────────

    def _confidence(self, lead: dict) -> int:
        """0-100. Data quality + freshness composite.

        Inputs:
          - data_grade: GOLD=90, SILVER=70, BRONZE=50, else=30
          - confidence_score from DB (0.0-1.0 mapped to 0-100)
          - data age penalty via freshness decay
          - surplus verification (bid > 0 and debt > 0)
        """
        # Grade component (40% of confidence)
        grade = (lead.get("data_grade") or "").upper()
        grade_map = {"GOLD": 90, "SILVER": 70, "BRONZE": 50}
        grade_score = grade_map.get(grade, 30)

        # Raw confidence from DB (30% of confidence)
        raw_conf = _safe_float(lead.get("confidence_score")) or 0.0
        conf_score = min(100, int(raw_conf * 100))

        # Freshness (20% of confidence)
        updated = lead.get("updated_at")
        freshness = int(self.get_freshness_decay(updated) * 100)

        # Verification bonus (10% of confidence)
        bid = _safe_float(lead.get("winning_bid")) or 0.0
        debt = _safe_float(lead.get("total_debt")) or 0.0
        verified = 100 if (bid > 0 and debt > 0) else 0

        score = (
            grade_score * 0.40
            + conf_score * 0.30
            + freshness * 0.20
            + verified * 0.10
        )
        return min(100, max(0, round(score)))

    # ── Velocity Score ──────────────────────────────────────────────

    def _velocity(self, lead: dict) -> int:
        """0-100. Market heat based on county unlock activity.

        Uses unlock counts from the last 90 days as a proxy for market
        interest. Counties with more unlocks = hotter markets.

        When real turnover data is available, this will incorporate
        county sales velocity and days-on-market metrics.
        """
        county = lead.get("county") or ""
        unlock_count = self._county_unlock_counts.get(county, 0)

        # Scale: 0 unlocks = 20 (baseline), 10+ unlocks = 80, 50+ = 100
        if unlock_count >= 50:
            return 100
        if unlock_count >= 10:
            return min(100, 60 + unlock_count)
        return min(100, 20 + unlock_count * 4)

    # ── Composite Score ─────────────────────────────────────────────

    def calculate_composite_score(self, lead: dict) -> dict:
        """Compute the 3-Score Intelligence Index.

        Returns:
            {
                "opportunity": int (0-100),
                "confidence": int (0-100),
                "velocity": int (0-100),
                "pricing_tier": int (1, 2, or 3),
                "credit_cost": int (1, 2, or 3),
                "algo_version": str,
            }
        """
        if not self._state_median:
            self.load_medians()

        # Opportunity = weighted composite of sub-factors
        ss = self._surplus_strength(lead)
        rc = self._recency(lead)
        ds = self._distress_signal(lead)
        er = self._equity_ratio(lead)
        mv = self._market_velocity_factor(lead)

        opportunity = min(100, max(0, round(
            ss * self.OPP_WEIGHTS["surplus_strength"]
            + rc * self.OPP_WEIGHTS["recency"]
            + ds * self.OPP_WEIGHTS["distress_signal"]
            + er * self.OPP_WEIGHTS["equity_ratio"]
            + mv * self.OPP_WEIGHTS["market_velocity"]
        )))

        confidence = self._confidence(lead)
        velocity = self._velocity(lead)
        cost = self.get_credit_cost(opportunity)

        return {
            "opportunity": opportunity,
            "confidence": confidence,
            "velocity": velocity,
            "pricing_tier": cost,
            "credit_cost": cost,
            "algo_version": self.algo_version,
        }

    # ── Dynamic Pricing ─────────────────────────────────────────────

    @classmethod
    def get_credit_cost(cls, score: int) -> int:
        """Return credit cost based on opportunity score.

        Delegates to pricing.get_credit_cost — canonical thresholds live there.

        85+   → 3 credits (Elite Opportunity)
        70-84 → 2 credits (Verified Lead)
        0-69  → 1 credit  (Standard)
        """
        return _pricing_get_credit_cost(score)

    # ── Freshness Decay ─────────────────────────────────────────────

    @staticmethod
    def get_freshness_decay(last_verified) -> float:
        """Return a 0.0-1.0 multiplier based on data age.

        0 days old   → 1.0 (full value)
        180 days old → 0.5 (half value)
        365+ days    → 0.0 (worthless)

        Accepts: ISO date string, datetime, date, or None.
        Returns 0.5 for None/unparseable (conservative default).
        """
        if last_verified is None:
            return 0.5

        try:
            if isinstance(last_verified, datetime):
                dt = last_verified.date() if last_verified.tzinfo else last_verified.date()
            elif isinstance(last_verified, date):
                dt = last_verified
            else:
                dt = date.fromisoformat(str(last_verified)[:10])

            days_old = (datetime.now(timezone.utc).date() - dt).days
            return max(0.0, min(1.0, 1.0 - (days_old / 365.0)))
        except (ValueError, TypeError):
            return 0.5


# ── Utility ──────────────────────────────────────────────────────────

def _safe_float(val) -> Optional[float]:
    """Safely convert to float, returning None for NULL/invalid."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
