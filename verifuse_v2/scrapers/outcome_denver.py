"""
VERIFUSE V2 — Engine 2: Denver Outcome Scraper (Money Verification)

Reads SignalRecords from data/signals/*.json, hits the Denver foreclosure
detail page for each case, extracts Winning Bid and Total Indebtedness,
computes overbid, and outputs OutcomeRecords.
"""

from __future__ import annotations

import glob
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from bs4 import BeautifulSoup

from verifuse_v2.contracts.schemas import (
    OutcomeRecord,
    SignalRecord,
    validate_outcome,
)
from verifuse_v2.utils.stealth import StealthSession

if TYPE_CHECKING:
    from verifuse_v2.pipeline_manager import Governor

log = logging.getLogger(__name__)

SIGNALS_DIR = Path(__file__).resolve().parent.parent / "data" / "signals"
OUTCOMES_DIR = Path(__file__).resolve().parent.parent / "data" / "outcomes"

DETAIL_URL_TEMPLATE = (
    "https://www.denvergov.org/Government/"
    "Agencies-Departments-Offices/"
    "Agencies-Departments-Offices-Directory/"
    "Department-of-Finance/Public-Trustee/"
    "ForeclosureDetail/{case_number}"
)
SCRAPER_NAME = "denver_outcome"

# Patterns to extract dollar amounts from detail page
MONEY_RE = re.compile(r'\$\s*([\d,]+(?:\.\d{2})?)')


class DenverOutcomeScraper:
    """Engine 2 — scrapes foreclosure detail pages for bid/debt data."""

    def __init__(self, governor: Governor):
        self.governor = governor
        cfg = governor.registry.get(SCRAPER_NAME, {})
        self.session = StealthSession(rpm=cfg.get("rpm", 2))

    # ── Public API ───────────────────────────────────────────────────

    def scrape(self) -> list[OutcomeRecord]:
        """Load all signals, fetch detail pages, produce OutcomeRecords."""
        signals = self._load_signals()
        if not signals:
            log.info("No signal files found — nothing for Engine 2")
            return []

        outcomes: list[OutcomeRecord] = []
        for signal in signals:
            outcome = self._process_signal(signal)
            if outcome is not None:
                outcomes.append(outcome)

        self.session.close()

        if outcomes:
            self._write_outcomes(outcomes)

        log.info("Engine 2 produced %d outcomes from %d signals",
                 len(outcomes), len(signals))
        return outcomes

    # ── Signal loading ───────────────────────────────────────────────

    def _load_signals(self) -> list[SignalRecord]:
        """Read every JSON file in data/signals/ and deserialise."""
        signals: list[SignalRecord] = []
        for path in sorted(SIGNALS_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text())
                if isinstance(data, list):
                    signals.extend(SignalRecord.from_dict(d) for d in data)
                else:
                    signals.append(SignalRecord.from_dict(data))
            except (json.JSONDecodeError, KeyError) as exc:
                log.warning("Skipping corrupt signal file %s: %s", path, exc)
        return signals

    # ── Per-signal processing ────────────────────────────────────────

    def _process_signal(self, signal: SignalRecord) -> Optional[OutcomeRecord]:
        """Fetch the detail page for one signal and extract financials."""
        if not signal.case_number:
            log.debug("Signal %s has no case_number — skipping", signal.signal_id)
            return None

        if not self.governor.request_permit(SCRAPER_NAME):
            log.info("Governor denied permit for %s — stopping", SCRAPER_NAME)
            return None

        detail_url = DETAIL_URL_TEMPLATE.format(case_number=signal.case_number)

        try:
            resp = self.session.get(detail_url)
            self.governor.report_result(SCRAPER_NAME, resp.status_code)

            if resp.status_code != 200:
                log.warning("Detail page %s returned %d", detail_url, resp.status_code)
                return None

            return self._parse_detail(resp.text, signal, detail_url)

        except Exception as exc:
            log.error("Failed to fetch detail for %s: %s", signal.case_number, exc)
            self.governor.report_result(SCRAPER_NAME, 0)
            return None

    def _parse_detail(
        self, html: str, signal: SignalRecord, source_url: str
    ) -> OutcomeRecord:
        """Parse the foreclosure detail page with BeautifulSoup.

        Extracts Winning Bid and Total Indebtedness, computes overbid.
        """
        soup = BeautifulSoup(html, "html.parser")

        winning_bid = self._extract_amount(soup, [
            "winning bid", "bid amount", "sale price", "high bid",
        ])
        total_debt = self._extract_amount(soup, [
            "total indebtedness", "grantor's debt", "grantor debt",
            "total debt", "amount due",
        ])

        # Determine outcome type and amounts
        if winning_bid is None:
            return OutcomeRecord(
                signal_id=signal.signal_id,
                outcome_type="UNCLAIMED",
                gross_amount=None,
                net_amount=None,
                holding_entity="Trustee",
                confidence_score=0.3,
                source_url=source_url,
            )

        if total_debt is not None:
            overbid = winning_bid - total_debt
        else:
            overbid = 0.0

        if overbid > 100:
            outcome_type = "OVERBID"
            confidence = 0.9
        else:
            outcome_type = "NO_SURPLUS"
            confidence = 0.85

        return OutcomeRecord(
            signal_id=signal.signal_id,
            outcome_type=outcome_type,
            gross_amount=winning_bid,
            net_amount=overbid if overbid > 0 else None,
            holding_entity="Trustee",
            confidence_score=confidence,
            source_url=source_url,
        )

    # ── Amount extraction ────────────────────────────────────────────

    def _extract_amount(
        self, soup: BeautifulSoup, labels: list[str]
    ) -> Optional[float]:
        """Find a dollar amount near a label in the HTML.

        Searches table cells, definition lists, and labeled spans.
        """
        page_text = soup.get_text(separator="\n")

        # Strategy 1: label-based table/row scan
        for label in labels:
            # Look in <th>/<td> pairs
            for th in soup.find_all(["th", "dt", "label", "strong", "b"]):
                if label.lower() in (th.get_text() or "").lower():
                    # Check sibling or next element for the amount
                    sibling = th.find_next(["td", "dd", "span", "div"])
                    if sibling:
                        amount = self._parse_money(sibling.get_text())
                        if amount is not None:
                            return amount

            # Strategy 2: regex on lines containing the label
            for line in page_text.split("\n"):
                if label.lower() in line.lower():
                    amount = self._parse_money(line)
                    if amount is not None:
                        return amount

        return None

    @staticmethod
    def _parse_money(text: str) -> Optional[float]:
        """Extract first dollar amount from a string."""
        match = MONEY_RE.search(text)
        if match:
            raw = match.group(1).replace(",", "")
            try:
                return float(raw)
            except ValueError:
                return None
        return None

    # ── Output ───────────────────────────────────────────────────────

    def _write_outcomes(self, outcomes: list[OutcomeRecord]) -> Path:
        """Write outcomes to JSON in data/outcomes/."""
        OUTCOMES_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        outfile = OUTCOMES_DIR / f"denver_{today}.json"

        payload = [o.to_dict() for o in outcomes]

        # Validate each record before writing
        valid_payload = []
        for rec in payload:
            ok, errors = validate_outcome(rec)
            if ok:
                valid_payload.append(rec)
            else:
                log.warning("Dropping invalid outcome %s: %s",
                            rec.get("signal_id"), errors)

        outfile.write_text(json.dumps(valid_payload, indent=2))
        log.info("Wrote %d outcomes to %s", len(valid_payload), outfile)
        return outfile
