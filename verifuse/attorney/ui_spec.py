"""
VeriFuse Surplus Engine — Attorney UI Specification
=====================================================
DELIVERABLE 4: Attorney UX Contract

PRINCIPLE: If a lawyer cannot answer "Can I act on this today?" within 10 seconds,
the UX has failed.

DOMAIN: attorney.verifuse.tech (no shared auth with internal.verifuse.tech)

WHAT ATTORNEYS SEE:
    - County, Jurisdiction, Asset ID, Asset Type
    - Estimated Surplus, Days Remaining, Statute Window
    - Recorder Link, Status
    - Owner of Record, Property Address, Sale Date, Case Number
    - Three buttons: Download Case Packet, Mark Interested, Archive

WHAT ATTORNEYS NEVER SEE (UX CONTRACT):
    - Completeness Score
    - Confidence Score
    - Risk Score
    - Data Grade (GOLD/SILVER/BRONZE/REJECT)
    - Record Class transitions
    - Pipeline events
    - Source scraper names
    - Source file hashes
    - Internal priority
    - Any field from Tier 4
    - Any Airtable table names or IDs
    - Any internal jargon (e.g. "kill switch", "gate condition")
    - Any scoring formulas
    - Any mention of automation logic

ADVERSARIAL DESIGN:
    Failure Mode                How Detected              Auto Response           Lawyer Sees
    ─────────────────────────── ──────────────────────────  ──────────────────────  ─────────────────
    Expired statute shown       days_remaining <= 0        Asset removed from      Nothing (gone)
                                in attorney_view           view, CLOSED class

    Incomplete Tier 2 shown     completeness < 1.0 in      Asset blocked from      Nothing (not shown)
                                ATTORNEY promotion gate    attorney_view

    Surplus estimate wrong      No auto-detection          Recorder link provided  Link to verify
                                                           for attorney to verify  themselves

    County data is stale        scraper last_run > 2x      Asset demoted to        Asset disappears
                                update_frequency           QUALIFIED               from view

    Attorney sees internal      attorney_view SQL          View query excludes     Impossible by
    scores                      excludes Tier 4            all Tier 4 fields       construction

LEGAL HOSTILITY TEST:
    Q: "Why was this asset shown to my client?"
    A: Because it met all ATTORNEY class gate conditions:
       - Full Tier 2 data present (completeness = 1.0)
       - Data grade GOLD or SILVER (verified source, recent data)
       - Statute window has > 0 days remaining
       - Jurisdiction has verified statute authority entry
       All transitions are logged in pipeline_events with timestamps and reasons.

    Q: "Why is the surplus estimate non-deceptive?"
    A: The estimate is derived from public record data (bid - judgment or official
       surplus posting). The recorder link is provided so the attorney can independently
       verify. We do not adjust, inflate, or "AI-enhance" surplus figures.

    Q: "Was any material fact hidden?"
    A: No. All Tier 2 fields (legally material) are displayed. Tier 4 fields (internal
       routing scores) are not material facts — they are operational metadata that would
       confuse rather than inform legal analysis.
"""

import sqlite3
from typing import Optional


# ============================================================================
# ATTORNEY DASHBOARD COLUMNS (exactly these, in this order)
# ============================================================================

DASHBOARD_COLUMNS = [
    {"field": "county",            "label": "County",           "why": "Jurisdiction"},
    {"field": "jurisdiction",      "label": "Jurisdiction",     "why": "Jurisdiction + State"},
    {"field": "asset_id",          "label": "Asset ID",         "why": "Reference"},
    {"field": "asset_type",        "label": "Asset Type",       "why": "Context"},
    {"field": "estimated_surplus", "label": "Est. Surplus",     "why": "Incentive",
     "format": "currency"},
    {"field": "days_remaining",    "label": "Days Remaining",   "why": "Urgency",
     "format": "integer"},
    {"field": "statute_window",    "label": "Statute Window",   "why": "Legal reality"},
    {"field": "recorder_link",     "label": "Recorder Link",    "why": "Proof",
     "format": "url"},
    {"field": "status",            "label": "Status",           "why": "Can I act?"},
    {"field": "owner_of_record",   "label": "Owner of Record",  "why": "Party identification"},
    {"field": "property_address",  "label": "Property Address", "why": "Asset location"},
    {"field": "sale_date",         "label": "Sale Date",        "why": "Timeline"},
    {"field": "case_number",       "label": "Case Number",      "why": "Court reference"},
]

# Buttons (exactly three)
DASHBOARD_BUTTONS = [
    {"id": "download_packet", "label": "Download Case Packet", "action": "generate_pdf"},
    {"id": "mark_interested", "label": "Mark Interested",      "action": "mark_interest"},
    {"id": "archive",         "label": "Archive",              "action": "archive_asset"},
]


def get_attorney_dashboard(conn: sqlite3.Connection,
                           jurisdiction_filter: Optional[str] = None,
                           sort_by: str = "days_remaining",
                           sort_asc: bool = True) -> list:
    """Fetch attorney-visible assets. Returns list of dicts with ONLY dashboard columns.

    This function is the ONLY data path to the attorney UI.
    It queries the attorney_view (which already filters to ATTORNEY class,
    days > 0, and GOLD/SILVER grade).
    """
    query = "SELECT * FROM attorney_view"
    params = []

    if jurisdiction_filter:
        query += " WHERE jurisdiction = ?"
        params.append(jurisdiction_filter)

    # Override the view's default ORDER BY
    direction = "ASC" if sort_asc else "DESC"
    query = f"""
        SELECT county, jurisdiction, asset_id, asset_type,
               estimated_surplus, days_remaining, statute_window,
               recorder_link, status, owner_of_record, property_address,
               sale_date, case_number
        FROM attorney_view
        {"WHERE jurisdiction = ?" if jurisdiction_filter else ""}
        ORDER BY {sort_by} {direction}
    """

    rows = conn.execute(query, params).fetchall()

    result = []
    for row in rows:
        asset = {}
        for i, col in enumerate(DASHBOARD_COLUMNS):
            value = row[i]
            if col.get("format") == "currency" and value is not None:
                asset[col["field"]] = f"${value:,.2f}"
                asset[f"_{col['field']}_raw"] = value
            elif col.get("format") == "integer" and value is not None:
                asset[col["field"]] = int(value)
            else:
                asset[col["field"]] = value
        result.append(asset)

    return result


def get_available_jurisdictions(conn: sqlite3.Connection) -> list:
    """Get jurisdictions that have ATTORNEY-class assets (for filter dropdown)."""
    rows = conn.execute(
        "SELECT DISTINCT jurisdiction FROM attorney_view ORDER BY jurisdiction"
    ).fetchall()
    return [r[0] for r in rows]
