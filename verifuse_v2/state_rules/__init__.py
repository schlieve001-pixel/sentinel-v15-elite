"""
verifuse_v2.state_rules — National scaling scaffold (Phase 2)

Each state module defines a StateSurplusRule subclass with:
  - statute_window_days: int
  - fee_cap_pct: float
  - triggering_event: str
  - requires_court_filing: bool
  - holder_entity: str

Colorado is operational. Other states are stubs for future expansion.
"""
from verifuse_v2.state_rules.colorado import ColoradoSurplusRule

__all__ = ["ColoradoSurplusRule"]
