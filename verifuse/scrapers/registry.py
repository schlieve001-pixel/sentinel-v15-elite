"""
VeriFuse Surplus Engine — Scraper Coverage Map & Registry
==========================================================
DELIVERABLE 2: Scraper Coverage Audit + Field Requirement Matrix

Every scraper MUST register here with its coverage declaration.
A scraper without a registry entry is DISABLED at runtime.

CURRENT STATE (audited from _ARCHIVE_FEB_2026):
- 9 Colorado county scrapers (varying quality)
- 1 Palm Beach County FL scraper (Selenium-based)
- Most scrapers lack: statute_window, days_remaining, lien_type, recorder_link
- No scraper declares its coverage matrix per the spec

This file seeds the registry and provides the runtime gate.
"""

import sqlite3
import json


# ============================================================================
# SCRAPER COVERAGE DECLARATIONS
# ============================================================================
# Audited against existing code in _ARCHIVE_FEB_2026/

SCRAPER_DECLARATIONS = [
    {
        "scraper_name": "denver_foreclosure",
        "jurisdiction": "Denver, CO",
        "record_type": "FORECLOSURE_SURPLUS",
        "fields_collected": [
            "case_number", "property_address", "owner_of_record",
            "estimated_surplus", "sale_date", "overbid_amount"
        ],
        "known_gaps": [
            "lien_type", "total_indebtedness", "redemption_date",
            "recorder_link (generates search URL, not direct link)",
            "statute_window (not computed by scraper)"
        ],
        "update_frequency_days": 7,
        "legal_confidence": "HIGH",
    },
    {
        "scraper_name": "denver_tax",
        "jurisdiction": "Denver, CO",
        "record_type": "TAX_OVERPAYMENT",
        "fields_collected": [
            "case_number", "property_address", "owner_of_record",
            "estimated_surplus"
        ],
        "known_gaps": [
            "sale_date", "lien_type", "total_indebtedness",
            "overbid_amount", "recorder_link", "redemption_date"
        ],
        "update_frequency_days": 14,
        "legal_confidence": "HIGH",
    },
    {
        "scraper_name": "jefferson_foreclosure",
        "jurisdiction": "Jefferson, CO",
        "record_type": "FORECLOSURE_SURPLUS",
        "fields_collected": [
            "case_number", "property_address", "owner_of_record",
            "estimated_surplus", "sale_date", "total_indebtedness",
            "overbid_amount"
        ],
        "known_gaps": [
            "lien_type", "redemption_date",
            "recorder_link (generates eagleweb search URL)"
        ],
        "update_frequency_days": 7,
        "legal_confidence": "HIGH",
    },
    {
        "scraper_name": "arapahoe_foreclosure",
        "jurisdiction": "Arapahoe, CO",
        "record_type": "FORECLOSURE_SURPLUS",
        "fields_collected": [
            "case_number", "property_address", "owner_of_record",
            "estimated_surplus", "overbid_amount"
        ],
        "known_gaps": [
            "sale_date (available but not always parsed)",
            "lien_type", "total_indebtedness", "redemption_date"
        ],
        "update_frequency_days": 7,
        "legal_confidence": "HIGH",
    },
    {
        "scraper_name": "douglas_foreclosure",
        "jurisdiction": "Douglas, CO",
        "record_type": "FORECLOSURE_SURPLUS",
        "fields_collected": [
            "owner_of_record", "estimated_surplus"
        ],
        "known_gaps": [
            "case_number (not in treasurer format)",
            "property_address (not in treasurer format)",
            "sale_date (month-only: Mon-YY format, system assumes 1st)",
            "lien_type", "total_indebtedness", "overbid_amount",
            "recorder_link", "redemption_date"
        ],
        "update_frequency_days": 14,
        "legal_confidence": "MED",
    },
    {
        "scraper_name": "douglas_tax",
        "jurisdiction": "Douglas, CO",
        "record_type": "TAX_OVERPAYMENT",
        "fields_collected": [
            "case_number", "owner_of_record", "estimated_surplus", "sale_date"
        ],
        "known_gaps": [
            "property_address", "lien_type", "total_indebtedness",
            "overbid_amount", "recorder_link", "redemption_date"
        ],
        "update_frequency_days": 14,
        "legal_confidence": "MED",
    },
    {
        "scraper_name": "mesa_foreclosure",
        "jurisdiction": "Mesa, CO",
        "record_type": "FORECLOSURE_SURPLUS",
        "fields_collected": [
            "case_number", "estimated_surplus", "sale_date"
        ],
        "known_gaps": [
            "property_address", "owner_of_record",
            "lien_type", "total_indebtedness", "overbid_amount",
            "recorder_link", "redemption_date"
        ],
        "update_frequency_days": 7,
        "legal_confidence": "HIGH",
    },
    {
        "scraper_name": "eagle_portal",
        "jurisdiction": "Eagle, CO",
        "record_type": "FORECLOSURE_SURPLUS",
        "fields_collected": [
            "case_number", "property_address", "owner_of_record",
            "total_indebtedness", "sale_date"
        ],
        "known_gaps": [
            "estimated_surplus (portal shows debt, not surplus)",
            "overbid_amount", "lien_type", "recorder_link", "redemption_date"
        ],
        "update_frequency_days": 7,
        "legal_confidence": "MED",
    },
    {
        "scraper_name": "teller_govease",
        "jurisdiction": "Teller, CO",
        "record_type": "FORECLOSURE_SURPLUS",
        "fields_collected": [
            "case_number", "property_address", "owner_of_record",
            "estimated_surplus", "sale_date", "total_indebtedness"
        ],
        "known_gaps": [
            "overbid_amount", "lien_type", "recorder_link", "redemption_date"
        ],
        "update_frequency_days": 7,
        "legal_confidence": "MED",
    },
    {
        "scraper_name": "summit_govease",
        "jurisdiction": "Summit, CO",
        "record_type": "FORECLOSURE_SURPLUS",
        "fields_collected": [
            "case_number", "property_address", "owner_of_record",
            "total_indebtedness", "sale_date"
        ],
        "known_gaps": [
            "estimated_surplus", "overbid_amount",
            "lien_type", "recorder_link", "redemption_date"
        ],
        "update_frequency_days": 7,
        "legal_confidence": "MED",
    },
    {
        "scraper_name": "sanmiguel_portal",
        "jurisdiction": "San Miguel, CO",
        "record_type": "FORECLOSURE_SURPLUS",
        "fields_collected": [
            "case_number", "property_address", "owner_of_record",
            "total_indebtedness", "sale_date"
        ],
        "known_gaps": [
            "estimated_surplus", "overbid_amount",
            "lien_type", "recorder_link", "redemption_date"
        ],
        "update_frequency_days": 7,
        "legal_confidence": "MED",
    },
    # ---- PHASE 2 EXPANSION: RealAuction Counties ----
    {
        "scraper_name": "pitkin_foreclosure",
        "jurisdiction": "Pitkin, CO",
        "record_type": "FORECLOSURE_SURPLUS",
        "fields_collected": [
            "case_number", "property_address", "owner_of_record",
            "estimated_surplus", "sale_date", "overbid_amount"
        ],
        "known_gaps": [
            "lien_type", "total_indebtedness", "recorder_link", "redemption_date"
        ],
        "update_frequency_days": 7,
        "legal_confidence": "MED",
    },
    {
        "scraper_name": "routt_foreclosure",
        "jurisdiction": "Routt, CO",
        "record_type": "FORECLOSURE_SURPLUS",
        "fields_collected": [
            "case_number", "property_address", "owner_of_record",
            "estimated_surplus", "sale_date", "overbid_amount"
        ],
        "known_gaps": [
            "lien_type", "total_indebtedness", "recorder_link", "redemption_date"
        ],
        "update_frequency_days": 7,
        "legal_confidence": "MED",
    },
    {
        "scraper_name": "adams_foreclosure",
        "jurisdiction": "Adams, CO",
        "record_type": "FORECLOSURE_SURPLUS",
        "fields_collected": [
            "case_number", "property_address", "owner_of_record",
            "estimated_surplus", "sale_date", "overbid_amount",
            "total_indebtedness"
        ],
        "known_gaps": [
            "lien_type", "recorder_link", "redemption_date"
        ],
        "update_frequency_days": 7,
        "legal_confidence": "HIGH",
    },
    # ---- PHASE 3 EXPANSION: Front Range + Mountain ----
    {
        "scraper_name": "elpaso_foreclosure",
        "jurisdiction": "El Paso, CO",
        "record_type": "FORECLOSURE_SURPLUS",
        "fields_collected": [
            "case_number", "property_address", "owner_of_record",
            "estimated_surplus", "sale_date", "overbid_amount"
        ],
        "known_gaps": [
            "lien_type", "total_indebtedness", "recorder_link", "redemption_date"
        ],
        "update_frequency_days": 7,
        "legal_confidence": "HIGH",
    },
    {
        "scraper_name": "larimer_foreclosure",
        "jurisdiction": "Larimer, CO",
        "record_type": "FORECLOSURE_SURPLUS",
        "fields_collected": [
            "case_number", "property_address", "owner_of_record",
            "estimated_surplus", "sale_date", "overbid_amount"
        ],
        "known_gaps": [
            "lien_type", "total_indebtedness", "recorder_link", "redemption_date"
        ],
        "update_frequency_days": 7,
        "legal_confidence": "HIGH",
    },
    {
        "scraper_name": "boulder_foreclosure",
        "jurisdiction": "Boulder, CO",
        "record_type": "FORECLOSURE_SURPLUS",
        "fields_collected": [
            "case_number", "property_address", "owner_of_record",
            "estimated_surplus", "sale_date", "overbid_amount"
        ],
        "known_gaps": [
            "lien_type", "total_indebtedness", "recorder_link", "redemption_date"
        ],
        "update_frequency_days": 7,
        "legal_confidence": "HIGH",
    },
    {
        "scraper_name": "weld_foreclosure",
        "jurisdiction": "Weld, CO",
        "record_type": "FORECLOSURE_SURPLUS",
        "fields_collected": [
            "case_number", "property_address", "owner_of_record",
            "estimated_surplus", "sale_date", "overbid_amount"
        ],
        "known_gaps": [
            "lien_type", "total_indebtedness", "recorder_link", "redemption_date"
        ],
        "update_frequency_days": 7,
        "legal_confidence": "MED",
    },
    {
        "scraper_name": "garfield_foreclosure",
        "jurisdiction": "Garfield, CO",
        "record_type": "FORECLOSURE_SURPLUS",
        "fields_collected": [
            "case_number", "property_address", "owner_of_record",
            "estimated_surplus", "sale_date"
        ],
        "known_gaps": [
            "lien_type", "total_indebtedness", "overbid_amount",
            "recorder_link", "redemption_date"
        ],
        "update_frequency_days": 7,
        "legal_confidence": "MED",
    },
    {
        "scraper_name": "grand_foreclosure",
        "jurisdiction": "Grand, CO",
        "record_type": "FORECLOSURE_SURPLUS",
        "fields_collected": [
            "case_number", "property_address", "owner_of_record",
            "estimated_surplus", "sale_date"
        ],
        "known_gaps": [
            "lien_type", "total_indebtedness", "overbid_amount",
            "recorder_link", "redemption_date"
        ],
        "update_frequency_days": 7,
        "legal_confidence": "MED",
    },
    {
        "scraper_name": "pbc_foreclosure",
        "jurisdiction": "Palm Beach, FL",
        "record_type": "FORECLOSURE_SURPLUS",
        "fields_collected": [
            "case_number", "estimated_surplus", "sale_date",
            "overbid_amount", "total_indebtedness"
        ],
        "known_gaps": [
            "property_address", "owner_of_record",
            "lien_type", "recorder_link", "redemption_date",
            "NOTE: Florida 1-year statute window is significantly shorter than CO"
        ],
        "update_frequency_days": 3,
        "legal_confidence": "HIGH",
    },
]


def seed_registry(conn: sqlite3.Connection):
    """Populate scraper_registry from declarations."""
    for decl in SCRAPER_DECLARATIONS:
        conn.execute("""
            INSERT OR REPLACE INTO scraper_registry
            (scraper_name, jurisdiction, record_type, fields_collected,
             known_gaps, update_frequency_days, legal_confidence, enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        """, (
            decl["scraper_name"],
            decl["jurisdiction"],
            decl["record_type"],
            json.dumps(decl["fields_collected"]),
            json.dumps(decl["known_gaps"]),
            decl["update_frequency_days"],
            decl["legal_confidence"],
        ))
    conn.commit()


def get_enabled_scrapers(conn: sqlite3.Connection) -> list:
    """Return only scrapers that have registry entries and are enabled."""
    rows = conn.execute(
        "SELECT scraper_name, jurisdiction, legal_confidence FROM scraper_registry WHERE enabled = 1"
    ).fetchall()
    return [{"name": r[0], "jurisdiction": r[1], "confidence": r[2]} for r in rows]


def disable_scraper(conn: sqlite3.Connection, scraper_name: str, reason: str):
    """Disable a scraper with documented reason."""
    conn.execute(
        "UPDATE scraper_registry SET enabled = 0, disabled_reason = ? WHERE scraper_name = ?",
        (reason, scraper_name)
    )
    conn.commit()


# ============================================================================
# FIELD REQUIREMENT MATRIX
# ============================================================================

FIELD_REQUIREMENT_MATRIX = """
FIELD REQUIREMENT MATRIX — VeriFuse Surplus Engine
====================================================

TIER 1: IDENTITY (Mandatory — gate for record existence)
─────────────────────────────────────────────────────────
Field               Required For    Scrapers That Provide It
asset_id            ALL             Generated (not scraped)
county              ALL             ALL scrapers
jurisdiction        ALL             Derived from county+state
case_number         ALL             All except douglas_foreclosure (BLOCKED)
asset_type          ALL             Derived from scraper registration

TIER 2: LEGAL ACTIONABILITY (Gate for ATTORNEY class)
─────────────────────────────────────────────────────────
Field               Required For    Scrapers That Provide It          Gap Analysis
statute_window      ATTORNEY        NONE (derived from statute_authority table)    OK: computed
days_remaining      ATTORNEY        NONE (computed from sale_date + statute)       OK: computed
owner_of_record     ATTORNEY        denver, jefferson, arapahoe, douglas,         MISSING: mesa, pbc
                                    eagle, teller, summit, sanmiguel
lien_type           ATTORNEY        NONE                                          CRITICAL GAP: no scraper provides this
sale_date           ATTORNEY        All except denver_tax, douglas_foreclosure     PARTIAL: douglas uses Mon-YY
recorder_link       ATTORNEY        NONE (denver/jefferson generate search URLs)  CRITICAL GAP: no official links

TIER 2 GAP SUMMARY:
  - lien_type:      Not available from any scraper. DECISION: Default to "Deed of Trust" for
                    foreclosure, "Tax Lien" for tax. Override manually. This is a known degradation.
  - recorder_link:  County recorder search URLs are generated, not direct document links.
                    DECISION: Generate county-specific search URLs. Mark as "search_url" not
                    "direct_link". Attorneys understand this distinction.
  - owner_of_record: Missing from Mesa and PBC scrapers.
                    DECISION: These assets CANNOT reach ATTORNEY class until owner is supplied
                    (manually or via supplemental scraper).

TIER 3: FINANCIAL (Non-blocking but important)
─────────────────────────────────────────────────────────
Field               Scrapers That Provide It
estimated_surplus   denver, jefferson, arapahoe, douglas, mesa, teller, pbc
total_indebtedness  jefferson, eagle, teller, summit, sanmiguel, pbc
overbid_amount      denver, jefferson, arapahoe, pbc

TIER 4: INTELLIGENCE (Internal only, never shown to attorneys)
─────────────────────────────────────────────────────────
Field               Source
completeness_score  Computed by pipeline.py
confidence_score    Computed by pipeline.py
risk_score          Computed by pipeline.py
data_grade          Computed by pipeline.py
"""


def print_coverage_report(conn: sqlite3.Connection):
    """Print scraper coverage audit to stdout."""
    print("=" * 70)
    print("SCRAPER COVERAGE AUDIT")
    print("=" * 70)

    scrapers = conn.execute("SELECT * FROM scraper_registry ORDER BY jurisdiction").fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM scraper_registry LIMIT 0").description]

    for row in scrapers:
        s = dict(zip(cols, row))
        status = "ENABLED" if s["enabled"] else f"DISABLED ({s['disabled_reason']})"
        collected = json.loads(s["fields_collected"])
        gaps = json.loads(s["known_gaps"])

        print(f"\n{'─' * 50}")
        print(f"Scraper:      {s['scraper_name']}")
        print(f"Jurisdiction: {s['jurisdiction']}")
        print(f"Record Type:  {s['record_type']}")
        print(f"Confidence:   {s['legal_confidence']}")
        print(f"Frequency:    Every {s['update_frequency_days']} days")
        print(f"Status:       {status}")
        print(f"Collects:     {', '.join(collected)}")
        print(f"Gaps:         {', '.join(gaps)}")
        if s["last_run_at"]:
            print(f"Last Run:     {s['last_run_at']} ({s['last_run_status']})")

    print(f"\n{'=' * 70}")
    print(FIELD_REQUIREMENT_MATRIX)
