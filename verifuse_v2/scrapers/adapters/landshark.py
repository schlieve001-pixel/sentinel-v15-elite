"""
LandShark Recording System Stub — Not Yet Implemented

LandShark is deployed in Southeast US counties.
"""
from __future__ import annotations
from .base_adapter import ScraperAdapter


class LandSharkAdapter(ScraperAdapter):
    """LandShark recording system adapter (STUB — not implemented)."""

    ADAPTER_NAME = "landshark"
    SCHEMA_VERSION = "0"

    def search_foreclosures(self, county: str, date_range: tuple) -> list[dict]:
        raise NotImplementedError("LandShark adapter not yet implemented. Target: Q4 2026.")

    def get_sale_details(self, case_id: str) -> dict:
        raise NotImplementedError("LandShark adapter not yet implemented.")

    @property
    def adapter_name(self) -> str:
        return self.ADAPTER_NAME

    @property
    def schema_version(self) -> str:
        return self.SCHEMA_VERSION

    @property
    def supported_states(self) -> list[str]:
        return ["AL", "MS", "TN", "AR", "SC"]
