"""
VERIFUSE V2 — Denver Public Trustee Excess Funds PDF Parser

Downloads and parses the monthly "Available Excess Funds" PDF from
the Denver Public Trustee. Ingests records into the V2 database.

Source URL pattern:
  https://denvergov.org/files/assets/public/v/1/clerk-and-recorder/
  documents/public-trustee-amp-recorder/{year}/{month}-{year}-excess_funds_list.pdf

Usage:
  python -m verifuse_v2.scrapers.denver_pdf_parser
  python -m verifuse_v2.scrapers.denver_pdf_parser --file /path/to/local.pdf
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pdfplumber
import requests

from verifuse_v2.db import database as db

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

RAW_PDF_DIR = Path(__file__).resolve().parent.parent / "data" / "raw_pdfs"

# Denver excess funds PDF URL patterns (they vary year to year)
PDF_URL_PATTERNS = [
    "https://denvergov.org/files/assets/public/v/1/clerk-and-recorder/documents/public-trustee-amp-recorder/{year}/{month_lower}-{year}-excess_funds_list.pdf",
    "https://denvergov.org/files/assets/public/v/1/clerk-and-recorder/documents/public-trustee-amp-recorder/{year}/{month_lower}-{year}-excess-funds-list.pdf",
    "https://www.denvergov.org/files/assets/public/v/1/clerk-and-recorder/documents/{month_lower}-{year}-excess-funds-list.pdf",
]

MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]


def _clean_money(raw: str) -> float:
    """Parse Denver PDF money values like '$ 2 99,937.74' → 299937.74."""
    if not raw:
        return 0.0
    # Remove $, spaces, commas, then parse
    cleaned = raw.replace("$", "").replace(",", "").replace(" ", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        log.warning("Could not parse money value: %r", raw)
        return 0.0


def _parse_sale_date(raw: str) -> Optional[str]:
    """Parse date like '06/06/25' or '10/05/23' → ISO 8601."""
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            dt = datetime.strptime(raw, fmt)
            # 2-digit year: 00-49 → 2000s, 50-99 → 1900s
            if dt.year < 100:
                dt = dt.replace(year=dt.year + 2000)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    log.warning("Could not parse date: %r", raw)
    return None


def _parse_address(row: list[str]) -> tuple[str, str, str, str]:
    """Extract (street, city, state, zip) from varying PDF formats.

    Format A (Oct 2025): [name, street, city, state, zip, ...]
    Format B (Apr 2024): [name, 'street city, state zip', '', '', '', ...]
    """
    street = (row[1] or "").strip()
    city = (row[2] or "").strip()
    state = (row[3] or "").strip()
    zipcode = (row[4] or "").strip()

    # Format B: city/state/zip embedded in address field
    if not city and not state:
        # Try to parse "1636 S. MICHIGAN WAY DENVER, CO 80219"
        match = re.match(
            r"^(.+?)\s+([\w\s]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)$",
            street,
        )
        if match:
            street = match.group(1).strip()
            city = match.group(2).strip()
            state = match.group(3).strip()
            zipcode = match.group(4).strip()
        else:
            city = "DENVER"
            state = "CO"

    return street, city, state, zipcode


def _make_asset_id(file_number: str) -> str:
    """Generate a deterministic asset_id from the Denver file number."""
    return f"denver_excess_{file_number.strip().replace(' ', '_')}"


def _record_hash(row: dict) -> str:
    """SHA-256 hash of key fields for dedup."""
    key = f"{row['file_number']}|{row['owner']}|{row['surplus']}"
    return hashlib.sha256(key.encode()).hexdigest()


def download_pdf(year: int | None = None, month: int | None = None) -> Optional[Path]:
    """Download the Denver excess funds PDF for a given month.

    If no year/month given, tries the most recent months.
    Returns the local file path, or None if download failed.
    """
    RAW_PDF_DIR.mkdir(parents=True, exist_ok=True)

    if year and month:
        targets = [(year, month)]
    else:
        # Try the last 6 months (Denver may lag on publishing)
        now = datetime.now(timezone.utc)
        targets = []
        for offset in range(0, 6):
            dt = now - timedelta(days=30 * offset)
            targets.append((dt.year, dt.month))

    for y, m in targets:
        month_lower = MONTH_NAMES[m - 1]
        for pattern in PDF_URL_PATTERNS:
            url = pattern.format(year=y, month_lower=month_lower)
            try:
                resp = requests.get(url, timeout=30)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    fname = f"denver_excess_{y}_{m:02d}.pdf"
                    path = RAW_PDF_DIR / fname
                    path.write_bytes(resp.content)
                    log.info("Downloaded: %s (%d bytes)", url, len(resp.content))
                    return path
            except requests.RequestException as e:
                log.debug("Failed to download %s: %s", url, e)

    log.error("Could not download any Denver excess funds PDF")
    return None


def parse_pdf(pdf_path: str | Path) -> list[dict]:
    """Parse a Denver excess funds PDF into structured records.

    Returns a list of dicts with keys:
        owner, street, city, state, zip, sale_date, file_number, surplus
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        log.error("PDF not found: %s", pdf_path)
        return []

    records = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            tables = page.extract_tables()
            if not tables:
                log.debug("No tables on page %d", page_num + 1)
                continue

            for table in tables:
                for row in table:
                    if not row or len(row) < 7:
                        continue

                    # Skip header rows
                    first_cell = (row[0] or "").strip()
                    if not first_cell or first_cell.startswith("Borrower"):
                        continue

                    owner = first_cell
                    street, city, state, zipcode = _parse_address(row)

                    # Columns shift based on format — find date and file number
                    # Look for a date pattern (MM/DD/YY) and file number (YYYY-NNNNNN)
                    sale_date_raw = ""
                    file_number = ""
                    surplus_raw = ""

                    for cell in row[2:]:
                        cell_str = (cell or "").strip()
                        if re.match(r"\d{2}/\d{2}/\d{2,4}", cell_str):
                            sale_date_raw = cell_str
                        elif re.match(r"\d{4}-\d{3,6}", cell_str):
                            file_number = cell_str
                        elif "$" in cell_str or (cell_str and re.match(r"[\d,. ]+$", cell_str)):
                            surplus_raw = cell_str

                    # Fallback: try positional extraction
                    if not sale_date_raw and len(row) >= 6:
                        sale_date_raw = (row[5] or "").strip()
                    if not file_number and len(row) >= 7:
                        file_number = (row[6] or "").strip()
                    if not surplus_raw and len(row) >= 8:
                        surplus_raw = (row[7] or "").strip()

                    if not file_number:
                        log.debug("Skipping row (no file number): %s", row)
                        continue

                    sale_date = _parse_sale_date(sale_date_raw)
                    surplus = _clean_money(surplus_raw)

                    record = {
                        "owner": owner,
                        "street": street,
                        "city": city,
                        "state": state or "CO",
                        "zip": zipcode,
                        "sale_date": sale_date,
                        "file_number": file_number,
                        "surplus": surplus,
                        "full_address": f"{street}, {city}, {state} {zipcode}".strip(", "),
                    }
                    records.append(record)

    log.info("Parsed %d records from %s", len(records), pdf_path.name)
    return records


def ingest_records(records: list[dict], source_file: str = "") -> dict:
    """Ingest parsed Denver records into the V2 database.

    Returns summary stats.
    """
    db.init_db()
    stats = {"total": len(records), "inserted": 0, "updated": 0, "skipped": 0}
    now = datetime.now(timezone.utc).isoformat()

    for rec in records:
        asset_id = _make_asset_id(rec["file_number"])
        rhash = _record_hash(rec)

        # Check if already exists
        existing = db.get_lead_by_id(asset_id)
        if existing:
            # Check if data changed
            if existing.get("record_hash") == rhash:
                stats["skipped"] += 1
                continue
            stats["updated"] += 1
        else:
            stats["inserted"] += 1

        # Compute days_remaining from sale_date (180-day window)
        days_remaining = None
        if rec["sale_date"]:
            try:
                sale_dt = datetime.fromisoformat(rec["sale_date"])
                deadline = sale_dt + timedelta(days=180)
                days_remaining = (deadline - datetime.now(timezone.utc).replace(tzinfo=None)).days
            except (ValueError, TypeError):
                pass

        # Determine data grade using V2 scoring logic
        surplus = rec["surplus"]
        completeness = 1.0 if all([rec["owner"], rec["street"], rec["sale_date"]]) else 0.5

        # Denver excess funds PDFs do NOT include indebtedness — confidence capped
        indebtedness = 0.0  # Not available from this source
        from verifuse_v2.daily_healthcheck import compute_confidence, compute_grade
        confidence = compute_confidence(surplus, indebtedness, rec["sale_date"],
                                        rec["owner"], rec["street"])
        grade, record_class = compute_grade(
            surplus, indebtedness, rec["sale_date"], days_remaining,
            confidence, completeness
        )

        # Insert/update asset
        with db.get_db() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO assets
                (asset_id, county, state, jurisdiction, case_number, asset_type,
                 source_name, statute_window, days_remaining, owner_of_record,
                 property_address, sale_date, estimated_surplus, overbid_amount,
                 completeness_score, confidence_score, data_grade,
                 record_hash, source_file, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, [
                asset_id, "Denver", "CO", "denver_co", rec["file_number"],
                "FORECLOSURE_SURPLUS", "denver_public_trustee_excess_funds",
                "180 days from sale_date (C.R.S. § 38-38-111)",
                days_remaining, rec["owner"], rec["full_address"],
                rec["sale_date"], surplus, surplus,
                completeness, confidence, grade,
                rhash, source_file, now, now,
            ])

            # Insert/update legal_status
            promoted_at = now if record_class == "ATTORNEY" else None
            closed_at = now if record_class == "CLOSED" else None
            close_reason = "kill_switch:statute_expired" if record_class == "CLOSED" else None

            conn.execute("""
                INSERT OR REPLACE INTO legal_status
                (asset_id, record_class, data_grade, days_remaining,
                 statute_window, last_evaluated_at, promoted_at, closed_at, close_reason)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, [
                asset_id, record_class, grade, days_remaining,
                "180 days from sale_date (C.R.S. § 38-38-111)",
                now, promoted_at, closed_at, close_reason,
            ])

    log.info("Ingestion complete: %d inserted, %d updated, %d skipped",
             stats["inserted"], stats["updated"], stats["skipped"])
    return stats


def run(pdf_path: str | None = None, year: int | None = None, month: int | None = None) -> dict:
    """Full pipeline: download (or use local file) → parse → ingest."""
    if pdf_path:
        path = Path(pdf_path)
    else:
        path = download_pdf(year=year, month=month)

    if not path:
        return {"error": "No PDF available"}

    records = parse_pdf(path)
    if not records:
        return {"error": f"No records parsed from {path.name}"}

    stats = ingest_records(records, source_file=str(path))

    # Log pipeline event
    with db.get_db() as conn:
        conn.execute("""
            INSERT INTO pipeline_events
            (asset_id, event_type, old_value, new_value, actor, reason, created_at)
            VALUES ('SYSTEM', 'SCRAPE', 'denver_pdf', ?, 'denver_pdf_parser',
                    ?, ?)
        """, [
            f"{stats['inserted']} new, {stats['updated']} updated",
            f"Parsed {path.name}: {stats['total']} records",
            datetime.now(timezone.utc).isoformat(),
        ])

    return stats


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Denver Excess Funds PDF Parser")
    parser.add_argument("--file", help="Path to a local PDF file")
    parser.add_argument("--year", type=int, help="Year to download (e.g., 2025)")
    parser.add_argument("--month", type=int, help="Month to download (1-12)")
    args = parser.parse_args()

    result = run(pdf_path=args.file, year=args.year, month=args.month)
    print()
    print("=" * 50)
    print("  DENVER PDF PARSER RESULTS")
    print("=" * 50)
    for k, v in result.items():
        print(f"  {k}: {v}")
    print("=" * 50)
