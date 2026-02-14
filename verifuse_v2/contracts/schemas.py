"""
VERIFUSE V2 — JSON Contract Definitions

All engines communicate via these immutable schemas.
Defined as dataclasses with to_dict()/from_dict() for JSON serialization.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, fields, asdict
from datetime import datetime, timezone
from typing import Optional


# ── Enum-style constants ─────────────────────────────────────────────

SIGNAL_TYPES = frozenset({
    "FORECLOSURE_FILED",
    "SALE_SCHEDULED",
    "SALE_HELD",
    "PROBATE_OPENED",
})

OUTCOME_TYPES = frozenset({
    "OVERBID",
    "EXCESS",
    "UNCLAIMED",
    "NO_SURPLUS",
    "REDEEMED",
})

HOLDING_ENTITIES = frozenset({
    "Trustee",
    "Treasurer",
    "Court",
})

ENTITY_TYPES = frozenset({
    "OWNER",
    "ESTATE",
    "ZOMBIE",
})


# ── Helpers ──────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid4() -> str:
    return str(uuid.uuid4())


# ── SignalRecord (Engine 1 output) ───────────────────────────────────

@dataclass
class SignalRecord:
    signal_id: str = field(default_factory=_uuid4)
    county: str = "Denver"
    signal_type: str = "FORECLOSURE_FILED"
    case_number: str = ""
    event_date: str = ""          # ISO 8601
    source_url: str = ""
    property_address: Optional[str] = None
    raw_data: dict = field(default_factory=dict)
    scraped_at: str = field(default_factory=_now_iso)
    scraper_version: str = "signal_denver:1.0"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> SignalRecord:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


# ── OutcomeRecord (Engine 2 output) ─────────────────────────────────

@dataclass
class OutcomeRecord:
    signal_id: str = ""
    outcome_type: str = "NO_SURPLUS"
    gross_amount: Optional[float] = None
    net_amount: Optional[float] = None
    holding_entity: str = "Trustee"
    confidence_score: float = 0.0
    source_url: str = ""
    verified_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> OutcomeRecord:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


# ── EntityRecord (Engine 3 output) ──────────────────────────────────

@dataclass
class EntityRecord:
    signal_id: str = ""
    entity_type: str = "OWNER"
    name: Optional[str] = None
    mailing_address: Optional[str] = None
    contact_score: int = 0        # 0-100
    is_deceased: bool = False
    zombie_flag: bool = False
    zombie_reason: Optional[str] = None
    enriched_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> EntityRecord:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


# ── Validators ───────────────────────────────────────────────────────

def validate_signal(data: dict) -> tuple[bool, list[str]]:
    """Validate a dict against SignalRecord contract."""
    errors: list[str] = []

    for req in ("signal_id", "county", "signal_type", "case_number",
                "event_date", "source_url", "scraped_at", "scraper_version"):
        val = data.get(req)
        if val is None or (isinstance(val, str) and not val.strip()):
            errors.append(f"Missing or empty required field: {req}")

    st = data.get("signal_type")
    if st and st not in SIGNAL_TYPES:
        errors.append(f"Invalid signal_type: {st}. Must be one of {sorted(SIGNAL_TYPES)}")

    if "raw_data" in data and not isinstance(data["raw_data"], dict):
        errors.append("raw_data must be a dict")

    return (len(errors) == 0, errors)


def validate_outcome(data: dict) -> tuple[bool, list[str]]:
    """Validate a dict against OutcomeRecord contract."""
    errors: list[str] = []

    for req in ("signal_id", "outcome_type", "holding_entity",
                "confidence_score", "source_url", "verified_at"):
        val = data.get(req)
        if val is None or (isinstance(val, str) and not val.strip()):
            errors.append(f"Missing or empty required field: {req}")

    ot = data.get("outcome_type")
    if ot and ot not in OUTCOME_TYPES:
        errors.append(f"Invalid outcome_type: {ot}. Must be one of {sorted(OUTCOME_TYPES)}")

    he = data.get("holding_entity")
    if he and he not in HOLDING_ENTITIES:
        errors.append(f"Invalid holding_entity: {he}. Must be one of {sorted(HOLDING_ENTITIES)}")

    cs = data.get("confidence_score")
    if cs is not None and not (0.0 <= float(cs) <= 1.0):
        errors.append(f"confidence_score must be 0.0-1.0, got {cs}")

    return (len(errors) == 0, errors)


def validate_entity(data: dict) -> tuple[bool, list[str]]:
    """Validate a dict against EntityRecord contract."""
    errors: list[str] = []

    for req in ("signal_id", "entity_type", "enriched_at"):
        val = data.get(req)
        if val is None or (isinstance(val, str) and not val.strip()):
            errors.append(f"Missing or empty required field: {req}")

    et = data.get("entity_type")
    if et and et not in ENTITY_TYPES:
        errors.append(f"Invalid entity_type: {et}. Must be one of {sorted(ENTITY_TYPES)}")

    cs = data.get("contact_score")
    if cs is not None and not (0 <= int(cs) <= 100):
        errors.append(f"contact_score must be 0-100, got {cs}")

    return (len(errors) == 0, errors)
