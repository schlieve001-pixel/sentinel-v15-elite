"""
VERIFUSE V2 — Titanium Models

Core invariant: Lead status (RESTRICTED/ACTIONABLE/EXPIRED) is computed
at runtime from UTC dates. NEVER stored statically.

Projection redaction:
  - SafeAsset: No PII, no street number. Default API response.
  - FullAsset: Full address + owner name. Only after valid lead_unlock.
"""

from __future__ import annotations

import re
from datetime import datetime, date, timedelta, timezone
from typing import Optional

from pydantic import BaseModel, Field, computed_field


# ── Constants ────────────────────────────────────────────────────────

RESTRICTION_DAYS = 180   # C.R.S. § 38-38-111: 6 months post-sale
CLAIM_WINDOW_DAYS = 180  # Default claim window (overridden by statute_authority)


# ── Lead Model (internal, full data) ────────────────────────────────

class Lead(BaseModel):
    """Internal lead representation with all fields from DB row.
    Status is computed, never stored.
    """
    asset_id: str
    county: str
    state: str = "CO"
    jurisdiction: str = ""
    case_number: Optional[str] = None
    asset_type: str = "FORECLOSURE_SURPLUS"
    source_name: Optional[str] = None
    owner_of_record: Optional[str] = None
    property_address: Optional[str] = None
    sale_date: Optional[str] = None
    claim_deadline: Optional[str] = None
    winning_bid: float = 0.0
    total_debt: float = 0.0
    surplus_amount: float = 0.0
    estimated_surplus: float = 0.0
    total_indebtedness: float = 0.0
    overbid_amount: float = 0.0
    confidence_score: float = 0.0
    completeness_score: float = 0.0
    data_grade: str = "BRONZE"
    days_remaining: Optional[int] = None
    recorder_link: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""

    @computed_field
    @property
    def status(self) -> str:
        """Dynamic status computed from UTC dates. NEVER stored.

        RESTRICTED: 0-6 months post-sale (attorneys only)
        ACTIONABLE: >6 months post-sale (any paid user)
        EXPIRED:    Past claim deadline (locked, cannot unlock)
        UNKNOWN:    Missing dates
        """
        today = datetime.now(timezone.utc).date()

        # Check expiry first (claim_deadline)
        if self.claim_deadline:
            try:
                deadline = date.fromisoformat(self.claim_deadline)
                if today > deadline:
                    return "EXPIRED"
            except (ValueError, TypeError):
                pass

        # Check restriction period (sale_date + 180 days)
        if self.sale_date:
            try:
                sale = date.fromisoformat(self.sale_date[:10])
                restriction_end = sale + timedelta(days=RESTRICTION_DAYS)
                if today < restriction_end:
                    return "RESTRICTED"
                return "ACTIONABLE"
            except (ValueError, TypeError):
                pass

        return "UNKNOWN"

    @computed_field
    @property
    def effective_surplus(self) -> float:
        """Best available surplus figure."""
        if self.surplus_amount > 0:
            return self.surplus_amount
        if self.estimated_surplus > 0:
            return self.estimated_surplus
        if self.winning_bid > 0 and self.total_debt > 0:
            return max(0.0, self.winning_bid - self.total_debt)
        return 0.0

    @classmethod
    def from_row(cls, row: dict) -> Lead:
        """Construct from a sqlite3.Row dict."""
        return cls(**{k: v for k, v in row.items() if k in cls.model_fields})


# ── SafeAsset (redacted projection — default API response) ──────────

class SafeAsset(BaseModel):
    """Public-facing projection. NO PII, NO street number.

    This is what unauthenticated and browsing users see.
    """
    asset_id: str
    county: str
    state: str = "CO"
    case_number: Optional[str] = None
    asset_type: str = "FORECLOSURE_SURPLUS"
    status: str                         # RESTRICTED / ACTIONABLE / EXPIRED
    surplus_estimate: float             # Rounded to nearest $100
    data_grade: str
    confidence_score: float
    sale_date: Optional[str] = None
    claim_deadline: Optional[str] = None
    days_remaining: Optional[int] = None
    city_hint: str = ""                 # "Denver, CO" — no street address
    surplus_verified: bool = False

    @classmethod
    def from_lead(cls, lead: Lead) -> SafeAsset:
        """Project a Lead into a SafeAsset (strip PII)."""
        # Extract city from address (drop street number + name)
        city_hint = _extract_city(lead.property_address, lead.county)

        # Compute days remaining from claim_deadline
        days_left = lead.days_remaining
        if lead.claim_deadline:
            try:
                deadline = date.fromisoformat(lead.claim_deadline)
                days_left = (deadline - datetime.now(timezone.utc).date()).days
            except (ValueError, TypeError):
                pass

        verified = (
            lead.total_debt > 0
            and lead.winning_bid > 0
            and lead.confidence_score >= 0.7
        )

        return cls(
            asset_id=lead.asset_id,
            county=lead.county,
            state=lead.state,
            case_number=lead.case_number,
            asset_type=lead.asset_type,
            status=lead.status,
            surplus_estimate=_round_surplus(lead.effective_surplus),
            data_grade=lead.data_grade,
            confidence_score=round(lead.confidence_score, 2),
            sale_date=lead.sale_date,
            claim_deadline=lead.claim_deadline,
            days_remaining=days_left,
            city_hint=city_hint,
            surplus_verified=verified,
        )


# ── FullAsset (unlocked projection — includes PII) ─────────────────

class FullAsset(SafeAsset):
    """Full lead data returned ONLY after valid lead_unlock.

    Includes: full address, owner name, financial details.
    """
    owner_name: Optional[str] = None
    property_address: Optional[str] = None
    winning_bid: float = 0.0
    total_debt: float = 0.0
    surplus_amount: float = 0.0
    overbid_amount: float = 0.0
    recorder_link: Optional[str] = None
    completeness_score: float = 0.0

    @classmethod
    def from_lead(cls, lead: Lead) -> FullAsset:
        """Project a Lead into a FullAsset (all data)."""
        safe = SafeAsset.from_lead(lead)
        return cls(
            **safe.model_dump(),
            owner_name=lead.owner_of_record,
            property_address=lead.property_address,
            winning_bid=lead.winning_bid,
            total_debt=lead.total_debt,
            surplus_amount=lead.effective_surplus,
            overbid_amount=lead.overbid_amount,
            recorder_link=lead.recorder_link,
            completeness_score=lead.completeness_score,
        )


# ── Attorney Verification Request ──────────────────────────────────

class AttorneyVerifyRequest(BaseModel):
    bar_number: str = Field(..., min_length=3, max_length=20)
    bar_state: str = Field(default="CO", min_length=2, max_length=2)


class UnlockRequest(BaseModel):
    disclaimer_accepted: bool = False


# ── Helpers ──────────────────────────────────────────────────────────

_STREET_NUM_RE = re.compile(r"^\d+[\-\s]?\w*\s+")


def _extract_city(address: Optional[str], county: str) -> str:
    """Extract city/county from address, stripping street number + name.

    "1234 Main St, Denver, CO 80203" → "Denver, CO 80203"
    """
    if not address:
        return f"{county}, CO"
    parts = [p.strip() for p in address.split(",")]
    if len(parts) >= 2:
        return ", ".join(parts[-2:]).strip()
    return f"{county}, CO"


def _round_surplus(amount: float) -> float:
    """Round surplus to nearest $100 for safe projection."""
    if amount <= 0:
        return 0.0
    return round(amount / 100) * 100
