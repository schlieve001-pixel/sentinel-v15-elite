"""
VERIFUSE V2 — Engine 4: Motion PDF Generator

Generates a "Motion for Disbursement of Surplus Funds" PDF using FPDF.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from fpdf import FPDF

from verifuse_v2.contracts.schemas import EntityRecord, OutcomeRecord

PDF_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "motions"


class MotionPDF(FPDF):
    """Court motion PDF with Denver District Court header."""

    def header(self) -> None:
        self.set_font("Helvetica", "B", 14)
        self.cell(0, 8, "DISTRICT COURT, DENVER COUNTY, COLORADO", align="C", ln=True)
        self.set_font("Helvetica", "", 10)
        self.cell(0, 6, "Second Judicial District", align="C", ln=True)
        self.ln(4)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(6)

    def footer(self) -> None:
        self.set_y(-20)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")


def generate_motion(
    outcome: OutcomeRecord,
    entity: EntityRecord,
    plaintiff: str = "THE LENDER",
    output_dir: Path | str | None = None,
) -> str:
    """Create a Motion for Disbursement PDF and return its file path.

    Parameters
    ----------
    outcome : OutcomeRecord
        Must contain gross_amount / net_amount.
    entity : EntityRecord
        Must contain name (defendant).
    plaintiff : str
        Name of the foreclosing party (defaults to generic placeholder).
    output_dir : Path | None
        Override output directory (defaults to data/motions/).

    Returns
    -------
    str
        Absolute path to the generated PDF.
    """
    out = Path(output_dir) if output_dir else PDF_OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)

    owner_name = entity.name or "UNKNOWN OWNER"
    surplus = outcome.net_amount or outcome.gross_amount or 0.0
    case_ref = outcome.signal_id[:12].upper()
    today_str = datetime.now(timezone.utc).strftime("%B %d, %Y")

    pdf = MotionPDF()
    pdf.alias_nb_pages()
    pdf.add_page()

    # ── Caption ──────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(90, 7, f"Plaintiff:  {plaintiff}", ln=True)
    pdf.cell(90, 7, "vs.", ln=True)
    pdf.cell(90, 7, f"Defendant:  {owner_name}", ln=True)
    pdf.ln(2)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(90, 7, f"Case Reference:  {case_ref}", ln=True)
    pdf.ln(6)

    # ── Title ────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "BU", 12)
    pdf.cell(0, 8, "MOTION FOR DISBURSEMENT OF SURPLUS FUNDS", align="C", ln=True)
    pdf.ln(6)

    # ── Body ─────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "", 11)
    body = (
        f"COMES NOW the Defendant, {owner_name}, and moves this Court "
        f"to disburse surplus funds in the amount of ${surplus:,.2f} "
        f"held by the Public Trustee of Denver County following the "
        f"foreclosure sale of the subject property.\n\n"
        f"The Defendant respectfully represents:\n\n"
        f"1. A foreclosure sale was conducted on the subject property, "
        f"resulting in a winning bid that exceeded the total "
        f"indebtedness by ${surplus:,.2f}.\n\n"
        f"2. Pursuant to C.R.S. \u00a7 38-38-111, the surplus funds "
        f"are to be paid to the owner of record at the time of "
        f"foreclosure, or their successors in interest.\n\n"
        f"3. The Defendant is the owner of record and is entitled "
        f"to the disbursement of said surplus funds.\n\n"
        f"WHEREFORE, the Defendant respectfully requests this Court "
        f"enter an Order directing the Public Trustee to disburse "
        f"the surplus funds in the amount of ${surplus:,.2f} to the "
        f"Defendant.\n\n"
        f"Respectfully submitted this {today_str}."
    )
    pdf.multi_cell(0, 6, body)
    pdf.ln(12)

    # ── Signature block ──────────────────────────────────────────────
    pdf.cell(0, 6, "____________________________________", ln=True)
    pdf.cell(0, 6, owner_name, ln=True)
    if entity.mailing_address:
        pdf.cell(0, 6, entity.mailing_address, ln=True)

    filename = f"motion_{case_ref}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.pdf"
    filepath = out / filename
    pdf.output(str(filepath))
    return str(filepath.resolve())
