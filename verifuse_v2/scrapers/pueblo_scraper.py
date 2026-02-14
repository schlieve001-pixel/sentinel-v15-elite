"""
VERIFUSE V2 — Pueblo County Foreclosure Scraper (Engine #10)

Scrapes the Pueblo County Public Trustee sale schedule page for
foreclosure listings. Pueblo does not use the GTS Search platform
and has less structured data than other CO counties.

Source: https://county.pueblo.org/treasurers-department/sale-schedule
Search: http://www.co.pueblo.co.us/pubtrustee/
Sales: Wednesdays at 10:00 AM MT

Note: Pueblo's data is less accessible than GTS-based counties.
This scraper attempts to parse their sale schedule page for basic
foreclosure info. For detailed financial data, PDFs must be obtained
directly from the Public Trustee's office.

Usage:
  python -m verifuse_v2.scrapers.pueblo_scraper
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

from verifuse_v2.db import database as db
from verifuse_v2.daily_healthcheck import compute_confidence, compute_grade

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

RAW_PDF_DIR = Path(__file__).resolve().parent.parent / "data" / "raw_pdfs" / "pueblo"

SALE_SCHEDULE_URL = "https://county.pueblo.org/treasurers-department/sale-schedule"
PUBTRUSTEE_URL = "http://www.co.pueblo.co.us/pubtrustee/"


def _clean_money(raw: str) -> float:
    if not raw:
        return 0.0
    cleaned = raw.replace("$", "").replace(",", "").replace(" ", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _make_asset_id(case_number: str) -> str:
    clean = case_number.strip().replace(" ", "_")
    return f"pueblo_{clean}"


def _record_hash(rec: dict) -> str:
    key = f"{rec.get('case_number', '')}|{rec.get('address', '')}|{rec.get('sale_date', '')}"
    return hashlib.sha256(key.encode()).hexdigest()


def scrape_sale_schedule() -> list[dict]:
    """Scrape the Pueblo County sale schedule page for foreclosure listings."""
    records = []

    try:
        resp = requests.get(SALE_SCHEDULE_URL, timeout=30)
        if resp.status_code != 200:
            log.warning("Could not fetch sale schedule: HTTP %d", resp.status_code)
            return records

        soup = BeautifulSoup(resp.text, "html.parser")

        # Look for tables with foreclosure data
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            headers = []
            for row in rows:
                cells = row.find_all(["th", "td"])
                if not cells:
                    continue

                cell_texts = [c.get_text(strip=True) for c in cells]

                # Detect header row
                if any("case" in c.lower() or "foreclosure" in c.lower() for c in cell_texts):
                    headers = [c.lower() for c in cell_texts]
                    continue

                if headers and len(cell_texts) >= len(headers):
                    rec = dict(zip(headers, cell_texts))
                    records.append(rec)

        # Also look for PDF links on the page
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if ".pdf" in href.lower() and ("sale" in href.lower() or "foreclosure" in href.lower()):
                log.info("Found PDF link: %s", href)

    except requests.RequestException as e:
        log.warning("Could not fetch sale schedule: %s", e)

    log.info("Scraped %d records from Pueblo sale schedule", len(records))
    return records


def ingest_records(records: list[dict]) -> dict:
    """Ingest scraped Pueblo County records into the V2 database."""
    db.init_db()
    stats = {"total": len(records), "inserted": 0, "updated": 0, "skipped": 0}
    now = datetime.now(timezone.utc).isoformat()

    for rec in records:
        case_number = rec.get("case number", rec.get("case", rec.get("foreclosure", "")))
        if not case_number:
            stats["skipped"] += 1
            continue

        address = rec.get("address", rec.get("property address", ""))
        owner = rec.get("owner", rec.get("grantor", ""))
        sale_date_raw = rec.get("sale date", rec.get("date", ""))

        sale_date = None
        if sale_date_raw:
            for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(sale_date_raw, fmt)
                    sale_date = dt.strftime("%Y-%m-%d")
                    break
                except ValueError:
                    continue

        asset_id = _make_asset_id(case_number)
        rhash = _record_hash({"case_number": case_number, "address": address, "sale_date": sale_date})

        existing = db.get_lead_by_id(asset_id)
        if existing:
            if existing.get("record_hash") == rhash:
                stats["skipped"] += 1
                continue
            stats["updated"] += 1
        else:
            stats["inserted"] += 1

        days_remaining = None
        if sale_date:
            try:
                sale_dt = datetime.fromisoformat(sale_date)
                deadline = sale_dt + timedelta(days=180)
                days_remaining = (deadline - datetime.now(timezone.utc).replace(tzinfo=None)).days
            except (ValueError, TypeError):
                pass

        completeness = 0.5
        confidence = compute_confidence(0.0, 0.0, sale_date, owner, address)
        grade = "BRONZE"
        record_class = "PIPELINE"

        with db.get_db() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO assets
                (asset_id, county, state, jurisdiction, case_number, asset_type,
                 source_name, statute_window, days_remaining, owner_of_record,
                 property_address, sale_date, estimated_surplus, overbid_amount,
                 total_indebtedness, completeness_score, confidence_score,
                 data_grade, record_hash, source_file, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, [
                asset_id, "Pueblo", "CO", "pueblo_co",
                case_number, "FORECLOSURE_PRESALE",
                "pueblo_public_trustee_schedule",
                "180 days from sale_date (C.R.S. § 38-38-111)",
                days_remaining, owner, address, sale_date,
                0.0, 0.0, 0.0,
                completeness, confidence, grade, rhash,
                SALE_SCHEDULE_URL, now, now,
            ])

            conn.execute("""
                INSERT OR REPLACE INTO legal_status
                (asset_id, record_class, data_grade, days_remaining,
                 statute_window, last_evaluated_at)
                VALUES (?,?,?,?,?,?)
            """, [asset_id, record_class, grade, days_remaining,
                  "180 days from sale_date (C.R.S. § 38-38-111)", now])

    log.info("Pueblo ingestion: %d inserted, %d updated, %d skipped",
             stats["inserted"], stats["updated"], stats["skipped"])
    return stats


def run() -> dict:
    """Full pipeline: scrape -> ingest."""
    records = scrape_sale_schedule()
    if not records:
        return {"status": "no_data", "note": "Pueblo County data requires manual PDF acquisition from PT office"}

    return ingest_records(records)


if __name__ == "__main__":
    result = run()
    print()
    print("=" * 50)
    print("  PUEBLO COUNTY RESULTS")
    print("=" * 50)
    for k, v in result.items():
        print(f"  {k}: {v}")
    print("=" * 50)
