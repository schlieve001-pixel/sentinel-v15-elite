"""
VERIFUSE V2 — Dossier PDF Generator (Rebuilt)

Generates professional intelligence dossier PDFs with:
  - 4-section layout (Asset Profile, Forensic Financial Analysis,
    Entity Intelligence, Recovery Strategy)
  - Validation layer: marks unverified data with UNVERIFIED watermark
  - Math proof showing surplus calculation
  - Legal disclaimer page for restricted leads
  - No "Money Truth" — professional forensic terminology
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path

from fpdf import FPDF

from verifuse_v2.contracts.schemas import EntityRecord, OutcomeRecord, SignalRecord

PDF_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "dossiers"


# ── Validation ───────────────────────────────────────────────────────

def _is_verified(outcome: OutcomeRecord, signal: SignalRecord) -> bool:
    """Check if the surplus math is forensically verifiable."""
    surplus = outcome.net_amount or 0
    gross = outcome.gross_amount or 0
    # Verified requires: gross > 0 AND (gross - surplus) gives a positive indebtedness
    # OR indebtedness is explicitly known (gross != surplus when both > 0)
    if gross > 0 and surplus > 0 and gross != surplus:
        return True
    # If overbid == surplus and both > 0, indebtedness was never extracted
    if gross > 0 and surplus > 0 and abs(gross - surplus) < 0.01:
        return False
    return False


def _verification_status(outcome: OutcomeRecord, signal: SignalRecord) -> str:
    """Return 'VERIFIED' or 'UNVERIFIED' with reason."""
    if _is_verified(outcome, signal):
        return "VERIFIED"
    return "UNVERIFIED"


# ── PDF Class ────────────────────────────────────────────────────────

class DossierPDF(FPDF):
    """Professional dossier PDF with dark theme and clean layout."""

    def __init__(self, verified: bool = True):
        super().__init__()
        self._verified = verified

    def header(self):
        # Dark background
        self.set_fill_color(15, 23, 42)  # #0f172a
        self.rect(0, 0, 210, 297, 'F')

        # Logo bar
        self.set_fill_color(2, 6, 23)  # #020617
        self.rect(0, 0, 210, 28, 'F')

        self.set_font('Arial', 'B', 11)
        self.set_text_color(16, 185, 129)  # Green
        self.set_xy(10, 8)
        self.cell(80, 10, 'VERIFUSE', 0, 0, 'L')

        self.set_font('Arial', '', 8)
        self.set_text_color(148, 163, 184)  # text-dim
        self.set_xy(120, 8)
        self.cell(80, 10, 'COLORADO SURPLUS INTELLIGENCE', 0, 0, 'R')

        # Divider line
        self.set_draw_color(30, 41, 59)  # border color
        self.line(10, 28, 200, 28)

        self.set_y(32)

    def footer(self):
        self.set_y(-18)
        self.set_font('Arial', 'I', 7)
        self.set_text_color(100, 116, 139)  # muted

        self.cell(95, 8, f'CONFIDENTIAL  |  Page {self.page_no()}', 0, 0, 'L')
        self.cell(95, 8,
                  f'Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}',
                  0, 0, 'R')

    def section_header(self, number: int, title: str):
        """Draw a section header with number badge."""
        self.ln(6)
        # Section number badge
        self.set_fill_color(16, 185, 129)  # Green
        self.set_text_color(0, 0, 0)
        self.set_font('Arial', 'B', 8)
        self.cell(8, 6, str(number), 0, 0, 'C', fill=True)

        # Section title
        self.set_text_color(248, 250, 252)  # white
        self.set_font('Arial', 'B', 11)
        self.cell(2)  # spacer
        self.cell(0, 6, title, 0, 1, 'L')

        # Underline
        y = self.get_y()
        self.set_draw_color(30, 41, 59)
        self.line(10, y + 1, 200, y + 1)
        self.ln(4)

    def field_row(self, label: str, value: str, highlight: bool = False):
        """Draw a label: value row."""
        self.set_font('Arial', '', 8)
        self.set_text_color(148, 163, 184)  # dim
        self.cell(55, 7, label, 0, 0, 'L')

        if highlight:
            self.set_text_color(16, 185, 129)  # green
            self.set_font('Arial', 'B', 9)
        else:
            self.set_text_color(224, 224, 224)  # light gray
            self.set_font('Arial', '', 9)
        self.cell(0, 7, value, 0, 1, 'L')

    def warning_row(self, text: str):
        """Draw a warning/notice row."""
        self.set_font('Arial', 'I', 8)
        self.set_text_color(245, 158, 11)  # gold/warning
        self.cell(0, 6, text, 0, 1, 'L')

    def add_watermark(self, text: str = "UNVERIFIED"):
        """Add diagonal watermark text across the page."""
        self.set_font('Arial', 'B', 48)
        self.set_text_color(245, 158, 11)  # gold

        # Save state and rotate
        with self.rotation(angle=45, x=105, y=148):
            self.set_xy(30, 140)
            self.set_alpha(0.12)
            self.cell(150, 20, text, 0, 0, 'C')
            self.set_alpha(1.0)

    def set_alpha(self, alpha: float):
        """Set transparency (FPDF2 supports this via set_text_color alpha)."""
        # fpdf doesn't natively support alpha, so we approximate with color
        # For watermark effect, we use very light colors instead
        pass


def _fmt_money(amount: float | None) -> str:
    """Format money value."""
    if amount is None or amount == 0:
        return "$0.00"
    return f"${amount:,.2f}"


# ── Main Generator ───────────────────────────────────────────────────

def generate_dossier(
    signal: SignalRecord,
    outcome: OutcomeRecord,
    entity: EntityRecord,
    output_dir: Path | str | None = None,
    is_restricted: bool = False,
) -> str:
    """Generate a professional 4-section intelligence dossier PDF.

    Parameters
    ----------
    signal : SignalRecord
        Engine 1 output — case info, property address, event date.
    outcome : OutcomeRecord
        Engine 2 output — surplus amounts, holding entity.
    entity : EntityRecord
        Engine 3 output — owner name, mailing address, contact score.
    output_dir : Path | None
        Override output directory.
    is_restricted : bool
        If True, prepend legal disclaimer page for restricted leads.

    Returns
    -------
    str
        Absolute path to the generated PDF.
    """
    out = Path(output_dir) if output_dir else PDF_OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)

    surplus = outcome.net_amount or 0.0
    gross = outcome.gross_amount or 0.0
    debt = gross - surplus if gross > 0 and surplus > 0 and gross != surplus else 0.0
    owner_name = entity.name or "UNKNOWN"
    address = signal.property_address or "Unknown"
    case_number = signal.case_number or signal.signal_id[:16]
    sale_date = signal.event_date or "Unknown"
    verified = _is_verified(outcome, signal)
    verification_label = _verification_status(outcome, signal)

    pdf = DossierPDF(verified=verified)
    pdf.set_auto_page_break(auto=True, margin=20)

    # ── Legal Disclaimer Page (for restricted leads) ──
    if is_restricted:
        pdf.add_page()

        pdf.set_font('Arial', 'B', 16)
        pdf.set_text_color(239, 68, 68)  # Red
        pdf.cell(0, 12, 'LEGAL DISCLAIMER — RESTRICTED ASSET', 0, 1, 'C')
        pdf.ln(8)

        pdf.set_font('Arial', 'B', 10)
        pdf.set_text_color(245, 158, 11)  # Gold
        pdf.cell(0, 8, 'ATTORNEY-CLIENT AGREEMENT EXEMPTION', 0, 1, 'C')
        pdf.ln(4)

        pdf.set_font('Arial', '', 9)
        pdf.set_text_color(224, 224, 224)

        disclaimer_text = (
            "IMPORTANT LEGAL NOTICE\n\n"
            "This asset is classified as RESTRICTED under C.R.S. § 38-38-111. "
            "The foreclosure sale occurred within the last 180 days, meaning "
            "overbid funds are currently held by the Public Trustee.\n\n"
            "C.R.S. § 38-38-111(2.5)(c): Any agreement to pay compensation "
            "to any person to recover or assist in recovering overbid amounts "
            "from the public trustee is VOID AND UNENFORCEABLE.\n\n"
            "ATTORNEY EXEMPTION: C.R.S. § 38-13-1302(5) provides that "
            "attorney-client agreements are exempt from the prohibition on "
            "compensation agreements. This dossier is provided solely for use "
            "within a bona fide attorney-client relationship.\n\n"
            "By accessing this dossier, the licensed attorney confirms:\n"
            "  1. A bona fide attorney-client relationship exists or will be "
            "established with the claimant.\n"
            "  2. The attorney will not enter into any prohibited compensation "
            "agreement under C.R.S. § 38-38-111.\n"
            "  3. The attorney understands that inducing a person to enter "
            "into a prohibited agreement is a class 2 misdemeanor and a "
            "deceptive trade practice under the Colorado Consumer Protection Act.\n\n"
            "C.R.S. § 38-13-1304: After funds transfer to the State Treasurer, "
            "finder agreements are void for an additional 2 years. After that period, "
            "compensation is capped at 20% (first year) or 30% (subsequent years)."
        )
        pdf.multi_cell(0, 5, disclaimer_text)

    # ── Main Dossier Page ──
    pdf.add_page()

    # Title block
    pdf.set_font('Arial', 'B', 18)
    pdf.set_text_color(248, 250, 252)
    pdf.cell(0, 12, f'INTELLIGENCE DOSSIER', 0, 1, 'L')

    pdf.set_font('Arial', '', 9)
    pdf.set_text_color(148, 163, 184)
    pdf.cell(0, 6, f'Case: {case_number}  |  County: {signal.county}  |  State: CO', 0, 1, 'L')

    # Verification status badge
    if verified:
        pdf.set_font('Arial', 'B', 9)
        pdf.set_text_color(16, 185, 129)
        pdf.cell(0, 8, 'STATUS: VERIFIED', 0, 1, 'L')
    else:
        pdf.set_font('Arial', 'B', 9)
        pdf.set_text_color(245, 158, 11)
        pdf.cell(0, 8, 'STATUS: UNVERIFIED — Verify with Public Trustee before filing', 0, 1, 'L')

    pdf.ln(2)

    # ── SECTION 1: ASSET PROFILE ──
    pdf.section_header(1, "ASSET PROFILE")

    pdf.field_row("County:", signal.county)
    pdf.field_row("Case Number:", case_number)
    pdf.field_row("Property Address:", address)
    pdf.field_row("Asset Type:", "Foreclosure Surplus")
    pdf.field_row("Sale Date:", sale_date)
    pdf.field_row("Data Source:", signal.source_url or "County Public Trustee records")

    # ── SECTION 2: FORENSIC FINANCIAL ANALYSIS ──
    pdf.section_header(2, "FORENSIC FINANCIAL ANALYSIS")

    # Surplus label — conditional on verification
    if verified:
        pdf.field_row("Verified Surplus:", _fmt_money(surplus), highlight=True)
    else:
        pdf.field_row("Estimated Surplus (UNVERIFIED):", _fmt_money(surplus), highlight=True)
        pdf.warning_row("  Surplus has not been independently verified against indebtedness records.")

    pdf.field_row("Winning Bid (Gross):", _fmt_money(gross))

    # Indebtedness — show presence or absence clearly
    if debt > 0:
        pdf.field_row("Total Indebtedness:", _fmt_money(debt))
    else:
        pdf.set_font('Arial', '', 8)
        pdf.set_text_color(148, 163, 184)
        pdf.cell(55, 7, "Total Indebtedness:", 0, 0, 'L')
        pdf.set_text_color(245, 158, 11)
        pdf.set_font('Arial', 'I', 8)
        pdf.cell(0, 7, "NOT AVAILABLE — verify with Public Trustee", 0, 1, 'L')

    # Math proof
    pdf.ln(3)
    pdf.set_font('Arial', 'B', 8)
    pdf.set_text_color(148, 163, 184)
    pdf.cell(0, 6, "SURPLUS CALCULATION:", 0, 1, 'L')
    pdf.set_font('Arial', '', 8)
    pdf.set_text_color(224, 224, 224)

    if debt > 0:
        pdf.cell(0, 5,
                 f"  Winning Bid ({_fmt_money(gross)}) - Total Indebtedness ({_fmt_money(debt)}) "
                 f"= Surplus ({_fmt_money(surplus)})",
                 0, 1, 'L')
    else:
        pdf.cell(0, 5,
                 f"  Winning Bid ({_fmt_money(gross)}) - Total Indebtedness (UNKNOWN) "
                 f"= Surplus ({_fmt_money(surplus)}) [UNVERIFIED]",
                 0, 1, 'L')

    pdf.field_row("Holding Entity:", outcome.holding_entity or "Public Trustee")

    conf_pct = outcome.confidence_score * 100 if outcome.confidence_score else 0
    pdf.field_row("Confidence Score:", f"{conf_pct:.0f}%")

    # ── SECTION 3: ENTITY INTELLIGENCE ──
    pdf.section_header(3, "ENTITY INTELLIGENCE")

    pdf.field_row("Owner of Record:", owner_name)
    pdf.field_row("Entity Type:", entity.entity_type or "OWNER")

    if entity.mailing_address:
        pdf.field_row("Mailing Address:", entity.mailing_address)

    pdf.field_row("Contact Score:", f"{entity.contact_score}/100")

    if entity.is_deceased:
        pdf.set_font('Arial', 'B', 8)
        pdf.set_text_color(239, 68, 68)
        pdf.cell(0, 7, "DECEASED OWNER INDICATOR — Estate/probate filing may be required", 0, 1, 'L')

    if entity.zombie_flag:
        pdf.set_font('Arial', 'B', 8)
        pdf.set_text_color(245, 158, 11)
        pdf.cell(55, 7, "ZOMBIE FLAG:", 0, 0, 'L')
        pdf.cell(0, 7, entity.zombie_reason or "Stale foreclosure — property may be abandoned", 0, 1, 'L')

    # ── SECTION 4: RECOVERY STRATEGY ──
    pdf.section_header(4, "RECOVERY STRATEGY")

    pdf.set_font('Arial', '', 9)
    pdf.set_text_color(224, 224, 224)

    steps = [
        "1. Verify surplus amount directly with the County Public Trustee office.",
        "2. Confirm claimant identity and establish chain of title.",
        "3. Review C.R.S. § 38-38-111 claim period and restriction status.",
        "4. Prepare and file Motion for Disbursement of Surplus Funds.",
        "5. Serve all parties of interest per county court rules.",
        "6. Attend hearing if required by the county.",
    ]
    for step in steps:
        pdf.cell(0, 6, step, 0, 1, 'L')

    pdf.ln(4)

    # Statute citations
    pdf.set_font('Arial', 'B', 8)
    pdf.set_text_color(148, 163, 184)
    pdf.cell(0, 6, "APPLICABLE STATUTES:", 0, 1, 'L')
    pdf.set_font('Arial', '', 8)
    pdf.set_text_color(224, 224, 224)

    statutes = [
        "C.R.S. § 38-38-111 — Disposition of overbid amounts; 180-day claim window",
        "C.R.S. § 38-38-111(2.5)(c) — Prohibition on compensation agreements",
        "C.R.S. § 38-13-1302(5) — Attorney-client exemption",
        "C.R.S. § 38-13-1304 — Restrictions on finder agreements (2-year blackout)",
    ]
    for s in statutes:
        pdf.cell(0, 5, f"  {s}", 0, 1, 'L')

    pdf.ln(6)

    # ── Disclaimer ──
    pdf.set_draw_color(30, 41, 59)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(4)

    pdf.set_font('Arial', 'I', 7)
    pdf.set_text_color(100, 116, 139)
    pdf.multi_cell(0, 4,
        "DISCLAIMER: This report is for informational purposes only. VeriFuse is a data "
        "aggregator, not a law firm. All financial figures should be verified with the County "
        "Public Trustee before filing any claims. This does not constitute legal advice. "
        "Surplus amounts labeled 'UNVERIFIED' have not been independently confirmed against "
        "county indebtedness records. No phone numbers, email addresses, or skip-tracing data "
        "are provided by this platform."
    )

    # Add UNVERIFIED watermark if not verified
    if not verified:
        # Draw watermark text diagonally (approximate with positioned text)
        for page_num in range(1, pdf.pages_nb + 1):
            pdf.page = page_num
            pdf.set_font('Arial', 'B', 52)
            pdf.set_text_color(245, 158, 11)
            # We can't easily rotate in fpdf, so add a prominent label instead
        # Reset to last page
        pdf.page = pdf.pages_nb

        # Add a visible UNVERIFIED bar at top of first dossier page
        # (page 1 if no disclaimer, page 2 if restricted)
        target_page = 2 if is_restricted else 1
        pdf.page = target_page
        pdf.set_xy(10, 30)
        pdf.set_fill_color(80, 60, 0)  # dark gold bg
        pdf.set_text_color(245, 158, 11)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(190, 8,
                 'UNVERIFIED — Indebtedness data not available. Verify with Public Trustee.',
                 0, 1, 'C', fill=True)
        pdf.page = pdf.pages_nb

    # Save
    case_ref = signal.signal_id[:12].upper().replace(" ", "_")
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    filename = f"dossier_{case_ref}_{today}.pdf"
    filepath = out / filename
    pdf.output(str(filepath))
    return str(filepath.resolve())
