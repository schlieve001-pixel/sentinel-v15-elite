"""
VeriFuse vNEXT — Platform Adapter Protocol
==========================================
Structural protocol for all Playwright-based platform adapters.
GovSoft engine implements this via govsoft_engine.GovSoftEngine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class PlatformAdapter(Protocol):
    """Protocol every platform adapter must satisfy."""

    async def search(
        self, county: str, date_from: str, date_to: str
    ) -> list[dict]:
        """Search for cases in the given date range.

        Returns a list of case dicts with at minimum:
          {county, case_number, asset_id, case_url}
        """
        ...

    async def open_case(self, case_url: str) -> dict:
        """Navigate to a case detail page and capture HTML snapshots.

        Returns raw case data dict extracted from the page.
        """
        ...

    async def list_documents(self, case_data: dict) -> list[dict]:
        """List documents available on the Docs tab for a case.

        Returns list of doc dicts: {filename, doc_type, url}
        """
        ...

    async def download_document(self, doc: dict, dest_dir: Path) -> Path:
        """Download a single document to dest_dir.

        Returns the absolute Path of the saved file.
        Filename on disk is sanitized; raw filename preserved in doc dict.
        """
        ...
