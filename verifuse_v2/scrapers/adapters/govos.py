"""
GovOS (formerly GovSmart) Stub — Not Yet Implemented

GovOS covers Southeast and Gulf Coast counties.
"""
from __future__ import annotations
from .base_adapter import ScraperAdapter


class GovOSAdapter(ScraperAdapter):
    """GovOS (formerly GovSmart) adapter (STUB — not implemented)."""

    ADAPTER_NAME = "govos"
    SCHEMA_VERSION = "0"

    def search_foreclosures(self, county: str, date_range: tuple) -> list[dict]:
        raise NotImplementedError("GovOS adapter not yet implemented. Target: Q1 2027.")

    def get_sale_details(self, case_id: str) -> dict:
        raise NotImplementedError("GovOS adapter not yet implemented.")

    @property
    def adapter_name(self) -> str:
        return self.ADAPTER_NAME

    @property
    def schema_version(self) -> str:
        return self.SCHEMA_VERSION

    @property
    def supported_states(self) -> list[str]:
        return ["FL", "LA", "GA", "AL", "TX"]
