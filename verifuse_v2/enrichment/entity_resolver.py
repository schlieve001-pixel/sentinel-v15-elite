"""
VERIFUSE V2 — Engine 3: Entity Resolver (Owner Location)

Reads OutcomeRecords (OVERBID only), looks up the property owner via the
Denver Assessor, flags zombie foreclosures, and outputs EntityRecords.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from bs4 import BeautifulSoup

from verifuse_v2.contracts.schemas import (
    EntityRecord,
    OutcomeRecord,
    SignalRecord,
    validate_entity,
)
from verifuse_v2.utils.stealth import StealthSession

if TYPE_CHECKING:
    from verifuse_v2.pipeline_manager import Governor

log = logging.getLogger(__name__)

SIGNALS_DIR = Path(__file__).resolve().parent.parent / "data" / "signals"
OUTCOMES_DIR = Path(__file__).resolve().parent.parent / "data" / "outcomes"
ENTITIES_DIR = Path(__file__).resolve().parent.parent / "data" / "entities"

ASSESSOR_SEARCH_URL = (
    "https://www.denvergov.org/property/realproperty/search"
)
SCRAPER_NAME = "denver_assessor"
ZOMBIE_THRESHOLD_DAYS = 18 * 30  # ~18 months


class EntityResolver:
    """Engine 3 — resolves property owners and flags zombies."""

    def __init__(self, governor: Governor):
        self.governor = governor
        cfg = governor.registry.get(SCRAPER_NAME, {})
        self.session = StealthSession(rpm=cfg.get("rpm", 2))

    # ── Public API ───────────────────────────────────────────────────

    def resolve(self) -> list[EntityRecord]:
        """Load OVERBID outcomes, look up owners, flag zombies."""
        signals_by_id = self._load_signals_index()
        outcomes = self._load_outcomes()

        if not outcomes:
            log.info("No outcome files found — nothing for Engine 3")
            return []

        entities: list[EntityRecord] = []
        for outcome in outcomes:
            signal = signals_by_id.get(outcome.signal_id)
            entity = self._process_outcome(outcome, signal)
            if entity is not None:
                entities.append(entity)

        self.session.close()

        if entities:
            self._write_entities(entities)

        log.info("Engine 3 produced %d entities from %d outcomes",
                 len(entities), len(outcomes))
        return entities

    # ── Data loading ─────────────────────────────────────────────────

    def _load_signals_index(self) -> dict[str, SignalRecord]:
        """Build {signal_id: SignalRecord} index from all signal files."""
        index: dict[str, SignalRecord] = {}
        for path in sorted(SIGNALS_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text())
                records = data if isinstance(data, list) else [data]
                for d in records:
                    sr = SignalRecord.from_dict(d)
                    index[sr.signal_id] = sr
            except (json.JSONDecodeError, KeyError) as exc:
                log.warning("Skipping corrupt signal file %s: %s", path, exc)
        return index

    def _load_outcomes(self) -> list[OutcomeRecord]:
        """Load outcomes and filter to OVERBID only."""
        outcomes: list[OutcomeRecord] = []
        for path in sorted(OUTCOMES_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text())
                records = data if isinstance(data, list) else [data]
                for d in records:
                    rec = OutcomeRecord.from_dict(d)
                    if rec.outcome_type == "OVERBID":
                        outcomes.append(rec)
            except (json.JSONDecodeError, KeyError) as exc:
                log.warning("Skipping corrupt outcome file %s: %s", path, exc)
        return outcomes

    # ── Per-outcome processing ───────────────────────────────────────

    def _process_outcome(
        self, outcome: OutcomeRecord, signal: Optional[SignalRecord]
    ) -> Optional[EntityRecord]:
        """Look up owner via assessor; check for zombie status."""

        # Zombie check: signal exists, event > 18 months ago, no resolution
        if signal and self._is_zombie(signal):
            return EntityRecord(
                signal_id=outcome.signal_id,
                entity_type="ZOMBIE",
                name=None,
                mailing_address=None,
                contact_score=0,
                is_deceased=False,
                zombie_flag=True,
                zombie_reason=(
                    f"Foreclosure filed {signal.event_date}, "
                    f"> 18 months with OVERBID but no claim activity"
                ),
            )

        # Need an address to look up the assessor
        address = signal.property_address if signal else None
        if not address:
            log.debug("No address for signal %s — skipping assessor lookup",
                      outcome.signal_id)
            return EntityRecord(
                signal_id=outcome.signal_id,
                entity_type="OWNER",
                name=None,
                mailing_address=None,
                contact_score=10,
                is_deceased=False,
                zombie_flag=False,
                zombie_reason=None,
            )

        # Assessor lookup
        owner_name, mailing_address = self._assessor_lookup(address)

        contact_score = 0
        if owner_name:
            contact_score += 40
        if mailing_address:
            contact_score += 40
        if signal and signal.property_address:
            contact_score += 20

        return EntityRecord(
            signal_id=outcome.signal_id,
            entity_type="OWNER",
            name=owner_name,
            mailing_address=mailing_address,
            contact_score=min(contact_score, 100),
            is_deceased=False,
            zombie_flag=False,
            zombie_reason=None,
        )

    # ── Assessor lookup ──────────────────────────────────────────────

    def _assessor_lookup(
        self, address: str
    ) -> tuple[Optional[str], Optional[str]]:
        """Search Denver Assessor for property owner and mailing address."""
        if not self.governor.request_permit(SCRAPER_NAME):
            log.info("Governor denied permit for %s", SCRAPER_NAME)
            return None, None

        try:
            resp = self.session.get(
                ASSESSOR_SEARCH_URL,
                params={"address": address},
            )
            self.governor.report_result(SCRAPER_NAME, resp.status_code)

            if resp.status_code != 200:
                log.warning("Assessor search returned %d for '%s'",
                            resp.status_code, address)
                return None, None

            return self._parse_assessor(resp.text, address)

        except Exception as exc:
            log.error("Assessor lookup failed for '%s': %s", address, exc)
            self.governor.report_result(SCRAPER_NAME, 0)
            return None, None

    def _parse_assessor(
        self, html: str, address: str
    ) -> tuple[Optional[str], Optional[str]]:
        """Extract Owner and Mailing Address from assessor results."""
        soup = BeautifulSoup(html, "html.parser")
        page_text = soup.get_text(separator="\n").lower()

        # Check for "No Results" / empty state
        no_results_phrases = [
            "no results", "no records found", "0 results",
            "no matching", "not found",
        ]
        for phrase in no_results_phrases:
            if phrase in page_text:
                log.info("Assessor returned no results for '%s'", address)
                return None, None

        owner_name = self._extract_field(soup, [
            "owner", "owner name", "property owner", "grantor",
        ])
        mailing_addr = self._extract_field(soup, [
            "mailing address", "mail address", "mailing",
            "owner address", "contact address",
        ])

        return owner_name, mailing_addr

    def _extract_field(
        self, soup: BeautifulSoup, labels: list[str]
    ) -> Optional[str]:
        """Find a text value near one of the given labels."""
        for label_text in labels:
            # Search structured elements: th/td, dt/dd, label/span
            for tag in soup.find_all(["th", "dt", "label", "strong", "b", "span"]):
                tag_content = (tag.get_text() or "").strip().lower()
                if label_text in tag_content:
                    sibling = tag.find_next(["td", "dd", "span", "div", "p"])
                    if sibling:
                        value = sibling.get_text(strip=True)
                        if value and len(value) > 1:
                            return value

            # Fallback: line-by-line scan
            page_text = soup.get_text(separator="\n")
            for line in page_text.split("\n"):
                if label_text in line.lower():
                    # Try to extract value after a colon or separator
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        val = parts[1].strip()
                        if val and len(val) > 1:
                            return val

        return None

    # ── Zombie detection ─────────────────────────────────────────────

    @staticmethod
    def _is_zombie(signal: SignalRecord) -> bool:
        """True if the foreclosure event is > 18 months old."""
        if not signal.event_date:
            return False
        try:
            event_dt = datetime.fromisoformat(signal.event_date)
            if event_dt.tzinfo is None:
                event_dt = event_dt.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - event_dt
            return age.days > ZOMBIE_THRESHOLD_DAYS
        except ValueError:
            return False

    # ── Output ───────────────────────────────────────────────────────

    def _write_entities(self, entities: list[EntityRecord]) -> Path:
        """Write entities to JSON in data/entities/."""
        ENTITIES_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        outfile = ENTITIES_DIR / f"denver_{today}.json"

        payload = []
        for e in entities:
            rec = e.to_dict()
            ok, errors = validate_entity(rec)
            if ok:
                payload.append(rec)
            else:
                log.warning("Dropping invalid entity %s: %s",
                            rec.get("signal_id"), errors)

        outfile.write_text(json.dumps(payload, indent=2))
        log.info("Wrote %d entities to %s", len(payload), outfile)
        return outfile
