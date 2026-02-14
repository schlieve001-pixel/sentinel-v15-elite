"""
VERIFUSE V2 — El Paso County Post-Sale List PDF Scraper

Downloads and parses weekly Post Sale List PDFs from the El Paso County
Public Trustee. These PDFs contain 100% verifiable data including:
  - Foreclosure Number, Property Address, Buyer
  - Bid Amount, Deficiency Amount, Overbid Amount, Total Indebtedness

Source: https://elpasopublictrustee.com/foreclosure-reports/
Platform: GTS Search (elpasopublictrustee.com/GTSSearch/)
Sales: Wednesdays at 10:00 AM MT via RealAuction.com

Usage:
  python -m verifuse_v2.scrapers.elpaso_postsale_scraper
  python -m verifuse_v2.scrapers.elpaso_postsale_scraper --file /path/to/local.pdf
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pdfplumber
import requests

from verifuse_v2.db import database as db
from verifuse_v2.daily_healthcheck import compute_confidence, compute_grade

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

RAW_PDF_DIR = Path(__file__).resolve().parent.parent / "data" / "raw_pdfs" / "elpaso"

# El Paso County GTS Search report URLs
REPORT_INDEX_URL = "https://elpasopublictrustee.com/foreclosure-reports/"
GTS_REPORT_BASE = "https://elpasopublictrustee.com/GTSSearch/report"

# Post-sale list report type (GTS system)
POST_SALE_REPORT_TYPE = 3  # type=1 is pre-sale, type=3 is post-sale


def _clean_money(raw: str) -> float:
    """Parse money values like '$155,300.00' or '$ 2 99,937.74' → float."""
    if not raw:
        return 0.0
    cleaned = raw.replace("$", "").replace(",", "").replace(" ", "").strip()
    # Handle parentheses for negative values
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    try:
        return float(cleaned)
    except ValueError:
        log.warning("Could not parse money: %r", raw)
        return 0.0


def _parse_date(raw: str) -> Optional[str]:
    """Parse dates like '06/06/25', '10/05/2024' → ISO 8601."""
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.year < 100:
                dt = dt.replace(year=dt.year + 2000)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    log.warning("Could not parse date: %r", raw)
    return None


def _make_asset_id(foreclosure_number: str) -> str:
    """Deterministic asset_id from El Paso foreclosure number."""
    clean = foreclosure_number.strip().replace(" ", "_")
    return f"elpaso_postsale_{clean}"


def _record_hash(rec: dict) -> str:
    """SHA-256 hash of key fields for change detection."""
    key = f"{rec['foreclosure_number']}|{rec['bid_amount']}|{rec['overbid']}|{rec['total_indebtedness']}"
    return hashlib.sha256(key.encode()).hexdigest()


def download_postsale_pdfs(weeks_back: int = 8) -> list[Path]:
    """Download recent Post Sale List PDFs from El Paso County.

    El Paso uses GTS Search — we try to fetch the report page and
    extract PDF links. Falls back to date-based URL guessing.
    """
    RAW_PDF_DIR.mkdir(parents=True, exist_ok=True)
    downloaded = []

    # Try fetching the reports index page for PDF links
    try:
        resp = requests.get(REPORT_INDEX_URL, timeout=30)
        if resp.status_code == 200:
            # Look for PDF links in the page
            pdf_links = re.findall(
                r'href=["\']([^"\']*(?:post.?sale|PostSale)[^"\']*\.pdf)["\']',
                resp.text,
                re.IGNORECASE,
            )
            for link in pdf_links[:weeks_back]:
                if not link.startswith("http"):
                    link = f"https://elpasopublictrustee.com{link}"
                try:
                    pdf_resp = requests.get(link, timeout=30)
                    if pdf_resp.status_code == 200 and len(pdf_resp.content) > 500:
                        fname = link.split("/")[-1]
                        path = RAW_PDF_DIR / fname
                        path.write_bytes(pdf_resp.content)
                        downloaded.append(path)
                        log.info("Downloaded: %s (%d bytes)", fname, len(pdf_resp.content))
                except requests.RequestException as e:
                    log.debug("Failed to download %s: %s", link, e)
    except requests.RequestException as e:
        log.warning("Could not fetch report index: %s", e)

    # Also try GTS report endpoint
    if not downloaded:
        try:
            resp = requests.get(
                GTS_REPORT_BASE,
                params={"t": POST_SALE_REPORT_TYPE},
                timeout=30,
            )
            if resp.status_code == 200 and len(resp.content) > 500:
                content_type = resp.headers.get("content-type", "")
                if "pdf" in content_type.lower():
                    path = RAW_PDF_DIR / "elpaso_postsale_latest.pdf"
                    path.write_bytes(resp.content)
                    downloaded.append(path)
                    log.info("Downloaded GTS post-sale report (%d bytes)", len(resp.content))
        except requests.RequestException as e:
            log.debug("GTS report fetch failed: %s", e)

    if not downloaded:
        log.warning("No El Paso post-sale PDFs downloaded")
    return downloaded


def parse_postsale_pdf(pdf_path: str | Path) -> list[dict]:
    """Parse an El Paso County Post Sale List PDF.

    Expected columns (in order):
        Foreclosure # | Property Address | Certificate of Purchase To |
        Purchaser Address | Bid Amount | Deficiency Amount |
        Overbid Amount | Total Indebtedness

    Returns list of dicts with all financial fields.
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
                    if not row or len(row) < 5:
                        continue

                    first_cell = (row[0] or "").strip()

                    # Skip headers, footers, blank rows
                    if not first_cell:
                        continue
                    if any(h in first_cell.lower() for h in [
                        "foreclosure", "property", "certificate", "page",
                        "post sale", "public trustee", "report", "date",
                    ]):
                        continue

                    # Parse the row — column positions may shift
                    foreclosure_num = first_cell
                    property_address = (row[1] or "").strip() if len(row) > 1 else ""
                    buyer = (row[2] or "").strip() if len(row) > 2 else ""
                    buyer_address = (row[3] or "").strip() if len(row) > 3 else ""

                    # Financial columns — scan remaining cells for money values
                    money_values = []
                    for cell in row[4:] if len(row) > 4 else []:
                        cell_str = (cell or "").strip()
                        if cell_str:
                            money_values.append(_clean_money(cell_str))

                    # Expected order: bid_amount, deficiency, overbid, total_indebtedness
                    bid_amount = money_values[0] if len(money_values) > 0 else 0.0
                    deficiency = money_values[1] if len(money_values) > 1 else 0.0
                    overbid = money_values[2] if len(money_values) > 2 else 0.0
                    total_indebtedness = money_values[3] if len(money_values) > 3 else 0.0

                    # If we have fewer money columns, try to detect from headers
                    # Also handle case where overbid = bid - indebtedness
                    if overbid == 0.0 and bid_amount > 0 and total_indebtedness > 0:
                        computed_overbid = bid_amount - total_indebtedness
                        if computed_overbid > 0:
                            overbid = computed_overbid

                    # Extract sale date from foreclosure number if possible
                    # El Paso format: EPC202XXXXXXX
                    sale_date = None
                    date_match = re.search(r"EPC(\d{4})(\d{2})", foreclosure_num)
                    if date_match:
                        year = int(date_match.group(1))
                        month = int(date_match.group(2))
                        if 2020 <= year <= 2030 and 1 <= month <= 12:
                            sale_date = f"{year}-{month:02d}-01"

                    # Also scan row for date patterns
                    if not sale_date:
                        for cell in row:
                            cell_str = (cell or "").strip()
                            if re.match(r"\d{2}/\d{2}/\d{2,4}", cell_str):
                                sale_date = _parse_date(cell_str)
                                if sale_date:
                                    break

                    record = {
                        "foreclosure_number": foreclosure_num,
                        "property_address": property_address,
                        "buyer": buyer,
                        "buyer_address": buyer_address,
                        "bid_amount": bid_amount,
                        "deficiency": deficiency,
                        "overbid": overbid,
                        "total_indebtedness": total_indebtedness,
                        "sale_date": sale_date,
                        "surplus": overbid,  # Overbid IS the surplus
                    }
                    records.append(record)

    log.info("Parsed %d records from %s", len(records), pdf_path.name)
    return records


def ingest_records(records: list[dict], source_file: str = "") -> dict:
    """Ingest parsed El Paso records into the V2 database."""
    db.init_db()
    stats = {"total": len(records), "inserted": 0, "updated": 0, "skipped": 0, "no_surplus": 0}
    now = datetime.now(timezone.utc).isoformat()

    for rec in records:
        surplus = rec["overbid"]
        if surplus < 1000:
            stats["no_surplus"] += 1
            continue

        asset_id = _make_asset_id(rec["foreclosure_number"])
        rhash = _record_hash(rec)

        existing = db.get_lead_by_id(asset_id)
        if existing:
            if existing.get("record_hash") == rhash:
                stats["skipped"] += 1
                continue
            stats["updated"] += 1
        else:
            stats["inserted"] += 1

        # Days remaining (180-day window from sale)
        days_remaining = None
        if rec["sale_date"]:
            try:
                sale_dt = datetime.fromisoformat(rec["sale_date"])
                deadline = sale_dt + timedelta(days=180)
                days_remaining = (deadline - datetime.now(timezone.utc).replace(tzinfo=None)).days
            except (ValueError, TypeError):
                pass

        indebtedness = rec["total_indebtedness"]
        completeness = 1.0 if all([
            rec["property_address"], rec["sale_date"], indebtedness > 0
        ]) else 0.8 if rec["property_address"] else 0.5

        confidence = compute_confidence(
            surplus, indebtedness, rec["sale_date"],
            rec.get("buyer", ""), rec["property_address"]
        )
        grade, record_class = compute_grade(
            surplus, indebtedness, rec["sale_date"],
            days_remaining, confidence, completeness
        )

        with db.get_db() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO assets
                (asset_id, county, state, jurisdiction, case_number, asset_type,
                 source_name, statute_window, days_remaining, owner_of_record,
                 property_address, sale_date, estimated_surplus, overbid_amount,
                 total_indebtedness, completeness_score, confidence_score,
                 data_grade, record_class, record_hash, source_file,
                 created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, [
                asset_id, "El Paso", "CO", "elpaso_co",
                rec["foreclosure_number"], "FORECLOSURE_SURPLUS",
                "elpaso_public_trustee_postsale",
                "180 days from sale_date (C.R.S. § 38-38-111)",
                days_remaining, rec.get("buyer", ""),
                rec["property_address"], rec["sale_date"],
                surplus, rec["overbid"], indebtedness,
                completeness, confidence, grade, record_class,
                rhash, source_file, now, now,
            ])

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

    log.info("El Paso ingestion: %d inserted, %d updated, %d skipped, %d no surplus",
             stats["inserted"], stats["updated"], stats["skipped"], stats["no_surplus"])
    return stats


def run(pdf_path: str | None = None) -> dict:
    """Full pipeline: download → parse → ingest."""
    if pdf_path:
        paths = [Path(pdf_path)]
    else:
        paths = download_postsale_pdfs()

    if not paths:
        return {"error": "No El Paso post-sale PDFs available"}

    total_stats = {"total": 0, "inserted": 0, "updated": 0, "skipped": 0, "no_surplus": 0, "files": 0}

    for path in paths:
        records = parse_postsale_pdf(path)
        if not records:
            log.warning("No records from %s", path.name)
            continue

        stats = ingest_records(records, source_file=str(path))
        total_stats["files"] += 1
        for k in ("total", "inserted", "updated", "skipped", "no_surplus"):
            total_stats[k] += stats.get(k, 0)

    # Log pipeline event
    with db.get_db() as conn:
        conn.execute("""
            INSERT INTO pipeline_events
            (asset_id, event_type, old_value, new_value, actor, reason, created_at)
            VALUES ('SYSTEM', 'SCRAPE', 'elpaso_postsale', ?, 'elpaso_postsale_scraper',
                    ?, ?)
        """, [
            f"{total_stats['inserted']} new, {total_stats['updated']} updated",
            f"Processed {total_stats['files']} PDFs: {total_stats['total']} records",
            datetime.now(timezone.utc).isoformat(),
        ])

    return total_stats


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="El Paso County Post-Sale Scraper")
    parser.add_argument("--file", help="Path to a local post-sale PDF file")
    args = parser.parse_args()

    result = run(pdf_path=args.file)
    print()
    print("=" * 50)
    print("  EL PASO COUNTY POST-SALE RESULTS")
    print("=" * 50)
    for k, v in result.items():
        print(f"  {k}: {v}")
    print("=" * 50)
