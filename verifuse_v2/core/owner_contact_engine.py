"""
verifuse_v2.core.owner_contact_engine — Internal Skip Trace (Zero Marginal Cost First)

Aggregates owner contact information from free/already-in-system sources:
  1. assessor_lookup.py — mailing address for 8 counties (already built)
  2. Colorado Secretary of State — for LLC/corporate owners (public)
  3. Property transfer history — from existing title_stack data
  4. USPS address standardization — confirms deliverability (free API)

Output: owner_contact JSON field stored on leads.owner_contact_json

Usage:
    engine = OwnerContactEngine(db_path)
    contact = engine.get_contact(lead_id)
    engine.enrich_from_assessor(lead_id, county, case_number)
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)


class OwnerContactEngine:
    """Aggregate owner contact from zero-marginal-cost sources."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_contact(self, lead_id: str) -> Optional[dict]:
        """Return owner contact data for a lead. Reads owner_contact_json column first."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT owner_contact_json, property_address, owner_name, county FROM leads WHERE id = ?",
                [lead_id]
            ).fetchone()
            if not row:
                return None
            # Try stored JSON first
            if row["owner_contact_json"]:
                try:
                    return json.loads(row["owner_contact_json"])
                except (json.JSONDecodeError, TypeError):
                    pass
            # Fallback: build minimal contact from available fields
            if row["property_address"]:
                return {
                    "mailing_address": row["property_address"],
                    "address_source": "property_record",
                    "address_confidence": "MEDIUM",
                    "forwarding_address": None,
                    "last_verified": None,
                    "skip_trace_needed": True,
                }
            return None
        finally:
            conn.close()

    def store_contact(self, lead_id: str, contact_data: dict) -> None:
        """Persist owner contact data to leads.owner_contact_json."""
        conn = self._get_conn()
        try:
            contact_data["last_verified"] = datetime.now(timezone.utc).date().isoformat()
            conn.execute(
                "UPDATE leads SET owner_contact_json = ? WHERE id = ?",
                [json.dumps(contact_data), lead_id]
            )
            conn.commit()
            log.info("[owner_contact] stored contact for lead %s (source=%s)",
                     lead_id, contact_data.get("address_source", "unknown"))
        finally:
            conn.close()

    def enrich_from_assessor(self, lead_id: str, county: str, case_number: str) -> Optional[dict]:
        """
        Pull owner contact from assessor_lookup module.
        Returns contact dict if successful, None if assessor lookup unavailable.

        Delegates to verifuse_v2.scrapers.assessor_lookup — that module has
        county-specific implementations for jefferson, arapahoe, adams, denver,
        el_paso, boulder, douglas, weld.
        """
        try:
            from verifuse_v2.scrapers.assessor_lookup import lookup_owner_address
            result = lookup_owner_address(county=county, case_number=case_number)
            if result and result.get("mailing_address"):
                contact = {
                    "mailing_address": result["mailing_address"],
                    "address_source": "assessor",
                    "address_confidence": "HIGH",
                    "forwarding_address": None,
                    "assessor_parcel": result.get("parcel_number"),
                }
                self.store_contact(lead_id, contact)
                return contact
        except (ImportError, AttributeError):
            log.debug("[owner_contact] assessor_lookup.lookup_owner_address not available for %s", county)
        except Exception as e:
            log.warning("[owner_contact] assessor enrichment failed for %s/%s: %s", county, case_number, e)
        return None

    def build_crossref_candidates(self, sale_date_cutoff: str = "2025-09-01") -> list[dict]:
        """
        Return leads where claim window may have expired and funds could be at CO Treasurer.
        These are candidates for the unclaimed property scraper crossref.
        """
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT id, county, case_number, owner_name, overbid_amount, sale_date "
                "FROM leads "
                "WHERE surplus_stream = 'FORECLOSURE_OVERBID' "
                "AND data_grade IN ('GOLD', 'SILVER') "
                "AND sale_date IS NOT NULL "
                "AND sale_date <= ? "
                "ORDER BY overbid_amount DESC LIMIT 200",
                [sale_date_cutoff]
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
