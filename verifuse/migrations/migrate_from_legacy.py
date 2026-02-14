"""
VeriFuse Surplus Engine — Migration from Legacy System
========================================================
DELIVERABLE 7 (partial): Migration Plan

Migrates data from:
  _ARCHIVE_FEB_2026/data/verifuse_vault.db (SQLite: leads + pipeline_leads)

Into:
  verifuse/data/verifuse.db (new canonical schema)

Migration rules:
1. Every legacy lead → PIPELINE class (re-evaluate from scratch)
2. Every legacy pipeline_lead → PIPELINE class
3. No automatic promotion to ATTORNEY — must pass gate conditions
4. All legacy fields mapped to canonical tiers
5. Missing fields explicitly marked NULL (not guessed)
6. Migration is logged as CREATED events with actor "system:migration"
7. Idempotent — can be run multiple times safely (dedup by record_hash)

WHAT THIS MIGRATION DOES NOT DO:
- Does not preserve legacy "Status" values (they are ambiguous)
- Does not preserve legacy risk_score (recomputed by new engine)
- Does not preserve legacy data_confidence (replaced by data_grade)
- Does not import legacy blacklist (must be re-evaluated)
"""

import os
import sys
import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.schema import init_db, seed_statute_authority, RecordClass, DataGrade
from core.pipeline import ingest_asset, evaluate_all
from scrapers.registry import seed_registry


LEGACY_DB = Path(__file__).resolve().parent.parent.parent / "_ARCHIVE_FEB_2026" / "data" / "verifuse_vault.db"

# Map legacy sale_type to AssetType enum
SALE_TYPE_MAP = {
    "foreclosure": "FORECLOSURE_SURPLUS",
    "tax deed": "TAX_DEED_SURPLUS",
    "tax surplus": "TAX_OVERPAYMENT",
    "tax overpayment": "TAX_OVERPAYMENT",
    "tax sale": "TAX_DEED_SURPLUS",
    "probate": "PROBATE_EXCESS",
}

# Map legacy county to scraper name
COUNTY_SCRAPER_MAP = {
    "Denver": "denver_foreclosure",
    "Jefferson": "jefferson_foreclosure",
    "Arapahoe": "arapahoe_foreclosure",
    "Douglas": "douglas_foreclosure",
    "Mesa": "mesa_foreclosure",
    "Eagle": "eagle_portal",
    "Teller": "teller_govease",
    "Summit": "summit_govease",
    "San Miguel": "sanmiguel_portal",
    "Palm Beach": "pbc_foreclosure",
}


def get_recorder_link(county: str, owner: str) -> str:
    """Generate county recorder search URL. Same logic as legacy but explicit."""
    if not owner or owner == "Unknown":
        return None
    o = str(owner).replace(" ", "+")
    links = {
        "Denver": f"https://denvergov.org/recorder/search?query={o}",
        "Jefferson": f"https://gts.co.jefferson.co.us/recorder/eagleweb/docSearch.jsp?search={o}",
        "Arapahoe": f"https://clerk.arapahoegov.com/recorder/eagleweb/docSearch.jsp?search={o}",
        "Adams": f"http://recording.adcogov.org/LandmarkWeb/search/index?nameFilter={o}",
    }
    return links.get(county)


def migrate_row(row: dict, table_name: str) -> dict:
    """Convert a legacy row to canonical ingest format."""
    county = row.get("county", "UNKNOWN")
    sale_type = str(row.get("sale_type", "foreclosure")).lower()
    asset_type = SALE_TYPE_MAP.get(sale_type, "FORECLOSURE_SURPLUS")

    # Determine state from county
    state = "FL" if county == "Palm Beach" else "CO"

    # Determine lien type from sale_type (known degradation — see spec)
    lien_type = None
    if "tax" in sale_type:
        lien_type = "Tax Lien"
    elif "foreclosure" in sale_type:
        lien_type = "Deed of Trust"

    owner = row.get("owner_grantor") or "Unknown"
    recorder = row.get("recorder_link") or get_recorder_link(county, owner)

    source_name = COUNTY_SCRAPER_MAP.get(county, "unknown_legacy")

    return {
        "county": county,
        "state": state,
        "case_number": row.get("case_number"),
        "asset_type": asset_type,
        "owner_of_record": owner if owner != "Unknown" else None,
        "property_address": row.get("property_address"),
        "sale_date": row.get("sale_date"),
        "lien_type": lien_type,
        "recorder_link": recorder,
        "estimated_surplus": row.get("estimated_surplus"),
        "total_indebtedness": row.get("total_debt"),
        "overbid_amount": row.get("overbid_amount"),
        "source_file_hash": row.get("source_file_hash"),
        "source_file": row.get("source_file") or f"legacy_{table_name}",
        "_source_name": source_name,
    }


def run_migration():
    """Execute the full migration."""
    print("=" * 70)
    print("VERIFUSE MIGRATION: Legacy → Canonical")
    print("=" * 70)

    if not LEGACY_DB.exists():
        print(f"FATAL: Legacy database not found at {LEGACY_DB}")
        return

    # Initialize new database
    print("\n[1/5] Initializing canonical database...")
    new_conn = init_db()
    seed_statute_authority(new_conn)
    seed_registry(new_conn)
    print("  OK: Schema, statutes, and scraper registry seeded.")

    # Open legacy database
    print("\n[2/5] Reading legacy database...")
    legacy_conn = sqlite3.connect(str(LEGACY_DB))
    legacy_conn.row_factory = sqlite3.Row

    # Migrate leads
    try:
        leads = legacy_conn.execute("SELECT * FROM leads").fetchall()
        print(f"  Found {len(leads)} legacy leads")
    except sqlite3.OperationalError:
        leads = []
        print("  No legacy leads table found")

    try:
        pipeline = legacy_conn.execute("SELECT * FROM pipeline_leads").fetchall()
        print(f"  Found {len(pipeline)} legacy pipeline leads")
    except sqlite3.OperationalError:
        pipeline = []
        print("  No legacy pipeline_leads table found")

    legacy_conn.close()

    # Ingest leads
    print("\n[3/5] Ingesting legacy leads into PIPELINE class...")
    ingested = 0
    errors = 0

    for row in leads:
        try:
            data = migrate_row(dict(row), "leads")
            source_name = data.pop("_source_name")
            ingest_asset(new_conn, data, source_name)
            ingested += 1
        except Exception as e:
            errors += 1
            print(f"  ERROR: {e}")

    for row in pipeline:
        try:
            data = migrate_row(dict(row), "pipeline_leads")
            source_name = data.pop("_source_name")
            ingest_asset(new_conn, data, source_name)
            ingested += 1
        except Exception as e:
            errors += 1
            print(f"  ERROR: {e}")

    print(f"  Ingested: {ingested}, Errors: {errors}")

    # Evaluate all assets
    print("\n[4/5] Running pipeline evaluation (PIPELINE → QUALIFIED → ATTORNEY)...")
    results = evaluate_all(new_conn)
    print(f"  Promoted: {results['promoted']}")
    print(f"  Killed: {results['killed']}")
    print(f"  Unchanged: {results['unchanged']}")
    print(f"  Errors: {results['errors']}")

    # Summary
    print("\n[5/5] Migration Summary")
    print("─" * 50)

    for cls in ("PIPELINE", "QUALIFIED", "ATTORNEY", "CLOSED"):
        count = new_conn.execute(
            "SELECT COUNT(*) FROM legal_status WHERE record_class = ?", (cls,)
        ).fetchone()[0]
        print(f"  {cls:12s}: {count}")

    total_events = new_conn.execute("SELECT COUNT(*) FROM pipeline_events").fetchone()[0]
    print(f"  {'EVENTS':12s}: {total_events}")

    attorney_count = new_conn.execute("SELECT COUNT(*) FROM attorney_view").fetchone()[0]
    print(f"\n  Attorney-visible assets: {attorney_count}")

    new_conn.close()
    print("\n  Migration complete.")


if __name__ == "__main__":
    run_migration()
