"""
VeriFuse Opportunity Scoring Engine

Computes a 0-100 opportunity score for each lead based on weighted factors.
Separates business logic from API logic — the API calls this module, never
the other way around.

Algo versions:
  v1-county  — Surplus Strength uses per-county median (default)
  v1-state   — Surplus Strength uses statewide median

Stub factors (distress_signal, equity_ratio, market_velocity) return 50
(neutral) until upstream data sources are integrated.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from typing import Optional


class OpportunityEngine:
    """Compute opportunity scores for leads.

    Usage:
        engine = OpportunityEngine(db_path, algo_version="v1-county")
        engine.load_medians()  # pre-compute medians once
        score = engine.calculate_score(lead_row)
        tier = engine.get_pricing_tier(score)
    """

    # Factor weights (must sum to 1.0)
    WEIGHTS = {
        "surplus_strength": 0.30,
        "recency": 0.20,
        "distress_signal": 0.20,
        "equity_ratio": 0.15,
        "market_velocity": 0.15,
    }

    # Pricing tier thresholds
    TIER_HIGH = 85      # score >= 85 → 3 credits
    TIER_STANDARD = 50  # score >= 50 → 2 credits
    # score < 50 → 1 credit

    def __init__(self, db_path: str, algo_version: str = "v1-county"):
        self.db_path = db_path
        self.algo_version = algo_version
        self._county_medians: dict[str, float] = {}
        self._state_median: float = 0.0

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def load_medians(self) -> None:
        """Pre-compute surplus medians from the leads table.

        Call this once before scoring a batch. For single-lead scoring,
        this is called automatically if medians are not loaded.
        """
        conn = self._get_conn()
        try:
            # Statewide median
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
                    "  WHERE county = ? AND COALESCE(estimated_surplus, surplus_amount, 0) > 100"
                    ")",
                    [county, county],
                ).fetchone()
                self._county_medians[county] = float(m_row["s"]) if m_row else 1.0
        finally:
            conn.close()

    # ── Individual Factor Methods ────────────────────────────────────

    def _surplus_strength(self, lead: dict) -> int:
        """0-100. Compare surplus against median. 2x median = 100."""
        surplus = _safe_float(lead.get("estimated_surplus")) or _safe_float(
            lead.get("surplus_amount")
        ) or 0.0
        if surplus <= 0:
            return 0

        # Select median based on algo_version
        if self.algo_version == "v1-state":
            median = self._state_median
        else:
            county = lead.get("county") or ""
            median = self._county_medians.get(county, self._state_median)

        if median <= 0:
            median = 1.0  # avoid division by zero

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
        """0-100. STUB: returns 50 (neutral) until lien data is available.

        Future implementation:
          0 liens = 30, 1-2 liens = 60, 3+ liens = 90
          Judicial foreclosure = +10 bonus
        """
        # When lien_count column exists:
        # lien_count = lead.get("lien_count")
        # if lien_count is not None:
        #     if lien_count >= 3: return 90
        #     if lien_count >= 1: return 60
        #     return 30
        return 50

    def _equity_ratio(self, lead: dict) -> int:
        """0-100. STUB: returns 50 (neutral) until market value data available.

        Future implementation:
          ratio = estimated_equity / market_value
          score = min(100, ratio * 200)
        """
        # When market_value column exists:
        # market_value = _safe_float(lead.get("market_value"))
        # equity = _safe_float(lead.get("estimated_equity"))
        # if market_value and equity and market_value > 0:
        #     ratio = equity / market_value
        #     return min(100, int(ratio * 200))
        return 50

    def _market_velocity(self, lead: dict) -> int:
        """0-100. STUB: returns 50 (neutral) until turnover data available.

        Future implementation:
          velocity = county_sales_last_90d / county_total_properties
          score = min(100, velocity * 1000)
        """
        return 50

    # ── Composite Score ──────────────────────────────────────────────

    def calculate_score(self, lead: dict) -> int:
        """Compute the weighted opportunity score (0-100).

        Auto-loads medians if not already loaded.
        """
        if not self._state_median:
            self.load_medians()

        factors = {
            "surplus_strength": self._surplus_strength(lead),
            "recency": self._recency(lead),
            "distress_signal": self._distress_signal(lead),
            "equity_ratio": self._equity_ratio(lead),
            "market_velocity": self._market_velocity(lead),
        }

        score = sum(
            factors[k] * self.WEIGHTS[k] for k in self.WEIGHTS
        )
        return min(100, max(0, round(score)))

    def calculate_score_detailed(self, lead: dict) -> dict:
        """Like calculate_score but returns all factor breakdowns.

        Returns:
            {
                "opportunity_score": int,
                "surplus_strength": int,
                "recency_score": int,
                "distress_signal": int,
                "equity_ratio": int,
                "market_velocity": int,
                "pricing_tier": int,
                "algo_version": str,
            }
        """
        if not self._state_median:
            self.load_medians()

        ss = self._surplus_strength(lead)
        rc = self._recency(lead)
        ds = self._distress_signal(lead)
        er = self._equity_ratio(lead)
        mv = self._market_velocity(lead)

        score = min(100, max(0, round(
            ss * self.WEIGHTS["surplus_strength"]
            + rc * self.WEIGHTS["recency"]
            + ds * self.WEIGHTS["distress_signal"]
            + er * self.WEIGHTS["equity_ratio"]
            + mv * self.WEIGHTS["market_velocity"]
        )))

        return {
            "opportunity_score": score,
            "surplus_strength": ss,
            "recency_score": rc,
            "distress_signal": ds,
            "equity_ratio": er,
            "market_velocity": mv,
            "pricing_tier": self.get_pricing_tier(score),
            "algo_version": self.algo_version,
        }

    # ── Pricing ──────────────────────────────────────────────────────

    @classmethod
    def get_pricing_tier(cls, score: int) -> int:
        """Return credit cost based on opportunity score.

        85-100 → 3 credits (High Confidence)
        50-84  → 2 credits (Standard)
        0-49   → 1 credit  (Speculative)
        """
        if score >= cls.TIER_HIGH:
            return 3
        if score >= cls.TIER_STANDARD:
            return 2
        return 1


# ── Utility ──────────────────────────────────────────────────────────

def _safe_float(val) -> Optional[float]:
    """Safely convert to float, returning None for NULL/invalid."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
