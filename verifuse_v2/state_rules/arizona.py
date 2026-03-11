"""
Arizona surplus recovery rules — STUB (Phase 2 expansion target).

Legal basis:
  - ARS § 33-812: Foreclosure overbid recovery
  - 3-year claim window from trustee sale
  - No attorney fee cap statute confirmed (TBD)

STATUS: Stub only — not yet operational. Do not use in production.
"""
from __future__ import annotations
from verifuse_v2.state_rules.base import StateSurplusRule


class ArizonaSurplusRule(StateSurplusRule):
    """Arizona foreclosure surplus recovery — STUB (not yet operational)."""

    @property
    def state_code(self) -> str:
        return "AZ"

    @property
    def statute_window_days(self) -> int:
        # ARS § 33-812: 3-year window from trustee sale
        return 1095

    @property
    def fee_cap_pct(self) -> float:
        # TBD — no confirmed fee cap statute as of March 2026
        return 0.0  # Unknown — 0.0 means no cap applied

    @property
    def triggering_event(self) -> str:
        return "trustee_sale"

    @property
    def requires_court_filing(self) -> bool:
        # ARS § 33-812: Administrative claim to trustee (not always court)
        return False

    @property
    def holder_entity(self) -> str:
        return "County Treasurer"
