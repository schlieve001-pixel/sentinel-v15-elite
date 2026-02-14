"""
VERIFUSE V2 — Engine 1: Denver Signal Scraper

Discovery ONLY — finds foreclosure events from Denver Public Trustee.
Produces SignalRecord JSON files. No outcome data.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from verifuse_v2.contracts.schemas import SignalRecord, validate_signal
from verifuse_v2.utils.stealth import StealthSession

if TYPE_CHECKING:
    from verifuse_v2.pipeline_manager import Governor

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "signals"
BASE_URL = (
    "https://www.denvergov.org/Government/"
    "Agencies-Departments-Offices/"
    "Agencies-Departments-Offices-Directory/"
    "Department-of-Finance/Public-Trustee"
)
SCRAPER_NAME = "denver_trustee"


class DenverSignalScraper:
    """Engine 1 — Denver Public Trustee foreclosure signal discovery."""

    def __init__(self, governor: Governor):
        self.governor = governor
        cfg = governor.registry.get(SCRAPER_NAME, {})
        self.session = StealthSession(rpm=cfg.get("rpm", 2))

    def scrape(self) -> list[SignalRecord]:
        """Fetch the Denver Public Trustee page and extract signals.

        Returns a list of SignalRecord objects and writes them to JSON.
        """
        if not self.governor.request_permit(SCRAPER_NAME):
            log.info("Governor denied permit for %s — skipping", SCRAPER_NAME)
            return []

        signals: list[SignalRecord] = []

        try:
            resp = self.session.get(BASE_URL)
            self.governor.report_result(SCRAPER_NAME, resp.status_code)

            if resp.status_code != 200:
                log.warning("Denver page returned %d", resp.status_code)
                return signals

            signals = self._parse_page(resp.text)
            log.info("Parsed %d signals from Denver Public Trustee", len(signals))

        except Exception as exc:
            log.error("Scrape failed: %s", exc)
            self.governor.report_result(SCRAPER_NAME, 0, captcha_hit=False)
        finally:
            self.session.close()

        if signals:
            self._write_signals(signals)

        return signals

    def _parse_page(self, html: str) -> list[SignalRecord]:
        """Parse HTML for foreclosure event data.

        Extracts case numbers, sale dates, and addresses from page content.
        Uses regex patterns to find structured data in the HTML.
        """
        signals: list[SignalRecord] = []

        # Pattern: look for case/sale references in page text
        # Denver Public Trustee pages contain structured foreclosure data
        # This handles both table-based and list-based layouts
        case_pattern = re.compile(
            r'(?:case|filing|rule)\s*(?:#|number|no\.?)?\s*[:.]?\s*'
            r'([A-Z0-9][\w\-]{3,30})',
            re.IGNORECASE,
        )
        date_pattern = re.compile(
            r'(?:sale\s*date|scheduled|hearing)\s*[:.]?\s*'
            r'(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})',
            re.IGNORECASE,
        )
        address_pattern = re.compile(
            r'(\d{1,6}\s+[A-Z][a-zA-Z\s]{2,40}(?:St|Ave|Blvd|Dr|Rd|Ct|Ln|Way|Pl|Cir)\.?'
            r'(?:\s*#?\s*\d{0,5})?)',
            re.IGNORECASE,
        )

        cases = case_pattern.findall(html)
        dates = date_pattern.findall(html)
        addresses = address_pattern.findall(html)

        # Zip discovered fields into signal records
        for i, case_num in enumerate(cases):
            event_date = ""
            if i < len(dates):
                event_date = self._normalize_date(dates[i])

            address = None
            if i < len(addresses):
                address = addresses[i].strip()

            record = SignalRecord(
                county="Denver",
                signal_type="FORECLOSURE_FILED",
                case_number=case_num.strip(),
                event_date=event_date,
                source_url=BASE_URL,
                property_address=address,
                raw_data={
                    "case_raw": case_num,
                    "date_raw": dates[i] if i < len(dates) else None,
                    "address_raw": addresses[i] if i < len(addresses) else None,
                },
            )

            valid, errors = validate_signal(record.to_dict())
            if valid:
                signals.append(record)
            else:
                log.debug("Skipping invalid signal: %s", errors)

        return signals

    @staticmethod
    def _normalize_date(raw: str) -> str:
        """Attempt to parse a date string into ISO 8601."""
        for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%m-%d-%y"):
            try:
                return datetime.strptime(raw.strip(), fmt).date().isoformat()
            except ValueError:
                continue
        return raw.strip()

    def _write_signals(self, signals: list[SignalRecord]) -> Path:
        """Write signals to JSON file in data/signals/."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        outfile = DATA_DIR / f"denver_{today}.json"

        payload = [s.to_dict() for s in signals]
        outfile.write_text(json.dumps(payload, indent=2))
        log.info("Wrote %d signals to %s", len(signals), outfile)
        return outfile
