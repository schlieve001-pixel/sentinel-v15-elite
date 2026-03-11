"""
IQS Recorder Stub — Not Yet Implemented

IQS Recorder is used by Pacific Northwest counties.

Target counties (examples):
  - Pierce County, WA
  - Snohomish County, WA
  - Clark County, WA
"""
from __future__ import annotations
from .base_adapter import ScraperAdapter


class IQSRecorderAdapter(ScraperAdapter):
    """IQS Recorder system adapter (STUB — not implemented)."""

    ADAPTER_NAME = "iqsrecorder"
    SCHEMA_VERSION = "0"

    def search_foreclosures(self, county: str, date_range: tuple) -> list[dict]:
        raise NotImplementedError("IQS Recorder adapter not yet implemented. Target: Q4 2026.")

    def get_sale_details(self, case_id: str) -> dict:
        raise NotImplementedError("IQS Recorder adapter not yet implemented.")

    @property
    def adapter_name(self) -> str:
        return self.ADAPTER_NAME

    @property
    def schema_version(self) -> str:
        return self.SCHEMA_VERSION

    @property
    def supported_states(self) -> list[str]:
        return ["WA", "OR", "ID"]
