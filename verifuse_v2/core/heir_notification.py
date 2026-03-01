"""
VeriFuse — Heir Notification Letter Template Generator
=======================================================
Generates a DRAFT TEMPLATE for an heir notification letter.

THIS IS A TEMPLATE ONLY. The generated PDF is a blank-form document
that an attorney must customize, review, sign, and mail on their own
letterhead. VeriFuse makes no legal representations. All legal
determinations (entitlement, filing deadlines, fee agreements, etc.)
are the sole responsibility of the attorney using this tool.

Usage:
  from verifuse_v2.core.heir_notification import generate_heir_notification_pdf
  pdf_bytes = generate_heir_notification_pdf(
      owner_name="John Doe",
      property_address="123 Main St, Jefferson County, CO",
      county="Jefferson",
      case_number="J2400300",
      surplus_amount=45000.00,
      sale_date="2024-03-15",
      mailing_address="456 Oak Ave, Denver, CO 80203",
  )
"""

from __future__ import annotations

import io
import logging
from datetime import date, datetime
from typing import Optional

log = logging.getLogger(__name__)


def _format_currency(amount: float) -> str:
    """Format a float as $X,XXX.XX."""
    return f"${amount:,.2f}"


def _format_date(date_str: str) -> str:
    """Format a YYYY-MM-DD date string to readable form."""
    if not date_str:
        return "[date unknown]"
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(date_str[:10], fmt[:len(date_str[:10])]).strftime("%B %d, %Y")
        except (ValueError, TypeError):
            pass
    return date_str


def generate_heir_notification_pdf(
    owner_name: str,
    property_address: str,
    county: str,
    case_number: str,
    surplus_amount: float,
    sale_date: str,
    mailing_address: Optional[str] = None,
    attorney_name: str = "[Attorney Name]",
    attorney_bar: str = "[Bar #]",
    attorney_firm: str = "[Firm Name]",
    attorney_address: str = "[Firm Address]",
    attorney_phone: str = "[Phone]",
    attorney_email: str = "[Email]",
) -> bytes:
    """Generate a PDF heir notification TEMPLATE using reportlab.

    Returns PDF bytes. Raises ImportError if reportlab is not installed.

    THIS IS A BLANK TEMPLATE. The attorney must:
    - Replace all bracketed [placeholder] fields
    - Add their own letterhead
    - Review and approve all content
    - Sign and mail the final letter

    Args:
        owner_name:       Name of the owner of record at time of foreclosure
        property_address: Property address that was foreclosed
        county:           Colorado county name
        case_number:      Foreclosure case number
        surplus_amount:   Dollar amount of surplus (reference data only)
        sale_date:        Foreclosure sale date (YYYY-MM-DD or ISO string)
        mailing_address:  Mailing address for the letter. May be None.
        attorney_*:       Optional attorney info. Defaults to blank placeholders.

    Returns:
        bytes: PDF file content
    """
    try:
        from reportlab.lib.pagesizes import letter  # type: ignore[import]
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle  # type: ignore[import]
        from reportlab.lib.units import inch  # type: ignore[import]
        from reportlab.lib.enums import TA_LEFT, TA_CENTER  # type: ignore[import]
        from reportlab.platypus import (  # type: ignore[import]
            SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle,
        )
        from reportlab.lib import colors  # type: ignore[import]
    except ImportError as e:
        log.error("[heir_notification] reportlab not installed: %s", e)
        raise ImportError(
            "reportlab is required for PDF generation. pip install reportlab"
        ) from e

    buf = io.BytesIO()

    # ── Watermark callback ─────────────────────────────────────────────────────
    def _add_watermark(canvas_obj, doc):
        canvas_obj.saveState()
        canvas_obj.setFont("Helvetica-Bold", 36)
        canvas_obj.setFillColorRGB(0.85, 0.85, 0.85, alpha=0.5)
        canvas_obj.translate(4.25 * inch, 5.5 * inch)
        canvas_obj.rotate(45)
        canvas_obj.drawCentredString(0, 0, "DRAFT TEMPLATE")
        canvas_obj.restoreState()

    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=1 * inch,
        leftMargin=1 * inch,
        topMargin=1 * inch,
        bottomMargin=1 * inch,
    )

    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    normal.fontName = "Times-Roman"
    normal.fontSize = 11
    normal.leading = 16

    heading_style = ParagraphStyle(
        "Heading",
        fontName="Times-Bold",
        fontSize=11,
        leading=16,
        spaceAfter=4,
    )
    small_style = ParagraphStyle(
        "Small",
        fontName="Times-Roman",
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#555555"),
    )
    blank_style = ParagraphStyle(
        "Blank",
        fontName="Times-Italic",
        fontSize=11,
        leading=16,
        textColor=colors.HexColor("#888888"),
    )
    warning_style = ParagraphStyle(
        "Warning",
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#cc0000"),
        spaceBefore=4,
        spaceAfter=4,
    )

    today = date.today().strftime("%B %d, %Y")
    sale_date_formatted = _format_date(sale_date)
    surplus_formatted = _format_currency(surplus_amount)

    # Public Trustee contact info by county
    PUBLIC_TRUSTEE_CONTACTS = {
        "jefferson": ("Jefferson County Public Trustee", "100 Jefferson County Pkwy, Golden, CO 80419", "(303) 271-8580"),
        "arapahoe":  ("Arapahoe County Public Trustee", "5334 S. Prince St., Littleton, CO 80120", "(303) 795-4550"),
        "adams":     ("Adams County Public Trustee", "4430 S. Adams County Pkwy, Brighton, CO 80601", "(720) 523-6160"),
        "denver":    ("Denver City and County Public Trustee", "201 W. Colfax Ave, Denver, CO 80202", "(720) 913-4610"),
        "boulder":   ("Boulder County Public Trustee", "1750 33rd St., Boulder, CO 80301", "(303) 441-3520"),
        "douglas":   ("Douglas County Public Trustee", "301 Wilcox St., Castle Rock, CO 80104", "(303) 660-7440"),
        "el_paso":   ("El Paso County Public Trustee", "1675 Garden of the Gods Rd., Colorado Springs, CO 80907", "(719) 520-7230"),
        "larimer":   ("Larimer County Public Trustee", "200 W. Oak St., Fort Collins, CO 80521", "(970) 498-7020"),
        "weld":      ("Weld County Public Trustee", "1150 O St., Greeley, CO 80631", "(970) 400-4370"),
    }
    county_lower = county.lower().replace(" ", "_")
    pt_name, pt_address, pt_phone = PUBLIC_TRUSTEE_CONTACTS.get(
        county_lower, (
            f"{county} County Public Trustee",
            f"{county} County Courthouse",
            "See county website",
        )
    )

    story = []

    # ── Template Banner ─────────────────────────────────────────────────────────
    story.append(Paragraph(
        "⚠ DRAFT TEMPLATE — ATTORNEY MUST REVIEW, CUSTOMIZE, AND SIGN BEFORE USE — NOT LEGAL ADVICE",
        warning_style,
    ))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#cc0000")))
    story.append(Spacer(1, 0.1 * inch))

    # ── Attorney Letterhead Placeholder ──
    story.append(Paragraph(
        "[ATTORNEY LETTERHEAD — Replace this block with your firm letterhead before printing]",
        ParagraphStyle("Placeholder", fontName="Times-Italic", fontSize=10,
                       textColor=colors.HexColor("#888888"), leading=14, spaceAfter=2),
    ))
    story.append(Paragraph(f"{attorney_firm}", heading_style))
    story.append(Paragraph(f"{attorney_address}", normal))
    story.append(Paragraph(f"{attorney_phone} | {attorney_email}", normal))
    story.append(Paragraph(f"Colorado Bar No. {attorney_bar}", normal))
    story.append(Spacer(1, 0.15 * inch))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))
    story.append(Spacer(1, 0.15 * inch))

    # ── Date + Addressee ──
    story.append(Paragraph(today, normal))
    story.append(Spacer(1, 0.15 * inch))

    if mailing_address:
        story.append(Paragraph(f"Estate of {owner_name}", heading_style))
        story.append(Paragraph(mailing_address, normal))
    else:
        story.append(Paragraph(f"Estate of {owner_name}", heading_style))
        story.append(Paragraph("[Mailing address — verify with county assessor records]", blank_style))
    story.append(Spacer(1, 0.2 * inch))

    # ── Re: Line ──
    story.append(Paragraph(
        f"<b>Re: [ATTORNEY TO CUSTOMIZE] — {county} County Case No. {case_number}<br/>"
        f"Reference: {owner_name} — Surplus Reference Amount: {surplus_formatted}</b>",
        heading_style,
    ))
    story.append(Spacer(1, 0.15 * inch))

    # ── Salutation ──
    story.append(Paragraph("[Dear ___________:]", blank_style))
    story.append(Spacer(1, 0.1 * inch))

    # ── Case Reference Data Box ─────────────────────────────────────────────────
    story.append(Paragraph("<b>Case Reference Data (from VeriFuse — verify independently before use):</b>", heading_style))
    ref_data = [
        ["County:", f"{county} County, Colorado"],
        ["Case Number:", case_number],
        ["Property Address:", property_address or "[see county records]"],
        ["Sale Date:", sale_date_formatted],
        ["Surplus Reference Amount:", surplus_formatted],
        ["Public Trustee:", pt_name],
        ["PT Address:", pt_address],
        ["PT Phone:", pt_phone],
    ]
    ref_table = Table(ref_data, colWidths=[2.0 * inch, 4.5 * inch])
    ref_table.setStyle(TableStyle([
        ("FONTNAME",  (0, 0), (0, -1), "Times-Bold"),
        ("FONTNAME",  (1, 0), (1, -1), "Times-Roman"),
        ("FONTSIZE",  (0, 0), (-1, -1), 10),
        ("LEADING",   (0, 0), (-1, -1), 14),
        ("VALIGN",    (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.HexColor("#f9f9f9"), colors.white]),
        ("LEFTPADDING",  (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING",   (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#eeeeee")),
    ]))
    story.append(ref_table)
    story.append(Spacer(1, 0.2 * inch))

    # ── Body — fill-in blanks ───────────────────────────────────────────────────
    story.append(Paragraph("<b>Letter Body — Attorney Must Draft:</b>", heading_style))
    story.append(Spacer(1, 0.05 * inch))

    fill_in_sections = [
        "[Opening paragraph: Identify yourself and the purpose of the letter. "
        "Reference the foreclosure case and property address above.]",

        "[Paragraph 2: Describe the surplus situation. Use the reference data above. "
        "Attorney must independently verify amounts with the Public Trustee before stating as fact.]",

        "[Paragraph 3: Explain the claim process and relevant deadlines. "
        "Attorney must confirm applicable statutes and deadlines with current Colorado law.]",

        "[Paragraph 4: Describe your services and fee arrangement, if any. "
        "Attorney is responsible for compliance with all applicable fee cap statutes and bar rules.]",

        "[Paragraph 5: Call to action and contact information.]",

        "[Closing disclaimer — attorney to draft per their firm's standard language.]",
    ]

    for section in fill_in_sections:
        story.append(Paragraph(section, blank_style))
        story.append(Spacer(1, 0.15 * inch))

    # ── Closing ──
    story.append(Paragraph("Respectfully,", normal))
    story.append(Spacer(1, 0.5 * inch))
    story.append(Paragraph(f"____________________________", normal))
    story.append(Paragraph(f"{attorney_name}", normal))
    story.append(Paragraph(f"{attorney_firm}", normal))
    story.append(Paragraph(f"Colorado Bar No. {attorney_bar}", normal))
    story.append(Spacer(1, 0.2 * inch))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))

    # ── Footer ─────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph(
        "GENERATED BY VERIFUSE INTELLIGENCE PLATFORM · DRAFT TEMPLATE ONLY · "
        "ATTORNEY MUST REVIEW AND CUSTOMIZE · NOT LEGAL ADVICE",
        small_style,
    ))
    story.append(Paragraph(
        f"Case: {case_number} | County: {county} | Sale: {sale_date_formatted} | "
        f"Surplus Ref: {surplus_formatted} | Generated: {today}",
        small_style,
    ))

    doc.build(story, onFirstPage=_add_watermark, onLaterPages=_add_watermark)
    return buf.getvalue()
