"""
GovEase Platform Adapter
==========================
Covers counties using GovEase portal:
  Teller, Summit, San Miguel

DISABLED BY DEFAULT (Task 0D): GovEase is debt-only portal.
Any output routes directly to leads_quarantine with reason GOVEASE_DEBT_ONLY.

Only operator override can route GovEase data to leads table.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone

from verifuse_v2.scrapers.base_scraper import CountyScraper

log = logging.getLogger(__name__)

DB_PATH = os.environ.get(
    "VERIFUSE_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "verifuse_v2.db"),
)


class GovEaseAdapter(CountyScraper):
    """Adapter for GovEase portal. DISABLED by default — routes to quarantine."""

    platform = "govease"

    def discover_pdfs(self) -> list[str]:
        """GovEase does not provide surplus data PDFs."""
        log.info("[%s] GovEase: DISABLED — debt-only portal, skipping PDF discovery", self.county)
        return []

    def fetch_html_data(self) -> list[dict]:
        """GovEase data routes to quarantine, not leads."""
        log.info("[%s] GovEase: DISABLED — any data would route to quarantine", self.county)
        return []

    def run(self, dry_run: bool = False) -> dict:
        """Override run to quarantine any discovered data."""
        result = {
            "county": self.county,
            "county_code": self.county_code,
            "platform": "govease",
            "pdfs_discovered": 0,
            "pdfs_downloaded": 0,
            "html_records": 0,
            "quarantined": 0,
            "errors": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "skipped": True,
            "reason": "GOVEASE_DEBT_ONLY — disabled by default",
        }

        # Check for operator override
        force_govease = os.environ.get("VERIFUSE_FORCE_GOVEASE", "").lower() in ("1", "true", "yes")
        if not force_govease:
            log.info("[%s] GovEase: SKIPPED (set VERIFUSE_FORCE_GOVEASE=1 to override)", self.county)
            return result

        log.warning("[%s] GovEase: OPERATOR OVERRIDE — processing (data routes to quarantine)", self.county)

        # Even with override, data goes to quarantine
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("PRAGMA journal_mode=WAL")
            now = datetime.now(timezone.utc).isoformat()

            conn.execute("""
                INSERT INTO pipeline_events
                (asset_id, event_type, old_value, new_value, actor, reason, created_at)
                VALUES ('SYSTEM', 'GOVEASE_OVERRIDE', NULL, ?, 'govease_adapter',
                        'Operator override — data quarantined', ?)
            """, [self.county, now])
            conn.commit()
            conn.close()
        except Exception as e:
            result["errors"].append(str(e))

        result["skipped"] = False
        return result
