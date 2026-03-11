"""
RealAuction.com Stub — Not Yet Implemented

RealAuction.com is an online auction platform used by many counties for tax
deed and foreclosure sales. Target URL pattern: https://www.realauction.com/
"""
from __future__ import annotations
from .base_adapter import ScraperAdapter


class RealAuctionAdapter(ScraperAdapter):
    """RealAuction.com online auction adapter (STUB — not implemented)."""

    ADAPTER_NAME = "realauction"
    SCHEMA_VERSION = "0"

    def search_foreclosures(self, county: str, date_range: tuple) -> list[dict]:
        raise NotImplementedError("RealAuction adapter not yet implemented. Target: Q2 2027.")

    def get_sale_details(self, case_id: str) -> dict:
        raise NotImplementedError("RealAuction adapter not yet implemented.")

    @property
    def adapter_name(self) -> str:
        return self.ADAPTER_NAME

    @property
    def schema_version(self) -> str:
        return self.SCHEMA_VERSION

    @property
    def supported_states(self) -> list[str]:
        return ["FL", "NJ", "NY", "PA", "MD"]
