"""
VeriFuse V2 — Case Packet Generator (HTML)
============================================
Generates an HTML case packet for attorney review.

Ported from V1 verifuse/attorney/case_packet.py with changes:
  - Queries `leads` table (not `assets`)
  - Gate: data_grade IN ('GOLD', 'SILVER') + attorney_packet_ready = 1
  - HTML output (primary deliverable)
  - Logs to pipeline_events

Usage:
    python -m verifuse_v2.attorney.case_packet --lead-id <LEAD_ID>
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "case_packets"


def _safe_fmt(val, fallback="NOT AVAILABLE — verify via recorder link"):
    if val is None or str(val).strip() == "" or str(val).strip().lower() in ("unknown", "n/a"):
        return fallback
    return val


def _fmt_money(amount) -> str:
    if amount is None:
        return "NOT AVAILABLE"
    try:
        return f"${float(amount):,.2f}"
    except (ValueError, TypeError):
        return str(amount)


def generate_case_packet(db_path: str, lead_id: str, output_dir: str = None) -> str:
    """Generate an HTML case packet for an attorney-ready lead.

    Gate: data_grade IN ('GOLD', 'SILVER') AND attorney_packet_ready = 1

    Args:
        db_path: Path to the SQLite database.
        lead_id: The lead ID.
        output_dir: Directory to save. Defaults to data/case_packets/.

    Returns:
        Path to the generated HTML file.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", [lead_id]).fetchone()
        if not row:
            raise ValueError(f"Lead {lead_id} not found")

        lead = dict(row)

        # Gate check
        grade = lead.get("data_grade", "")
        packet_ready = lead.get("attorney_packet_ready", 0)
        if grade not in ("GOLD", "SILVER"):
            raise ValueError(f"Lead {lead_id} grade is {grade}. Must be GOLD or SILVER.")
        if not packet_ready:
            raise ValueError(f"Lead {lead_id} is not attorney_packet_ready.")

        # Log packet generation
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("""
            INSERT INTO pipeline_events
            (asset_id, event_type, old_value, new_value, actor, reason, created_at)
            VALUES (?, 'CASE_PACKET_GENERATED', NULL, 'generated', 'system:case_packet',
                    'attorney_requested_packet', ?)
        """, [lead_id, now])
        conn.commit()
    finally:
        conn.close()

    generated_at = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")
    surplus = lead.get("surplus_amount") or lead.get("estimated_surplus") or 0

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Case Packet — {lead.get('case_number', lead_id)}</title>
<style>
    body {{ font-family: 'Georgia', serif; margin: 40px; color: #1a1a1a; font-size: 11pt; }}
    h1 {{ font-size: 22pt; margin-bottom: 5px; }}
    h2 {{ font-size: 14pt; border-bottom: 2px solid #1a1a1a; padding-bottom: 4px; margin-top: 30px; }}
    .cover {{ text-align: center; padding-top: 80px; }}
    .cover h1 {{ font-size: 28pt; }}
    .cover h2 {{ border: none; font-size: 16pt; color: #555; }}
    .warning {{ background: #fff3cd; border: 1px solid #ffc107; padding: 12px; margin-top: 30px;
                font-size: 10pt; text-align: left; }}
    .data-table {{ width: 100%; border-collapse: collapse; margin: 10px 0; }}
    .data-table td {{ padding: 6px 10px; border-bottom: 1px solid #ddd; vertical-align: top; }}
    .data-table .label {{ font-weight: bold; width: 35%; background: #f8f9fa; }}
    .note {{ font-size: 9pt; color: #666; font-style: italic; margin-top: 5px; }}
    .disclaimer {{ background: #f0f0f0; padding: 15px; margin-top: 40px; font-size: 9pt;
                   border: 1px solid #ccc; }}
    .disclaimer h3 {{ margin-top: 0; font-size: 11pt; }}
    .page-break {{ page-break-after: always; }}
    .surplus {{ color: #00803E; font-size: 18pt; font-weight: bold; }}
    .badge {{ display: inline-block; padding: 2px 8px; border-radius: 3px;
              font-size: 10pt; font-weight: bold; }}
    .badge-gold {{ background: #ffd700; color: #333; }}
    .badge-silver {{ background: #c0c0c0; color: #333; }}
</style>
</head>
<body>

<div class="cover">
    <h1>SURPLUS FUNDS CASE PACKET</h1>
    <h2>{_safe_fmt(lead.get('county'), 'Unknown')} County, Colorado — Foreclosure Surplus</h2>
    <p><strong>Lead ID:</strong> {lead_id}</p>
    <p><strong>Generated:</strong> {generated_at}</p>
    <p><strong>Data as of:</strong> {str(lead.get('updated_at', 'Unknown'))[:10]}</p>
    <p><span class="badge badge-{grade.lower()}">{grade}</span></p>
    <div class="warning">
        This packet contains publicly available information compiled for
        attorney review. All facts should be independently verified via the
        county recorder. VeriFuse does not provide legal advice.
    </div>
</div>

<div class="page-break"></div>

<h2>Lead Summary</h2>
<table class="data-table">
    <tr><td class="label">County</td><td>{_safe_fmt(lead.get('county'))}</td></tr>
    <tr><td class="label">Case Number</td><td>{_safe_fmt(lead.get('case_number'))}</td></tr>
    <tr><td class="label">Owner of Record</td><td>{_safe_fmt(lead.get('owner_name'))}</td></tr>
    <tr><td class="label">Property Address</td><td>{_safe_fmt(lead.get('property_address'))}</td></tr>
    <tr><td class="label">Sale Date</td><td>{_safe_fmt(lead.get('sale_date'))}</td></tr>
    <tr><td class="label">Claim Deadline</td><td>{_safe_fmt(lead.get('claim_deadline'), 'N/A')}</td></tr>
</table>

<h2>Financial Summary</h2>
<table class="data-table">
    <tr><td class="label">Surplus Amount</td><td class="surplus">{_fmt_money(surplus)}</td></tr>
    <tr><td class="label">Winning Bid</td><td>{_fmt_money(lead.get('winning_bid'))}</td></tr>
    <tr><td class="label">Total Debt</td><td>{_fmt_money(lead.get('total_debt'))}</td></tr>
    <tr><td class="label">Overbid Amount</td><td>{_fmt_money(lead.get('overbid_amount'))}</td></tr>
    <tr><td class="label">Fee Cap</td><td>C.R.S. § 38-38-111(2.5)(c): Compensation agreements void during holding period</td></tr>
</table>
<p class="note">Surplus estimate is derived from public auction records.
    Actual surplus may differ after clerk processing. Verify with county.</p>

<h2>Statute Information</h2>
<table class="data-table">
    <tr><td class="label">Statute Window Status</td><td>{_safe_fmt(lead.get('statute_window_status'), 'UNKNOWN')}</td></tr>
    <tr><td class="label">Statute Citation</td><td>C.R.S. § 38-38-111</td></tr>
    <tr><td class="label">Data Grade</td><td>{_safe_fmt(lead.get('data_grade'))}</td></tr>
    <tr><td class="label">Confidence Score</td><td>{lead.get('confidence_score', 0):.0%}</td></tr>
</table>

<h2>Data Provenance</h2>
<table class="data-table">
    <tr><td class="label">Source</td><td>Public records — {_safe_fmt(lead.get('county'), 'N/A')} County, CO</td></tr>
    <tr><td class="label">Last Updated</td><td>{str(lead.get('updated_at', 'Unknown'))[:10]}</td></tr>
    <tr><td class="label">Source Name</td><td>{_safe_fmt(lead.get('source_name'), 'VeriFuse automated collection')}</td></tr>
</table>

<div class="disclaimer">
    <h3>Disclaimer</h3>
    <p>
        This case packet is provided for informational purposes only and does not
        constitute legal advice. VeriFuse Technologies LLC compiles publicly available
        information from county and court records. While we strive for accuracy, we make
        no warranties regarding the completeness or correctness of this information.
        Attorneys are responsible for independently verifying all facts before taking
        legal action. This document was generated on {generated_at}.
    </p>
</div>

</body>
</html>"""

    out_dir = Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    county_clean = (lead.get("county") or "UNK").replace(" ", "_")
    short_id = str(lead_id)[:12]
    filename = f"VF_PACKET_{county_clean}_{short_id}.html"
    filepath = out_dir / filename

    filepath.write_text(html, encoding="utf-8")
    return str(filepath)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate HTML case packet")
    parser.add_argument("--lead-id", required=True, help="Lead ID")
    parser.add_argument("--db", default=os.environ.get("VERIFUSE_DB_PATH"),
                        help="Path to database")
    parser.add_argument("--output-dir", default=None, help="Output directory")
    args = parser.parse_args()

    if not args.db:
        print("FATAL: --db or VERIFUSE_DB_PATH required")
        sys.exit(1)

    path = generate_case_packet(args.db, args.lead_id, args.output_dir)
    print(f"Case packet generated: {path}")
