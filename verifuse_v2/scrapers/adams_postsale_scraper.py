"""
VERIFUSE V2 — Adams County Post-Sale List PDF Scraper

Downloads and parses weekly Post Sale List PDFs from the Adams County
Public Trustee. These PDFs contain 100% verifiable data including:
  - Foreclosure Number, Property Address, Buyer
  - Bid Amount, Deficiency Amount, Overbid Amount, Total Indebtedness

Source: https://apps.adcogov.org/PTForeclosureSearch/reports
PDF URL pattern:
  https://apps.adcogov.org/PTForeclosureSearch/Report_Files/
  POST%20SALE%20LIST%20{M}-{DD}-{YY}.pdf

Platform: GTS Search / ASP.NET
Sales: Wednesdays (weekly)

Usage:
  python -m verifuse_v2.scrapers.adams_postsale_scraper
  python -m verifuse_v2.scrapers.adams_postsale_scraper --file /path/to/local.pdf
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

RAW_PDF_DIR = Path(__file__).resolve().parent.parent / "data" / "raw_pdfs" / "adams"

# Adams County post-sale list URL pattern
PDF_BASE_URL = "https://apps.adcogov.org/PTForeclosureSearch/Report_Files/"
REPORTS_INDEX_URL = "https://apps.adcogov.org/PTForeclosureSearch/reports"


def _clean_money(raw: str) -> float:
    """Parse money values like '$155,300.00' → float."""
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
    return None


def _make_asset_id(foreclosure_number: str) -> str:
    """Deterministic asset_id from Adams foreclosure number."""
    clean = foreclosure_number.strip().replace(" ", "_")
    return f"adams_postsale_{clean}"


def _record_hash(rec: dict) -> str:
    """SHA-256 hash of key fields for change detection."""
    key = f"{rec['foreclosure_number']}|{rec['bid_amount']}|{rec['overbid']}|{rec['total_indebtedness']}"
    return hashlib.sha256(key.encode()).hexdigest()


def _generate_pdf_urls(weeks_back: int = 12) -> list[str]:
    """Generate candidate PDF URLs for recent sale dates.

    Adams County publishes on Wednesdays. URL format:
    POST SALE LIST {M}-{DD}-{YY}.pdf
    """
    urls = []
    now = datetime.now(timezone.utc)

    for week in range(weeks_back):
        dt = now - timedelta(weeks=week)
        # Find the nearest Wednesday (weekday=2)
        days_since_wed = (dt.weekday() - 2) % 7
        wed = dt - timedelta(days=days_since_wed)

        # Adams uses M-DD-YY format (no leading zero on month)
        month = wed.month
        day = wed.day
        year = wed.strftime("%y")

        fname = f"POST SALE LIST {month}-{day:02d}-{year}.pdf"
        url = PDF_BASE_URL + fname.replace(" ", "%20")
        urls.append(url)

        # Also try with leading zero on month
        fname2 = f"POST SALE LIST {month:02d}-{day:02d}-{year}.pdf"
        if fname2 != fname:
            urls.append(PDF_BASE_URL + fname2.replace(" ", "%20"))

    return urls


def download_postsale_pdfs(weeks_back: int = 12) -> list[Path]:
    """Download recent Post Sale List PDFs from Adams County."""
    RAW_PDF_DIR.mkdir(parents=True, exist_ok=True)
    downloaded = []

    # Method 1: Scrape the reports index for PDF links
    try:
        resp = requests.get(REPORTS_INDEX_URL, timeout=30)
        if resp.status_code == 200:
            pdf_links = re.findall(
                r'href=["\']([^"\']*(?:POST.?SALE|post.?sale)[^"\']*\.pdf)["\']',
                resp.text,
                re.IGNORECASE,
            )
            for link in pdf_links[:weeks_back]:
                if not link.startswith("http"):
                    link = f"https://apps.adcogov.org{link}"
                try:
                    pdf_resp = requests.get(link, timeout=30)
                    if pdf_resp.status_code == 200 and len(pdf_resp.content) > 500:
                        fname = link.split("/")[-1].replace("%20", "_")
                        path = RAW_PDF_DIR / fname
                        path.write_bytes(pdf_resp.content)
                        downloaded.append(path)
                        log.info("Downloaded: %s (%d bytes)", fname, len(pdf_resp.content))
                except requests.RequestException as e:
                    log.debug("Failed: %s: %s", link, e)
    except requests.RequestException as e:
        log.warning("Could not fetch reports index: %s", e)

    # Method 2: Try date-based URL guessing
    if not downloaded:
        for url in _generate_pdf_urls(weeks_back):
            try:
                resp = requests.get(url, timeout=15)
                if resp.status_code == 200 and len(resp.content) > 500:
                    content_type = resp.headers.get("content-type", "")
                    if "pdf" in content_type.lower() or resp.content[:5] == b"%PDF-":
                        fname = url.split("/")[-1].replace("%20", "_")
                        path = RAW_PDF_DIR / fname
                        path.write_bytes(resp.content)
                        downloaded.append(path)
                        log.info("Downloaded: %s (%d bytes)", fname, len(resp.content))
            except requests.RequestException:
                continue

    if not downloaded:
        log.warning("No Adams County post-sale PDFs downloaded")
    return downloaded


def _extract_sale_date_from_file(pdf_path: Path, text: str) -> Optional[str]:
    """Extract sale date from PDF header text or filename."""
    # Try header: "Foreclosure Sale List for Sale Date: February 11, 2026"
    header_match = re.search(
        r"Sale\s+Date:\s+(\w+\s+\d{1,2},?\s+\d{4})", text, re.IGNORECASE
    )
    if header_match:
        raw = header_match.group(1).replace(",", "")
        for fmt in ("%B %d %Y", "%b %d %Y"):
            try:
                dt = datetime.strptime(raw, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue

    # Try filename: POST_SALE_LIST_2-11-26.pdf
    fname_match = re.search(r"(\d{1,2})-(\d{1,2})-(\d{2,4})", pdf_path.name)
    if fname_match:
        m, d, y = fname_match.groups()
        if len(y) == 2:
            y = "20" + y
        try:
            return f"{y}-{int(m):02d}-{int(d):02d}"
        except ValueError:
            pass
    return None


def parse_postsale_pdf(pdf_path: str | Path) -> list[dict]:
    """Parse an Adams County Post Sale List PDF.

    Adams PDFs use a TEXT-BASED key-value format (NOT tables):
        Foreclosure #: A202580924
        Property Address: 2469 Devonshire Court, 34, Denver, CO, 80229
        Certificate of Purchase to: Guild Mortgage Company LLC
        Purchaser Address: 5887 Copley Drive, ...
        Bid Amount: $203,600.00
        Deficiency Amount: $43,004.82
        Overbid Amount: $0.00 Total Indebtedness: $246,604.82

    Note: "Overbid Amount" and "Total Indebtedness" are on the SAME line.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        log.error("PDF not found: %s", pdf_path)
        return []

    # Extract all text from all pages
    full_text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n"

    if not full_text.strip():
        log.warning("No text extracted from %s", pdf_path.name)
        return []

    # Extract the sale date from the header
    sale_date = _extract_sale_date_from_file(pdf_path, full_text)

    # Parse records using regex on labeled fields
    # Split into blocks by "Foreclosure #:" delimiter
    blocks = re.split(r"(?=Foreclosure\s*#\s*:)", full_text)

    records = []
    money_re = re.compile(r"\$[\d,]+\.?\d*")

    for block in blocks:
        block = block.strip()
        if not block.startswith("Foreclosure"):
            continue

        # Foreclosure number
        fc_match = re.search(r"Foreclosure\s*#\s*:\s*([A-Z0-9]+)", block)
        if not fc_match:
            continue
        foreclosure_num = fc_match.group(1)
        # Skip if it doesn't look like a real foreclosure number
        if not re.match(r"^[A-Z]\d{6,}", foreclosure_num):
            continue

        # Property Address (may span multiple lines before next label)
        addr_match = re.search(
            r"Property\s+Address\s*:\s*(.+?)(?=Certificate\s+of\s+Purchase|$)",
            block, re.DOTALL
        )
        property_address = ""
        if addr_match:
            # Join multi-line address, clean up
            raw_addr = addr_match.group(1).strip()
            property_address = re.sub(r"\s+", " ", raw_addr).strip()

        # Buyer (Certificate of Purchase to)
        buyer_match = re.search(
            r"Certificate\s+of\s+Purchase\s+to\s*:\s*(.+?)(?=Purchaser\s+Address|$)",
            block, re.DOTALL
        )
        buyer = ""
        if buyer_match:
            buyer = re.sub(r"\s+", " ", buyer_match.group(1).strip())

        # Bid Amount
        bid_match = re.search(r"Bid\s+Amount\s*:\s*(\$[\d,]+\.?\d*)", block)
        bid_amount = _clean_money(bid_match.group(1)) if bid_match else 0.0

        # Deficiency Amount
        def_match = re.search(r"Deficiency\s+Amount\s*:\s*(\$[\d,]+\.?\d*)", block)
        deficiency = _clean_money(def_match.group(1)) if def_match else 0.0

        # Overbid Amount (may be on same line as Total Indebtedness)
        over_match = re.search(r"Overbid\s+Amount\s*:\s*(\$[\d,]+\.?\d*)", block)
        overbid = _clean_money(over_match.group(1)) if over_match else 0.0

        # Total Indebtedness
        indebt_match = re.search(r"Total\s+Indebtedness\s*:\s*(\$[\d,]+\.?\d*)", block)
        total_indebtedness = _clean_money(indebt_match.group(1)) if indebt_match else 0.0

        # Compute surplus: overbid = bid - indebtedness (if overbid not explicit)
        surplus = overbid
        if surplus == 0.0 and bid_amount > 0 and total_indebtedness > 0:
            computed = bid_amount - total_indebtedness
            if computed > 0:
                surplus = computed

        record = {
            "foreclosure_number": foreclosure_num,
            "property_address": property_address,
            "buyer": buyer,
            "buyer_address": "",
            "bid_amount": bid_amount,
            "deficiency": deficiency,
            "overbid": overbid,
            "total_indebtedness": total_indebtedness,
            "sale_date": sale_date,
            "surplus": surplus,
        }
        records.append(record)

    log.info("Parsed %d records from %s", len(records), pdf_path.name)
    return records


def ingest_records(records: list[dict], source_file: str = "") -> dict:
    """Ingest parsed Adams County records into the V2 database."""
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
                 data_grade, record_hash, source_file,
                 created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, [
                asset_id, "Adams", "CO", "adams_co",
                rec["foreclosure_number"], "FORECLOSURE_SURPLUS",
                "adams_public_trustee_postsale",
                "180 days from sale_date (C.R.S. § 38-38-111)",
                days_remaining, rec.get("buyer", ""),
                rec["property_address"], rec["sale_date"],
                surplus, rec["overbid"], indebtedness,
                completeness, confidence, grade,
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

    log.info("Adams ingestion: %d inserted, %d updated, %d skipped, %d no surplus",
             stats["inserted"], stats["updated"], stats["skipped"], stats["no_surplus"])
    return stats


def run(pdf_path: str | None = None) -> dict:
    """Full pipeline: download → parse → ingest."""
    if pdf_path:
        paths = [Path(pdf_path)]
    else:
        paths = download_postsale_pdfs()

    if not paths:
        return {"error": "No Adams County post-sale PDFs available"}

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
            VALUES ('SYSTEM', 'SCRAPE', 'adams_postsale', ?, 'adams_postsale_scraper',
                    ?, ?)
        """, [
            f"{total_stats['inserted']} new, {total_stats['updated']} updated",
            f"Processed {total_stats['files']} PDFs: {total_stats['total']} records",
            datetime.now(timezone.utc).isoformat(),
        ])

    return total_stats


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Adams County Post-Sale Scraper")
    parser.add_argument("--file", help="Path to a local post-sale PDF file")
    args = parser.parse_args()

    result = run(pdf_path=args.file)
    print()
    print("=" * 50)
    print("  ADAMS COUNTY POST-SALE RESULTS")
    print("=" * 50)
    for k, v in result.items():
        print(f"  {k}: {v}")
    print("=" * 50)
