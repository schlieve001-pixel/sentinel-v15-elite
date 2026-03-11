"""
Colorado surplus recovery rules.

Legal basis:
  - C.R.S. § 38-38-111: Foreclosure overbid — Public Trustee holds 6 months, then transfers
  - C.R.S. § 38-13-1304 (HB25-1224): 10% attorney fee cap, effective June 4, 2025
  - 30-month claim window from Trustee Sale date (6 months restriction + 24 months claim)
"""
from __future__ import annotations
from verifuse_v2.state_rules.base import StateSurplusRule


class ColoradoSurplusRule(StateSurplusRule):
    """Colorado foreclosure surplus recovery — fully operational."""

    @property
    def state_code(self) -> str:
        return "CO"

    @property
    def statute_window_days(self) -> int:
        # C.R.S. § 38-38-111: 6 months restriction + 24 months claim = 30 months total
        return 912  # 30 months ≈ 912 days

    @property
    def fee_cap_pct(self) -> float:
        # HB25-1224, C.R.S. § 38-13-1304: 10% cap effective June 4, 2025
        return 0.10

    @property
    def triggering_event(self) -> str:
        return "trustee_sale"

    @property
    def requires_court_filing(self) -> bool:
        # C.R.S. § 38-38-111: Yes, motion to district court required
        return True

    @property
    def holder_entity(self) -> str:
        return "Public Trustee"

    @property
    def restriction_period_days(self) -> int:
        """6 calendar months — C.R.S. § 38-38-111 forbids contact during this period."""
        return 182  # Approximately 6 months

    @property
    def claim_window_days(self) -> int:
        """24 months from end of restriction period."""
        return 730
