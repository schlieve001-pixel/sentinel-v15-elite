"""
StateSurplusRule — Abstract base class for state-specific surplus recovery rules.

All state modules MUST subclass this and implement all abstract properties.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class StateSurplusRule(ABC):
    """Abstract base for state surplus recovery rules.

    Subclass this for each state VeriFuse expands to.
    """

    @property
    @abstractmethod
    def state_code(self) -> str:
        """Two-letter state abbreviation (e.g., 'CO', 'AZ')."""
        ...

    @property
    @abstractmethod
    def statute_window_days(self) -> int:
        """Number of days from triggering event within which claims must be filed."""
        ...

    @property
    @abstractmethod
    def fee_cap_pct(self) -> float:
        """Attorney fee cap as a decimal (e.g., 0.10 = 10%)."""
        ...

    @property
    @abstractmethod
    def triggering_event(self) -> str:
        """What starts the claim window (e.g., 'trustee_sale', 'tax_deed_issuance')."""
        ...

    @property
    @abstractmethod
    def requires_court_filing(self) -> bool:
        """True if a court motion is required (vs. administrative claim)."""
        ...

    @property
    @abstractmethod
    def holder_entity(self) -> str:
        """Who holds the surplus funds (e.g., 'Public Trustee', 'County Treasurer')."""
        ...

    def is_claim_active(self, triggering_date_str: str, today_str: str) -> bool:
        """Return True if claim window is still open."""
        from datetime import date
        try:
            trigger = date.fromisoformat(triggering_date_str[:10])
            today = date.fromisoformat(today_str[:10])
            return (today - trigger).days <= self.statute_window_days
        except (ValueError, TypeError):
            return False  # Fail-closed on parse error

    def deadline_from_trigger(self, triggering_date_str: str) -> str | None:
        """Return ISO date string of claim deadline."""
        from datetime import date, timedelta
        try:
            trigger = date.fromisoformat(triggering_date_str[:10])
            deadline = trigger + timedelta(days=self.statute_window_days)
            return deadline.isoformat()
        except (ValueError, TypeError):
            return None
