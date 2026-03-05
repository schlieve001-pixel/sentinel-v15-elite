"""
template_engine.py — Pre-flight validation wrapper around dossier_gen.py.

Validates all required fields before calling PDF generation.
Raises ValueError with field list if validation fails — caller converts to HTTP 422.
"""
from __future__ import annotations

from typing import Optional


# Fields that must be non-empty for any document generation
_REQUIRED_BASE = [
    "owner_name",
    "property_address",
    "sale_date",
    "county",
    "case_number",
]

# At least one of these must have a positive value
_SURPLUS_FIELDS = ["overbid_amount", "surplus_amount"]

# Additional fields required for full case packet
_REQUIRED_PACKET = ["restriction_end_date"]


def _safe_float(val) -> Optional[float]:
    """Return float or None — no exceptions."""
    try:
        f = float(val)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


class TemplateEngine:
    """
    Validates lead data completeness before generating PDFs.

    Usage:
        tpl = TemplateEngine()
        try:
            pdf_bytes = tpl.generate_letter(lead_dict)
        except ValueError as e:
            raise HTTPException(422, detail=str(e))
    """

    def validate(self, lead: dict, level: str = "letter") -> list:
        """
        Return list of missing field names.
        Empty list = valid, ready to generate.
        level: 'letter' | 'packet'
        """
        missing = []

        for f in _REQUIRED_BASE:
            val = lead.get(f)
            if not val or (isinstance(val, str) and not val.strip()):
                missing.append(f)

        if not any(_safe_float(lead.get(f)) for f in _SURPLUS_FIELDS):
            missing.append("net_to_owner_amount")

        if level == "packet":
            for f in _REQUIRED_PACKET:
                val = lead.get(f)
                if not val or (isinstance(val, str) and not val.strip()):
                    missing.append(f)

        return missing

    def assert_letter_ready(self, lead: dict) -> None:
        """
        Validate all required fields for Rule 7.3 letter generation.
        Raises ValueError with field list if validation fails — caller converts to HTTP 422.
        Does not generate — generation is delegated to verifuse_v2.legal.mail_room.
        """
        missing = self.validate(lead, "letter")
        if missing:
            raise ValueError(
                f"Cannot generate letter — missing required fields: {', '.join(missing)}"
            )

    def assert_packet_ready(self, lead: dict) -> None:
        """
        Validate all required fields for full case packet generation.
        Raises ValueError with field list if validation fails — caller converts to HTTP 422.
        Does not generate — generation is delegated to verifuse_v2.attorney.case_packet.
        """
        missing = self.validate(lead, "packet")
        if missing:
            raise ValueError(
                f"Cannot generate packet — missing required fields: {', '.join(missing)}"
            )
