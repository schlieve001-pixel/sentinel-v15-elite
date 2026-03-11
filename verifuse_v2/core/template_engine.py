"""
template_engine.py — Pre-flight validation wrapper around dossier_gen.py.

Validates all required fields before calling PDF generation.
Raises ValueError with field list if validation fails — caller converts to HTTP 422.
"""
from __future__ import annotations

import re
from typing import Optional


class TemplateRenderError(ValueError):
    """Raised when template rendering leaves unresolved {{variable}} placeholders."""
    def __init__(self, message: str, unresolved: list):
        super().__init__(message)
        self.unresolved = unresolved


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

    def render(self, template_text: str, variables: dict, strict: bool = True) -> str:
        """
        Render template_text by substituting {{key}} → value for each key in variables.

        After substitution, scans for remaining {{...}} patterns.
        If strict=True (default) and any remain: raises TemplateRenderError.
        If strict=False: returns partially-rendered text (caller accepts responsibility).

        Args:
            template_text: Template string with {{variable}} placeholders
            variables: Dict of variable_name → value to substitute
            strict: If True, raise TemplateRenderError for unresolved variables

        Returns:
            Fully rendered string (when strict=True and all variables resolved)

        Raises:
            TemplateRenderError: When strict=True and unresolved {{...}} remain
        """
        result = template_text
        for key, value in variables.items():
            result = result.replace(f"{{{{{key}}}}}", str(value) if value is not None else "")

        # Scan for any remaining unresolved placeholders
        unresolved = re.findall(r'\{\{([^}]+)\}\}', result)
        if unresolved and strict:
            raise TemplateRenderError(
                f"Unresolved template variables: {unresolved}",
                unresolved=unresolved,
            )
        return result
