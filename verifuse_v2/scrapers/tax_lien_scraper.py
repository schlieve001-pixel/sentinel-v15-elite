"""
VERIFUSE V2 — Tax Lien Sale Surplus Scraper

Colorado tax lien sales generate surplus when a property is sold for
more than the delinquent taxes + costs. This is a SEPARATE surplus
stream from foreclosure overbids (different statute, different office).

Key difference from foreclosure surplus:
  - Held by: County Treasurer (not Public Trustee)
  - Statute: C.R.S. § 39-11-151 (tax lien surplus)
  - Timeline: Surplus held 5 years, then escheats to county
  - No 6-month contact restriction (C.R.S. § 38-38-111 is foreclosure-specific)

Data sources:
  - County Treasurer websites (tax lien sale results)
  - County Treasurer CORA requests (bulk data)
  - GovEase / Grant Street auction platforms (some counties)

Usage:
  python -m verifuse_v2.scrapers.tax_lien_scraper
  python -m verifuse_v2.scrapers.tax_lien_scraper --county Denver
  python -m verifuse_v2.scrapers.tax_lien_scraper --import-csv /path/to/tax_surplus.csv
"""

from __future__ import annotations

import csv
import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

from verifuse_v2.db import database as db

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

# County Treasurer contact info and data URLs
COUNTY_TREASURER_SOURCES = {
    "Denver": {
        "url": "https://www.denvergov.org/Government/Agencies-Departments-Offices/Department-of-Finance/Treasury/Tax-Liens",
        "phone": "720-913-9300",
        "email": "treasury@denvergov.org",
        "auction_platform": "grant_street",
    },
    "Jefferson": {
        "url": "https://www.jeffco.us/835/Tax-Lien-Sale",
        "phone": "303-271-8330",
        "email": "treasurer@jeffco.us",
        "auction_platform": "grant_street",
    },
    "Arapahoe": {
        "url": "https://www.arapahoeco.gov/your_county/county_departments/treasurer/tax_lien_sale/index.php",
        "phone": "303-795-4550",
        "email": "treasurer@arapahoegov.com",
        "auction_platform": "govease",
    },
    "Adams": {
        "url": "https://www.adcogov.org/treasurer",
        "phone": "720-523-6160",
        "email": "treasurer@adcogov.org",
        "auction_platform": None,
    },
    "El Paso": {
        "url": "https://treasurer.elpasoco.com/county-treasurer/tax-lien-sale/",
        "phone": "719-520-7230",
        "email": None,
        "auction_platform": "grant_street",
    },
    "Douglas": {
        "url": "https://www.douglas.co.us/treasurer/tax-lien-sale-information/",
        "phone": "303-660-7440",
        "email": "treasurer@douglas.co.us",
        "auction_platform": None,
    },
    "Larimer": {
        "url": "https://www.larimer.gov/treasurer/thirdparty/liens/sale",
        "phone": "970-498-7020",
        "email": "treasurer@larimer.org",
        "auction_platform": "govease",
    },
    "Boulder": {
        "url": "https://www.bouldercounty.org/property-and-land/treasurer/tax-sale/",
        "phone": "303-441-3520",
        "email": "treasurer@bouldercounty.org",
        "auction_platform": None,
    },
    "Mesa": {
        "url": "https://www.mesacounty.us/treasurer",
        "phone": "970-244-1820",
        "email": None,
        "auction_platform": None,
    },
    "Weld": {
        "url": "https://www.weldgov.com/departments/treasurer",
        "phone": "970-400-4370",
        "email": None,
        "auction_platform": None,
    },
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15",
]


def _clean_money(text: str) -> float:
    """Convert '$1,234.56' to 1234.56."""
    if not text:
        return 0.0
    clean = re.sub(r"[^\d.]", "", str(text))
    try:
        return float(clean)
    except ValueError:
        return 0.0


def _parse_date(text: str) -> str:
    """Convert various date formats to ISO 8601."""
    if not text:
        return ""
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m-%d-%Y"):
        try:
            return datetime.strptime(text.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return text.strip()


def _make_asset_id(county: str, parcel: str) -> str:
    """Generate deterministic ID for tax lien surplus."""
    clean = re.sub(r"[^a-zA-Z0-9]", "_", parcel.strip())
    return f"taxlien_{county.lower()}_{clean}"


def _record_hash(rec: dict) -> str:
    """SHA-256 hash for dedup."""
    key = f"{rec.get('parcel', '')}|{rec.get('owner', '')}|{rec.get('surplus', 0)}"
    return hashlib.sha256(key.encode()).hexdigest()


# ── CSV Import ──────────────────────────────────────────────────────


def import_csv(csv_path: str | Path, county: str = "") -> dict:
    """Import tax lien surplus data from a CSV file.

    Expected columns (flexible mapping):
        parcel, owner, address, sale_date, sale_amount, taxes_owed, surplus
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        log.error("CSV not found: %s", csv_path)
        return {"error": f"File not found: {csv_path}"}

    COLUMN_MAP = {
        "parcel": "parcel", "parcel_number": "parcel", "parcel_id": "parcel",
        "account": "parcel", "account_number": "parcel", "schedule": "parcel",
        "owner": "owner", "owner_name": "owner", "name": "owner",
        "taxpayer": "owner", "property_owner": "owner",
        "address": "address", "property_address": "address", "situs": "address",
        "sale_date": "sale_date", "date_sold": "sale_date", "auction_date": "sale_date",
        "sale_amount": "sale_amount", "bid_amount": "sale_amount", "winning_bid": "sale_amount",
        "taxes_owed": "taxes_owed", "delinquent": "taxes_owed", "total_due": "taxes_owed",
        "surplus": "surplus", "overbid": "surplus", "excess": "surplus",
        "overage": "surplus", "remaining": "surplus",
        "county": "county",
    }

    records = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return {"error": "CSV has no header row"}

        header_map = {}
        for raw in reader.fieldnames:
            normalized = raw.strip().lower().replace(" ", "_")
            header_map[raw] = COLUMN_MAP.get(normalized, normalized)

        for row in reader:
            mapped = {}
            for k, v in row.items():
                mapped[header_map.get(k, k)] = (v or "").strip()

            # Need at least a parcel number
            if not mapped.get("parcel"):
                continue

            # Use county from arg or CSV
            if not mapped.get("county"):
                mapped["county"] = county

            records.append(mapped)

    if not records:
        return {"error": "No valid records found in CSV"}

    log.info("Parsed %d tax lien records from %s", len(records), csv_path.name)
    return _ingest_tax_lien_records(records)


def _ingest_tax_lien_records(records: list[dict]) -> dict:
    """Ingest tax lien surplus records into the V2 database."""
    db.init_db()
    stats = {"total": len(records), "inserted": 0, "skipped": 0, "no_surplus": 0}
    now = datetime.now(timezone.utc).isoformat()

    with db.get_db() as conn:
        for rec in records:
            # Compute surplus if not provided
            surplus = _clean_money(str(rec.get("surplus", 0)))
            if surplus == 0:
                sale_amount = _clean_money(str(rec.get("sale_amount", 0)))
                taxes_owed = _clean_money(str(rec.get("taxes_owed", 0)))
                if sale_amount > taxes_owed:
                    surplus = sale_amount - taxes_owed

            if surplus < 1000:
                stats["no_surplus"] += 1
                continue

            county = rec.get("county", "Unknown")
            asset_id = _make_asset_id(county, rec["parcel"])
            rhash = _record_hash(rec)

            # Check for existing
            existing = conn.execute(
                "SELECT record_hash FROM assets WHERE asset_id = ?", [asset_id]
            ).fetchone()
            if existing and existing["record_hash"] == rhash:
                stats["skipped"] += 1
                continue

            sale_date = _parse_date(rec.get("sale_date", ""))
            owner = rec.get("owner", "")
            address = rec.get("address", "")

            # Grade
            completeness = 1.0 if all([owner, address, sale_date]) else 0.5
            confidence = 0.80  # CSV data, not direct from county system

            # Tax lien surplus has 5-year escheatment (C.R.S. § 39-11-151)
            days_remaining = None
            if sale_date:
                try:
                    sale_dt = datetime.fromisoformat(sale_date)
                    deadline = sale_dt + timedelta(days=365 * 5)
                    days_remaining = (deadline - datetime.now(timezone.utc).replace(tzinfo=None)).days
                except (ValueError, TypeError):
                    pass

            if surplus >= 5000 and completeness >= 1.0 and days_remaining and days_remaining > 90:
                grade = "GOLD"
                record_class = "ATTORNEY"
            elif surplus >= 1000 and days_remaining and days_remaining > 0:
                grade = "SILVER"
                record_class = "QUALIFIED"
            else:
                grade = "BRONZE"
                record_class = "PIPELINE"

            try:
                conn.execute("""
                    INSERT OR REPLACE INTO assets
                    (asset_id, county, state, jurisdiction, case_number, asset_type,
                     source_name, statute_window, days_remaining, owner_of_record,
                     property_address, sale_date, estimated_surplus, overbid_amount,
                     completeness_score, confidence_score, data_grade,
                     record_hash, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, [
                    asset_id, county, "CO", f"{county.lower()}_co", rec["parcel"],
                    "TAX_LIEN_SURPLUS", "tax_lien_csv_import",
                    "5 years from sale (C.R.S. § 39-11-151)",
                    days_remaining, owner, address, sale_date,
                    surplus, surplus, completeness, confidence, grade,
                    rhash, now, now,
                ])

                conn.execute("""
                    INSERT OR REPLACE INTO legal_status
                    (asset_id, record_class, data_grade, statute_window, last_evaluated_at)
                    VALUES (?,?,?,?,?)
                """, [
                    asset_id, record_class, grade,
                    "5 years from sale (C.R.S. § 39-11-151)", now,
                ])

                stats["inserted"] += 1
            except Exception as e:
                log.error("Failed to insert %s: %s", asset_id, e)
                stats["skipped"] += 1

    log.info("Tax lien ingestion: %d inserted, %d skipped, %d no surplus",
             stats["inserted"], stats["skipped"], stats["no_surplus"])
    return stats


# ── CORA Request Generator ──────────────────────────────────────────


def generate_cora_request(county: str) -> str:
    """Generate a Colorado Open Records Act request letter for tax lien surplus data.

    CORA (C.R.S. § 24-72-201 et seq.) gives the right to access public records.
    The first hour of staff time is free.
    """
    info = COUNTY_TREASURER_SOURCES.get(county, {})
    today = datetime.now().strftime("%B %d, %Y")

    letter = f"""
COLORADO OPEN RECORDS ACT REQUEST
{today}

To: {county} County Treasurer
{info.get('phone', '[Phone number]')}

Re: CORA Request for Tax Lien Sale Surplus Data

Dear {county} County Treasurer:

Pursuant to the Colorado Open Records Act, C.R.S. § 24-72-201 et seq.,
I am requesting access to the following public records:

1. All tax lien sale results for the past 5 years (2021-2026) where
   the sale price exceeded the total taxes, fees, and costs owed,
   resulting in surplus funds.

2. For each such sale, I request:
   - Parcel/schedule number
   - Property address
   - Prior owner name (at time of sale)
   - Sale date
   - Sale amount / winning bid
   - Total taxes and fees owed
   - Surplus amount
   - Whether surplus has been claimed or remains unclaimed

3. Any unclaimed tax lien surplus funds currently held by the
   {county} County Treasurer's office.

Format preference: Electronic (CSV, Excel, or PDF) preferred.

Under CORA, the first hour of staff time to fulfill this request is
provided at no cost (C.R.S. § 24-72-205(6)(b)). If additional costs
are anticipated, please provide an estimate before proceeding.

Please respond within 3 business days as required by statute.

Thank you,
[Your Name]
[Your Contact Information]
"""
    return letter.strip()


def print_county_contacts() -> None:
    """Print all county treasurer contact info for manual data collection."""
    print("\n" + "=" * 70)
    print("  COLORADO COUNTY TREASURER CONTACTS — TAX LIEN SURPLUS DATA")
    print("=" * 70)
    for county, info in sorted(COUNTY_TREASURER_SOURCES.items()):
        print(f"\n  {county} County:")
        print(f"    URL:   {info['url']}")
        print(f"    Phone: {info.get('phone', 'N/A')}")
        print(f"    Email: {info.get('email', 'N/A')}")
        if info.get("auction_platform"):
            print(f"    Platform: {info['auction_platform']}")
    print("\n" + "=" * 70)


# ── Main Pipeline ────────────────────────────────────────────────────


def run(county: Optional[str] = None, csv_path: Optional[str] = None) -> dict:
    """Full pipeline for tax lien surplus data collection."""
    results = {}

    if csv_path:
        log.info("Importing tax lien CSV: %s", csv_path)
        results["csv_import"] = import_csv(csv_path, county=county or "")
    else:
        log.info("No CSV provided. Tax lien data must be collected manually.")
        log.info("Generating CORA request letters...")

        counties = [county] if county else ["Denver", "Jefferson", "Arapahoe", "Adams", "El Paso"]
        cora_dir = Path(__file__).resolve().parent.parent / "data" / "cora_requests"
        cora_dir.mkdir(parents=True, exist_ok=True)

        for c in counties:
            letter = generate_cora_request(c)
            out_path = cora_dir / f"cora_tax_lien_{c.lower()}.txt"
            out_path.write_text(letter)
            log.info("CORA request saved: %s", out_path)

        results["cora_requests"] = {
            "generated": len(counties),
            "output_dir": str(cora_dir),
        }
        results["contacts"] = {c: COUNTY_TREASURER_SOURCES[c].get("phone", "N/A")
                              for c in counties if c in COUNTY_TREASURER_SOURCES}

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Tax Lien Sale Surplus Scraper")
    parser.add_argument("--county", help="County (e.g., Denver, Jefferson)")
    parser.add_argument("--import-csv", dest="csv", help="Path to tax surplus CSV")
    parser.add_argument("--contacts", action="store_true", help="Print county contact info")
    parser.add_argument("--cora", help="Generate CORA request for a county")
    args = parser.parse_args()

    if args.contacts:
        print_county_contacts()
    elif args.cora:
        print(generate_cora_request(args.cora))
    else:
        result = run(county=args.county, csv_path=args.csv)
        print("\n" + "=" * 50)
        print("  TAX LIEN SURPLUS RESULTS")
        print("=" * 50)
        for k, v in result.items():
            if isinstance(v, dict):
                print(f"  {k}:")
                for k2, v2 in v.items():
                    print(f"    {k2}: {v2}")
            else:
                print(f"  {k}: {v}")
        print("=" * 50)
