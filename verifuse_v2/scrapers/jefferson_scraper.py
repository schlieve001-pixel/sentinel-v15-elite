from __future__ import annotations

import csv
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from verifuse_v2.db import database as db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def generate_asset_id(county: str, case_number: str) -> str:
    """Generate a deterministic ID for deduplication."""
    raw = f"{county.lower()}_{case_number.strip()}"
    return f"{county.lower()}_foreclosure_{raw}"


def clean_money(text: str) -> float:
    """Convert '$1,234.56' to 1234.56."""
    if not text:
        return 0.0
    clean = re.sub(r"[^\d.]", "", text)
    try:
        return float(clean)
    except ValueError:
        return 0.0


def parse_date(text: str) -> str:
    """Convert '10/05/2024' to '2024-10-05'."""
    if not text:
        return ""
    try:
        dt = datetime.strptime(text.strip(), "%m/%d/%Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return text


def ingest_jefferson_records(records: list[dict]) -> dict:
    """Save scraped or imported records to the database."""
    stats = {"total": len(records), "inserted": 0, "updated": 0, "skipped": 0, "no_surplus": 0}
    
    db.init_db()
    
    with db.get_db() as conn:
        for rec in records:
            # Skip if no surplus (unless we want to track $0 leads)
            overbid = clean_money(str(rec.get("overbid", 0)))
            if overbid <= 1000:  # FILTER: Only keep leads with > $1,000 surplus
                stats["no_surplus"] += 1
                continue 

            asset_id = generate_asset_id("jefferson", rec["file_number"])
            
            # Upsert — columns must match schema.sql
            now = datetime.now(timezone.utc).isoformat()
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO assets (
                        asset_id, county, state, jurisdiction, case_number,
                        asset_type, source_name, sale_date,
                        owner_of_record, property_address,
                        overbid_amount, total_indebtedness, estimated_surplus,
                        data_grade, statute_window,
                        completeness_score, confidence_score,
                        created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    asset_id,
                    "Jefferson",
                    "CO",
                    "jefferson_co",
                    rec["file_number"],
                    "FORECLOSURE_SURPLUS",
                    "jefferson_csv_import",
                    parse_date(rec.get("sale_date", "")),
                    rec.get("owner", ""),
                    rec.get("address", ""),
                    overbid,
                    clean_money(str(rec.get("written_bid", 0))),
                    overbid,
                    "SILVER",
                    "180 days from sale_date (C.R.S. § 38-38-111)",
                    0.8 if rec.get("owner") and rec.get("address") else 0.5,
                    0.85,
                    now,
                    now,
                ))
                # Also insert legal_status
                conn.execute("""
                    INSERT OR REPLACE INTO legal_status
                    (asset_id, record_class, data_grade, statute_window, last_evaluated_at)
                    VALUES (?,?,?,?,?)
                """, (
                    asset_id,
                    "ATTORNEY" if overbid >= 1000 else "QUALIFIED",
                    "SILVER",
                    "180 days from sale_date (C.R.S. § 38-38-111)",
                    now,
                ))
                stats["inserted"] += 1
            except Exception as e:
                log.error(f"Failed to insert {asset_id}: {e}")
                stats["skipped"] += 1

    return stats


def run(days_back: int = 90) -> dict:
    """
    Main scraper execution (Stub for now, as JeffCo requires solving reCAPTCHA).
    """
    log.warning("Automated scraping for Jefferson County is currently blocked by reCAPTCHA.")
    log.warning("Please use --csv to import data manually.")
    return {"error": "Automated scraping unavailable. Use --csv."}


def import_csv(csv_path: str | Path) -> dict:
    """Import Jefferson County overbid data from a CSV file."""
    csv_path = Path(csv_path)
    if not csv_path.exists():
        log.error("CSV file not found: %s", csv_path)
        return {"error": f"File not found: {csv_path}"}

    # Column name aliases
    COLUMN_MAP = {
        "file_number": "file_number", "file_#": "file_number", "case_number": "file_number",
        "owner": "owner", "borrower": "owner", "name": "owner",
        "address": "address", "property_address": "address",
        "sale_date": "sale_date", "sold_date": "sale_date",
        "sale_amount": "sale_amount", "winning_bid": "sale_amount",
        "written_bid": "written_bid", "indebtedness": "written_bid",
        "overbid": "overbid", "surplus": "overbid", "excess": "overbid"
    }

    records = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        
        if not reader.fieldnames:
            return {"error": "CSV has no header row"}

        header_map = {}
        for raw_header in reader.fieldnames:
            normalized = raw_header.strip().lower().replace(" ", "_")
            canonical = COLUMN_MAP.get(normalized, normalized)
            header_map[raw_header] = canonical

        for row in reader:
            mapped = {}
            for raw_key, value in row.items():
                canonical = header_map.get(raw_key, raw_key)
                mapped[canonical] = (value or "").strip()

            if not mapped.get("file_number"):
                continue
            
            records.append(mapped)

    if not records:
        return {"error": "No valid records found in CSV"}

    log.info("Parsed %d records from %s", len(records), csv_path.name)
    stats = ingest_jefferson_records(records)
    stats["source_file"] = str(csv_path)
    return stats


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Jefferson County Foreclosure Scraper")
    parser.add_argument("--csv", help="Path to CSV file for manual overbid data import")
    parser.add_argument("--days", type=int, default=90, help="Days to look back (default: 90)")
    args = parser.parse_args()

    if args.csv:
        result = import_csv(args.csv)
    else:
        result = run(days_back=args.days)

    print("\n" + "=" * 50)
    print("  JEFFERSON COUNTY RESULTS")
    print("=" * 50)
    for k, v in result.items():
        print(f"  {k}: {v}")
