"""Base interface for all VeriFuse scraper adapters."""
from __future__ import annotations
from abc import ABC, abstractmethod


class ScraperAdapter(ABC):
    """Abstract base class for all county/state scraper adapters."""

    @abstractmethod
    def search_foreclosures(self, county: str, date_range: tuple) -> list[dict]:
        """Search for foreclosure cases in a county for a date range.

        Returns list of dicts with keys: case_number, case_type, sale_date, status
        """
        ...

    @abstractmethod
    def get_sale_details(self, case_id: str) -> dict:
        """Fetch full sale details for a specific case.

        Returns dict with keys: case_number, winning_bid, total_indebtedness,
        overbid_amount, sale_date, property_address, owner_name
        """
        ...

    @property
    @abstractmethod
    def adapter_name(self) -> str:
        """Unique identifier for this adapter (e.g. 'tyler_eagle')."""
        ...

    @property
    @abstractmethod
    def schema_version(self) -> str:
        """Version of the data schema this adapter produces."""
        ...

    @property
    def supported_states(self) -> list[str]:
        """List of US state abbreviations this adapter covers."""
        return []
