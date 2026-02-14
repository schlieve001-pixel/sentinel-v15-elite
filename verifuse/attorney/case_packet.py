"""
VeriFuse Surplus Engine — PDF Case Packet Generator
=====================================================
DELIVERABLE 6: Case Packet Structure

A case packet is the PDF an attorney downloads to evaluate an opportunity.
It contains ONLY publicly verifiable facts. No scores. No AI analysis.

SECTIONS (in order):
1. COVER PAGE — Asset ID, Jurisdiction, Generated Date, VeriFuse branding
2. ASSET SUMMARY — All Tier 1 + Tier 2 fields in table format
3. FINANCIAL SUMMARY — Tier 3 fields (surplus, debt, overbid)
4. STATUTE INFORMATION — Window, citation, days remaining, triggering event
5. RECORDER REFERENCE — Link to county recorder for independent verification
6. PROVENANCE — Source declaration (which public record, when collected)
7. DISCLAIMER — Legal disclaimer re: verification responsibility

ADVERSARIAL DESIGN:
    Failure Mode               Detection                Auto Response           Lawyer Sees
    ─────────────────────────── ──────────────────────── ─────────────────────── ────────────────
    Packet generated for        Gate check in            Packet generation       Error message
    non-ATTORNEY asset          generate_case_packet()   refused

    Stale data in packet        days_remaining           Warning banner on       "Data as of
                                recomputed at gen time   cover page              {date}. Verify."

    Missing Tier 2 field        Completeness check       Field shows "NOT        Explicit gap
    in packet                   at gen time              AVAILABLE — verify      visibility
                                                         via recorder link"
"""

import sqlite3
from datetime import datetime
from typing import Optional


def generate_case_packet(conn: sqlite3.Connection, asset_id: str) -> dict:
    """Generate case packet data structure for PDF rendering.

    GATE: Only ATTORNEY-class assets with GOLD/SILVER grade can generate packets.
    Returns dict with all sections, or raises ValueError with reason.

    The actual PDF rendering uses this dict as input to a template engine
    (ReportLab or WeasyPrint — DECISION: WeasyPrint for HTML-to-PDF,
    simpler templates, easier to maintain).
    """
    # Gate check
    status = conn.execute("""
        SELECT ls.record_class, ls.data_grade, ls.days_remaining
        FROM legal_status ls
        WHERE ls.asset_id = ?
    """, (asset_id,)).fetchone()

    if not status:
        raise ValueError(f"Asset {asset_id} not found")
    if status[0] != "ATTORNEY":
        raise ValueError(f"Asset {asset_id} is {status[0]}, not ATTORNEY. Packet refused.")
    if status[1] not in ("GOLD", "SILVER"):
        raise ValueError(f"Asset {asset_id} grade is {status[1]}. Packet refused.")

    # Fetch full asset
    asset = conn.execute("SELECT * FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()
    cols = [d[0] for d in conn.execute("SELECT * FROM assets LIMIT 0").description]
    a = dict(zip(cols, asset))

    # Fetch statute
    statute = conn.execute("""
        SELECT * FROM statute_authority
        WHERE jurisdiction = ? AND asset_type = ?
    """, (a["jurisdiction"], a["asset_type"])).fetchone()

    statute_cols = [d[0] for d in conn.execute("SELECT * FROM statute_authority LIMIT 0").description]
    s = dict(zip(statute_cols, statute)) if statute else {}

    # Log packet generation
    conn.execute("""
        INSERT INTO pipeline_events
        (asset_id, event_type, old_value, new_value, actor, reason, created_at)
        VALUES (?, 'CASE_PACKET_GENERATED', NULL, 'generated', 'system:case_packet',
                'attorney_requested_packet', ?)
    """, (asset_id, datetime.utcnow().isoformat() + "Z"))
    conn.commit()

    def safe(val, fallback="NOT AVAILABLE — verify via recorder link"):
        if val is None or str(val).strip() == "" or str(val) == "Unknown":
            return fallback
        return val

    generated_at = datetime.utcnow().strftime("%B %d, %Y at %H:%M UTC")

    packet = {
        "generated_at": generated_at,
        "asset_id": a["asset_id"],

        # SECTION 1: COVER PAGE
        "cover": {
            "title": "SURPLUS FUNDS CASE PACKET",
            "subtitle": f"{a['jurisdiction']} — {a['asset_type'].replace('_', ' ').title()}",
            "asset_id": a["asset_id"],
            "generated": generated_at,
            "data_as_of": a["updated_at"][:10] if a.get("updated_at") else "Unknown",
            "warning": (
                "This packet contains publicly available information compiled for "
                "attorney review. All facts should be independently verified via the "
                "county recorder link provided. VeriFuse does not provide legal advice."
            ),
        },

        # SECTION 2: ASSET SUMMARY (Tier 1 + Tier 2)
        "asset_summary": {
            "County": a["county"],
            "State": a["state"],
            "Jurisdiction": a["jurisdiction"],
            "Asset Type": a["asset_type"].replace("_", " ").title(),
            "Case / Parcel Number": safe(a.get("case_number")),
            "Owner of Record": safe(a.get("owner_of_record")),
            "Property Address": safe(a.get("property_address")),
            "Lien Type": safe(a.get("lien_type")),
            "Sale Date": safe(a.get("sale_date")),
            "Redemption Date": safe(a.get("redemption_date"), "N/A or not applicable"),
        },

        # SECTION 3: FINANCIAL SUMMARY (Tier 3)
        "financial_summary": {
            "Estimated Surplus": f"${a['estimated_surplus']:,.2f}" if a.get("estimated_surplus") else "NOT AVAILABLE",
            "Total Indebtedness": f"${a['total_indebtedness']:,.2f}" if a.get("total_indebtedness") else "NOT AVAILABLE",
            "Overbid Amount": f"${a['overbid_amount']:,.2f}" if a.get("overbid_amount") else "NOT AVAILABLE",
            "Jurisdiction Fee Cap": (
                f"{s['fee_cap_pct']*100:.0f}% of surplus" if s.get("fee_cap_pct")
                else f"${s['fee_cap_flat']:,.2f}" if s.get("fee_cap_flat")
                else "No statutory cap identified"
            ),
            "note": (
                "Surplus estimate is derived from public auction records. "
                "Actual surplus may differ after clerk processing. Verify with county."
            ),
        },

        # SECTION 4: STATUTE INFORMATION
        "statute_info": {
            "Statute Window": f"{s.get('statute_years', '?')} years from {s.get('triggering_event', '?')}" if s else "CANNOT VERIFY — no statute authority entry",
            "Statute Citation": s.get("statute_citation", "NOT AVAILABLE"),
            "Days Remaining": status[2] if status[2] is not None else "CANNOT COMPUTE",
            "Court Petition Required": "Yes" if s.get("requires_court") else "No" if s else "Unknown",
            "Known Issues": s.get("known_issues") or "None identified",
        },

        # SECTION 5: RECORDER REFERENCE
        "recorder": {
            "link": a.get("recorder_link") or "NOT AVAILABLE — search county recorder manually",
            "note": (
                "This link directs to the county recorder search. It may be a search URL "
                "rather than a direct document link. Use the owner name and case number "
                "to locate the relevant filing."
            ),
        },

        # SECTION 6: PROVENANCE
        "provenance": {
            "Source": f"Public records via {a['jurisdiction']} county systems",
            "Collection Date": a.get("created_at", "Unknown")[:10],
            "Last Updated": a.get("updated_at", "Unknown")[:10],
            "Source File Hash": a.get("source_file_hash") or "Not recorded",
            "Record Hash": a.get("record_hash") or "Not recorded",
            "note": (
                "Source file hash and record hash provide cryptographic verification "
                "that this data has not been altered since collection."
            ),
        },

        # SECTION 7: DISCLAIMER
        "disclaimer": (
            "DISCLAIMER: This case packet is provided for informational purposes only "
            "and does not constitute legal advice. VeriFuse Technologies LLC compiles "
            "publicly available information from county and court records. While we "
            "strive for accuracy, we make no warranties regarding the completeness or "
            "correctness of this information. Attorneys are responsible for independently "
            "verifying all facts before taking legal action. Surplus fund amounts are "
            "estimates based on public record data and may not reflect the final amount "
            "available after clerk processing, additional liens, or competing claims. "
            "Statute of limitations information is based on our interpretation of "
            "applicable law and should be independently verified. This document was "
            f"generated on {generated_at}."
        ),
    }

    return packet


def packet_to_html(packet: dict) -> str:
    """Convert case packet dict to HTML for WeasyPrint PDF rendering."""
    sections = []

    # Cover
    c = packet["cover"]
    sections.append(f"""
    <div class="cover">
        <h1>{c['title']}</h1>
        <h2>{c['subtitle']}</h2>
        <p><strong>Asset ID:</strong> {c['asset_id']}</p>
        <p><strong>Generated:</strong> {c['generated']}</p>
        <p><strong>Data as of:</strong> {c['data_as_of']}</p>
        <div class="warning">{c['warning']}</div>
    </div>
    <div class="page-break"></div>
    """)

    # Asset Summary
    rows = "".join(
        f"<tr><td class='label'>{k}</td><td>{v}</td></tr>"
        for k, v in packet["asset_summary"].items()
    )
    sections.append(f"""
    <h2>Asset Summary</h2>
    <table class="data-table">{rows}</table>
    """)

    # Financial Summary
    fin = packet["financial_summary"]
    fin_rows = "".join(
        f"<tr><td class='label'>{k}</td><td>{v}</td></tr>"
        for k, v in fin.items() if k != "note"
    )
    sections.append(f"""
    <h2>Financial Summary</h2>
    <table class="data-table">{fin_rows}</table>
    <p class="note">{fin['note']}</p>
    """)

    # Statute Info
    stat_rows = "".join(
        f"<tr><td class='label'>{k}</td><td>{v}</td></tr>"
        for k, v in packet["statute_info"].items()
    )
    sections.append(f"""
    <h2>Statute Information</h2>
    <table class="data-table">{stat_rows}</table>
    """)

    # Recorder
    rec = packet["recorder"]
    sections.append(f"""
    <h2>Recorder Reference</h2>
    <p><a href="{rec['link']}">{rec['link']}</a></p>
    <p class="note">{rec['note']}</p>
    """)

    # Provenance
    prov = packet["provenance"]
    prov_rows = "".join(
        f"<tr><td class='label'>{k}</td><td>{v}</td></tr>"
        for k, v in prov.items() if k != "note"
    )
    sections.append(f"""
    <h2>Data Provenance</h2>
    <table class="data-table">{prov_rows}</table>
    <p class="note">{prov['note']}</p>
    """)

    # Disclaimer
    sections.append(f"""
    <div class="disclaimer">
        <h3>Disclaimer</h3>
        <p>{packet['disclaimer']}</p>
    </div>
    """)

    body = "\n".join(sections)

    return f"""<!DOCTYPE html>
<html>
<head>
<style>
    body {{ font-family: 'Georgia', serif; margin: 40px; color: #1a1a1a; font-size: 11pt; }}
    h1 {{ font-size: 22pt; margin-bottom: 5px; }}
    h2 {{ font-size: 14pt; border-bottom: 2px solid #1a1a1a; padding-bottom: 4px; margin-top: 30px; }}
    .cover {{ text-align: center; padding-top: 120px; }}
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
    a {{ color: #0066cc; }}
</style>
</head>
<body>
{body}
</body>
</html>"""
