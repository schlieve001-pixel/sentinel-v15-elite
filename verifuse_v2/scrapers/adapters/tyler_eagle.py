"""
Tyler Technologies Eagle Stub — Not Yet Implemented

Tyler Eagle is the most widely deployed county recording system in the US,
covering major TX, IL, GA, and WA counties among others.

Target counties (examples):
  - Dallas County, TX
  - Cook County, IL
  - Fulton County, GA
  - King County, WA

Portal pattern: https://{county}.tylertech.com/eagle/ or
                https://recorder.{county}.gov/eagle/
"""
from __future__ import annotations
from .base_adapter import ScraperAdapter


class TylerEagleAdapter(ScraperAdapter):
    """Tyler Technologies Eagle recording system adapter (STUB — not implemented)."""

    ADAPTER_NAME = "tyler_eagle"
    SCHEMA_VERSION = "0"  # not yet stabilized

    def search_foreclosures(self, county: str, date_range: tuple) -> list[dict]:
        raise NotImplementedError("Tyler Eagle adapter not yet implemented. Target: Q3 2026.")

    def get_sale_details(self, case_id: str) -> dict:
        raise NotImplementedError("Tyler Eagle adapter not yet implemented.")

    @property
    def adapter_name(self) -> str:
        return self.ADAPTER_NAME

    @property
    def schema_version(self) -> str:
        return self.SCHEMA_VERSION

    @property
    def supported_states(self) -> list[str]:
        return ["TX", "IL", "GA", "WA", "OH", "NC"]
