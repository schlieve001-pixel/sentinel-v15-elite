"""
VERIFUSE V2 — Weld County Pre-Sale Foreclosure PDF Scraper (Engine #8)

Downloads and parses weekly Pre Sale List PDFs from the Weld County
Public Trustee. PDFs are hosted on weld.gov with predictable URL patterns.

Fields: Foreclosure Number, Grantor, Address, Lender's Bid Amount,
Deficiency, Total Indebtedness.

Source: https://www.weld.gov/Government/Departments/Treasurer-Public-Trustee/Public-Trustee/Foreclosure-Reports
Search: https://www.wcpto.com/AllReports.aspx
PDF URL pattern:
  https://www.weld.gov/files/sharedassets/public/v/1/departments/
  treasure-and-public-trustee/documents/reports/public-trustee-reports/
  {YYYY}/pre-sale/{date}-pre-sale-list.pdf

Platform: GTS Search (wcpto.com)
Sales: Wednesdays via weld.realforeclose.com

Usage:
  python -m verifuse_v2.scrapers.weld_scraper
  python -m verifuse_v2.scrapers.weld_scraper --file /path/to/local.pdf
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
from bs4 import BeautifulSoup

from verifuse_v2.db import database as db
from verifuse_v2.daily_healthcheck import compute_confidence, compute_grade

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

RAW_PDF_DIR = Path(__file__).resolve().parent.parent / "data" / "raw_pdfs" / "weld"

REPORTS_URL = "https://www.weld.gov/Government/Departments/Treasurer-Public-Trustee/Public-Trustee/Foreclosure-Reports"
GTS_REPORTS_URL = "https://www.wcpto.com/AllReports.aspx"
PDF_BASE = (
    "https://www.weld.gov/files/sharedassets/public/v/1/departments/"
    "treasure-and-public-trustee/documents/reports/public-trustee-reports"
)

# Month name mappings for URL patterns
MONTH_NAMES = {
    1: "january", 2: "february", 3: "march", 4: "april",
    5: "may", 6: "june", 7: "july", 8: "august",
    9: "september", 10: "october", 11: "november", 12: "december",
}


def _clean_money(raw: str) -> float:
    if not raw:
        return 0.0
    cleaned = raw.replace("$", "").replace(",", "").replace(" ", "").strip()
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    try:
        return float(cleaned)
    except ValueError:
        log.warning("Could not parse money: %r", raw)
        return 0.0


def _parse_date(raw: str) -> Optional[str]:
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d", "%B %d %Y", "%B %d, %Y"):
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.year < 100:
                dt = dt.replace(year=dt.year + 2000)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _make_asset_id(foreclosure_number: str) -> str:
    clean = foreclosure_number.strip().replace(" ", "_")
    return f"weld_presale_{clean}"


def _record_hash(rec: dict) -> str:
    key = f"{rec['foreclosure_number']}|{rec['bid_amount']}|{rec['total_indebtedness']}|{rec['address']}"
    return hashlib.sha256(key.encode()).hexdigest()


def _generate_pdf_urls(weeks_back: int = 12) -> list[str]:
    """Generate candidate PDF URLs for recent sale dates."""
    urls = []
    now = datetime.now(timezone.utc)

    for week in range(weeks_back):
        dt = now - timedelta(weeks=week)
        # Find nearest Wednesday
        days_since_wed = (dt.weekday() - 2) % 7
        wed = dt - timedelta(days=days_since_wed)

        year = wed.year
        month = MONTH_NAMES[wed.month]
        day = wed.day

        # Pattern 1: 2026/pre-sale/2026.01.07-pre-sale-list.pdf
        date_dot = wed.strftime("%Y.%m.%d")
        urls.append(f"{PDF_BASE}/{year}/pre-sale/{date_dot}-pre-sale-list.pdf")

        # Pattern 2: 2024/pre-sale/july-17-2024-pre-sale-list.pdf
        urls.append(f"{PDF_BASE}/{year}/pre-sale/{month}-{day:02d}-{year}-pre-sale-list.pdf")
        urls.append(f"{PDF_BASE}/{year}/pre-sale/{month}-{day}-{year}-pre-sale-list.pdf")

        # Pattern 3: with v/3 instead of v/1
        date_dot_v3 = f"https://www.weld.gov/files/sharedassets/public/v/3/departments/treasure-and-public-trustee/documents/reports/public-trustee-reports/{year}/pre-sale/{date_dot}-pre-sale-list.pdf"
        urls.append(date_dot_v3)

    return urls


def download_presale_pdfs(weeks_back: int = 12) -> list[Path]:
    """Download Pre Sale List PDFs from Weld County."""
    RAW_PDF_DIR.mkdir(parents=True, exist_ok=True)
    downloaded = []

    # Method 1: Scrape reports page for PDF links
    for report_url in [REPORTS_URL, GTS_REPORTS_URL]:
        try:
            resp = requests.get(report_url, timeout=30)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if ".pdf" in href.lower() and "pre" in href.lower() and "sale" in href.lower():
                        if not href.startswith("http"):
                            href = "https://www.weld.gov" + href
                        try:
                            pdf_resp = requests.get(href, timeout=30)
                            if pdf_resp.status_code == 200 and pdf_resp.content[:5] == b"%PDF-":
                                fname = href.split("/")[-1].replace("%20", "_")
                                path = RAW_PDF_DIR / fname
                                if not path.exists():
                                    path.write_bytes(pdf_resp.content)
                                    log.info("Downloaded: %s (%d bytes)", fname, len(pdf_resp.content))
                                downloaded.append(path)
                        except requests.RequestException as e:
                            log.debug("Failed: %s: %s", href, e)
        except requests.RequestException as e:
            log.warning("Could not fetch %s: %s", report_url, e)

    # Method 2: Try date-based URL patterns
    if not downloaded:
        for url in _generate_pdf_urls(weeks_back):
            try:
                resp = requests.get(url, timeout=15)
                if resp.status_code == 200 and resp.content[:5] == b"%PDF-":
                    fname = url.split("/")[-1].replace("%20", "_")
                    path = RAW_PDF_DIR / fname
                    if not path.exists():
                        path.write_bytes(resp.content)
                        log.info("Downloaded: %s (%d bytes)", fname, len(resp.content))
                    downloaded.append(path)
            except requests.RequestException:
                continue

    if not downloaded:
        existing = list(RAW_PDF_DIR.glob("*.pdf"))
        if existing:
            log.info("Using %d existing Weld PDFs on disk", len(existing))
            return existing
        log.warning("No Weld County pre-sale PDFs available")

    return downloaded


def parse_presale_pdf(pdf_path: str | Path) -> list[dict]:
    """Parse a Weld County Pre Sale List PDF.

    Weld PDFs use the same GTS format as El Paso:
        Foreclosure: #: WLD202500XXX
        The Grantor: Owner Name
        Street Address: 123 Main St, Greeley, CO 80631
        Lender's Bid Amount: $ 320,912.46
        Deficiency: $ 0.00
        Total Indebtedness: $ 320,912.46
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        log.error("PDF not found: %s", pdf_path)
        return []

    full_text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n"

    if not full_text.strip():
        log.warning("No text extracted from %s", pdf_path.name)
        return []

    # Extract sale date
    sale_date = None
    header_match = re.search(
        r"Sale\s+Date:\s+(\w+\s+\d{1,2},?\s+\d{4})", full_text, re.IGNORECASE
    )
    if header_match:
        raw = header_match.group(1).replace(",", "")
        sale_date = _parse_date(raw)

    if not sale_date:
        fname_match = re.search(r"(\d{4})[._](\d{2})[._](\d{2})", pdf_path.name)
        if fname_match:
            sale_date = f"{fname_match.group(1)}-{fname_match.group(2)}-{fname_match.group(3)}"

    # Split into blocks
    blocks = re.split(r"(?=Foreclosure\s*:?\s*#\s*:)", full_text)

    records = []
    for block in blocks:
        block = block.strip()
        if not block.startswith("Foreclosure"):
            continue

        fc_match = re.search(r"Foreclosure\s*:?\s*#\s*:\s*(\w+)", block)
        if not fc_match:
            continue
        foreclosure_num = fc_match.group(1)

        grantor_match = re.search(
            r"(?:The\s+)?Grantor\s*:\s*(.+?)(?=Legal\s+Description|Street\s+Address|PARCEL|$)",
            block, re.DOTALL
        )
        owner = re.sub(r"\s+", " ", grantor_match.group(1).strip()) if grantor_match else ""

        addr_match = re.search(
            r"Street\s+Address\s*:\s*(.+?)(?=Current\s+Beneficiary|First\s+Publication|Lender|$)",
            block, re.DOTALL
        )
        address = re.sub(r"\s+", " ", addr_match.group(1).strip()) if addr_match else ""

        bid_match = re.search(r"Lender.?s?\s+Bid\s+Amount\s*:\s*(\$[\d,. ]+)", block)
        bid_amount = _clean_money(bid_match.group(1)) if bid_match else 0.0

        def_match = re.search(r"Deficiency\s*:\s*(\$[\d,. ]+)", block)
        deficiency = _clean_money(def_match.group(1)) if def_match else 0.0

        indebt_match = re.search(r"Total\s+Indebtedness\s*:\s*(\$[\d,. ]+)", block)
        total_indebtedness = _clean_money(indebt_match.group(1)) if indebt_match else 0.0

        record = {
            "foreclosure_number": foreclosure_num,
            "owner": owner,
            "address": address,
            "bid_amount": bid_amount,
            "deficiency": deficiency,
            "total_indebtedness": total_indebtedness,
            "sale_date": sale_date,
            "overbid": 0.0,
            "surplus": 0.0,
        }
        records.append(record)

    log.info("Parsed %d records from %s", len(records), pdf_path.name)
    return records


def ingest_records(records: list[dict], source_file: str = "") -> dict:
    """Ingest parsed Weld County records into the V2 database."""
    db.init_db()
    stats = {"total": len(records), "inserted": 0, "updated": 0, "skipped": 0}
    now = datetime.now(timezone.utc).isoformat()

    for rec in records:
        if rec["total_indebtedness"] <= 0:
            stats["skipped"] += 1
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

        days_remaining = None
        if rec["sale_date"]:
            try:
                sale_dt = datetime.fromisoformat(rec["sale_date"])
                deadline = sale_dt + timedelta(days=180)
                days_remaining = (deadline - datetime.now(timezone.utc).replace(tzinfo=None)).days
            except (ValueError, TypeError):
                pass

        indebtedness = rec["total_indebtedness"]
        surplus = rec["surplus"]
        completeness = 0.8 if all([rec["owner"], rec["address"], rec["sale_date"]]) else 0.5

        confidence = compute_confidence(surplus, indebtedness, rec["sale_date"], rec["owner"], rec["address"])
        grade = "SILVER"
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
                asset_id, "Weld", "CO", "weld_co",
                rec["foreclosure_number"], "FORECLOSURE_PRESALE",
                "weld_public_trustee_presale",
                "180 days from sale_date (C.R.S. § 38-38-111)",
                days_remaining, rec["owner"], rec["address"], rec["sale_date"],
                surplus, rec["overbid"], indebtedness,
                completeness, confidence, grade, rhash, source_file, now, now,
            ])

            conn.execute("""
                INSERT OR REPLACE INTO legal_status
                (asset_id, record_class, data_grade, days_remaining,
                 statute_window, last_evaluated_at)
                VALUES (?,?,?,?,?,?)
            """, [asset_id, record_class, grade, days_remaining,
                  "180 days from sale_date (C.R.S. § 38-38-111)", now])

    log.info("Weld ingestion: %d inserted, %d updated, %d skipped",
             stats["inserted"], stats["updated"], stats["skipped"])
    return stats


def run(pdf_path: str | None = None) -> dict:
    """Full pipeline: download -> parse -> ingest."""
    if pdf_path:
        paths = [Path(pdf_path)]
    else:
        paths = download_presale_pdfs()

    if not paths:
        return {"error": "No Weld County pre-sale PDFs available"}

    total_stats = {"total": 0, "inserted": 0, "updated": 0, "skipped": 0, "files": 0}

    for path in paths:
        records = parse_presale_pdf(path)
        if not records:
            log.warning("No records from %s", path.name)
            continue

        stats = ingest_records(records, source_file=str(path))
        total_stats["files"] += 1
        for k in ("total", "inserted", "updated", "skipped"):
            total_stats[k] += stats.get(k, 0)

    with db.get_db() as conn:
        conn.execute("""
            INSERT INTO pipeline_events
            (asset_id, event_type, old_value, new_value, actor, reason, created_at)
            VALUES ('SYSTEM', 'SCRAPE', 'weld_presale', ?, 'weld_scraper', ?, ?)
        """, [
            f"{total_stats['inserted']} new, {total_stats['updated']} updated",
            f"Processed {total_stats['files']} PDFs: {total_stats['total']} records",
            datetime.now(timezone.utc).isoformat(),
        ])

    return total_stats


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Weld County Pre-Sale Scraper")
    parser.add_argument("--file", help="Path to a local pre-sale PDF file")
    args = parser.parse_args()

    result = run(pdf_path=args.file)
    print()
    print("=" * 50)
    print("  WELD COUNTY PRE-SALE RESULTS")
    print("=" * 50)
    for k, v in result.items():
        print(f"  {k}: {v}")
    print("=" * 50)
