"""
VERIFUSE V2 — El Paso County Pre-Sale Foreclosure PDF Scraper

Downloads and parses weekly Pre Sale List PDFs from the El Paso County
Public Trustee (GTS Search system). These PDFs contain verified data:
  - Foreclosure Number, Grantor (owner), Street Address
  - Lender's Bid Amount, Deficiency, Total Indebtedness

Note: El Paso does NOT publish a Post Sale List with overbid data.
Pre-sale data provides verified indebtedness for cross-referencing
with auction results. Overbid (surplus) is unknown until the sale
occurs, so these are ingested as PIPELINE leads awaiting outcome data.

Source: https://elpasopublictrustee.com/GTSSearch/reports
PDF pattern: Report_Files/{YYYYMMDD} Pre Sale list.pdf

Also downloads archived Post Sale Continuance lists from type=8 reports
which link to individual weekly PDFs with sale outcome data.

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
from bs4 import BeautifulSoup

from verifuse_v2.db import database as db
from verifuse_v2.daily_healthcheck import compute_confidence, compute_grade

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

RAW_PDF_DIR = Path(__file__).resolve().parent.parent / "data" / "raw_pdfs" / "elpaso"

GTS_BASE = "https://elpasopublictrustee.com/GTSSearch/"
PRE_SALE_REPORT_URL = GTS_BASE + "report?t=1"
ARCHIVED_CONTINUANCE_URL = GTS_BASE + "report?t=8"


def _clean_money(raw: str) -> float:
    """Parse money values like '$ 320,912.46' → float."""
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
    """Parse dates in various formats → ISO 8601."""
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
    """Deterministic asset_id from El Paso foreclosure number."""
    clean = foreclosure_number.strip().replace(" ", "_")
    return f"elpaso_presale_{clean}"


def _record_hash(rec: dict) -> str:
    """SHA-256 hash of key fields for change detection."""
    key = f"{rec['foreclosure_number']}|{rec['bid_amount']}|{rec['total_indebtedness']}|{rec['address']}"
    return hashlib.sha256(key.encode()).hexdigest()


def download_presale_pdfs(weeks_back: int = 12) -> list[Path]:
    """Download Pre Sale List PDFs from El Paso GTS Search.

    Scrapes the report page (type=1) for current PDF link, and also
    tries date-based URL guessing for recent weeks.
    """
    RAW_PDF_DIR.mkdir(parents=True, exist_ok=True)
    downloaded = []

    # Method 1: Get current pre-sale PDF from report page
    try:
        resp = requests.get(PRE_SALE_REPORT_URL, timeout=30)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if ".pdf" in href.lower() and "sale" in href.lower():
                    if not href.startswith("http"):
                        href = GTS_BASE + href
                    try:
                        pdf_resp = requests.get(href, timeout=30)
                        if pdf_resp.status_code == 200 and pdf_resp.content[:5] == b"%PDF-":
                            fname = href.split("/")[-1].replace("%20", "_")
                            path = RAW_PDF_DIR / fname
                            path.write_bytes(pdf_resp.content)
                            downloaded.append(path)
                            log.info("Downloaded: %s (%d bytes)", fname, len(pdf_resp.content))
                    except requests.RequestException as e:
                        log.debug("Failed: %s: %s", href, e)
    except requests.RequestException as e:
        log.warning("Could not fetch pre-sale report page: %s", e)

    # Method 2: Try date-based URL patterns for recent weeks
    now = datetime.now(timezone.utc)
    for week in range(weeks_back):
        dt = now - timedelta(weeks=week)
        # El Paso sales on Wednesdays — find nearest Wednesday
        days_since_wed = (dt.weekday() - 2) % 7
        wed = dt - timedelta(days=days_since_wed)
        date_str = wed.strftime("%Y%m%d")

        # Try various filename patterns observed
        patterns = [
            f"Report_Files/{date_str} Pre Sale list.pdf",
            f"Report_Files/{date_str} Pre Sale List.pdf",
            f"Report_Files/{date_str}%20Pre%20Sale%20list.pdf",
        ]
        for pattern in patterns:
            url = GTS_BASE + pattern.replace(" ", "%20")
            try:
                pdf_resp = requests.get(url, timeout=15)
                if pdf_resp.status_code == 200 and pdf_resp.content[:5] == b"%PDF-":
                    fname = f"elpaso_presale_{date_str}.pdf"
                    path = RAW_PDF_DIR / fname
                    if not path.exists():
                        path.write_bytes(pdf_resp.content)
                        downloaded.append(path)
                        log.info("Downloaded: %s (%d bytes)", fname, len(pdf_resp.content))
                    break
            except requests.RequestException:
                continue

    if not downloaded:
        # Method 3: Use any existing files on disk
        existing = list(RAW_PDF_DIR.glob("*.pdf"))
        if existing:
            log.info("Using %d existing El Paso PDFs on disk", len(existing))
            return existing
        log.warning("No El Paso pre-sale PDFs available")

    return downloaded


def parse_presale_pdf(pdf_path: str | Path) -> list[dict]:
    """Parse an El Paso County Pre Sale List PDF.

    El Paso PDFs use TEXT-BASED key-value format:
        Foreclosure: #: EPC202500155
        The Grantor: Careli Monserrat Alejandre
        Street Address: 6133 Callan Drive, Colorado Springs, CO 80927
        Lender's Bid Amount: $ 320,912.46
        Deficiency: $ 0.00
        Total Indebtedness: $ 320,912.46

    Returns list of dicts with financial fields.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        log.error("PDF not found: %s", pdf_path)
        return []

    # Extract all text
    full_text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n"

    if not full_text.strip():
        log.warning("No text extracted from %s", pdf_path.name)
        return []

    # Extract sale date from header
    sale_date = None
    header_match = re.search(
        r"Sale\s+Date:\s+(\w+\s+\d{1,2},?\s+\d{4})", full_text, re.IGNORECASE
    )
    if header_match:
        raw = header_match.group(1).replace(",", "")
        sale_date = _parse_date(raw)

    # Split into blocks by "Foreclosure: #:" delimiter
    blocks = re.split(r"(?=Foreclosure\s*:\s*#\s*:)", full_text)

    records = []
    for block in blocks:
        block = block.strip()
        if not block.startswith("Foreclosure"):
            continue

        # Foreclosure number: "Foreclosure: #: EPC202500155"
        fc_match = re.search(r"Foreclosure\s*:\s*#\s*:\s*(EPC\d+)", block)
        if not fc_match:
            continue
        foreclosure_num = fc_match.group(1)

        # Grantor (owner): "The Grantor: Name"
        grantor_match = re.search(
            r"The\s+Grantor\s*:\s*(.+?)(?=Legal\s+Description|Street\s+Address|PARCEL|$)",
            block, re.DOTALL
        )
        owner = ""
        if grantor_match:
            owner = re.sub(r"\s+", " ", grantor_match.group(1).strip())

        # Street Address
        addr_match = re.search(
            r"Street\s+Address\s*:\s*(.+?)(?=Current\s+Beneficiary|First\s+Publication|Lender|$)",
            block, re.DOTALL
        )
        address = ""
        if addr_match:
            address = re.sub(r"\s+", " ", addr_match.group(1).strip())

        # Lender's Bid Amount
        bid_match = re.search(r"Lender.?s?\s+Bid\s+Amount\s*:\s*(\$[\d,. ]+)", block)
        bid_amount = _clean_money(bid_match.group(1)) if bid_match else 0.0

        # Deficiency
        def_match = re.search(r"Deficiency\s*:\s*(\$[\d,. ]+)", block)
        deficiency = _clean_money(def_match.group(1)) if def_match else 0.0

        # Total Indebtedness
        indebt_match = re.search(r"Total\s+Indebtedness\s*:\s*(\$[\d,. ]+)", block)
        total_indebtedness = _clean_money(indebt_match.group(1)) if indebt_match else 0.0

        # Beneficiary (lender name)
        bene_match = re.search(
            r"Current\s+Beneficiary\s+Name\s*:\s*(.+?)(?=First\s+Publication|$)",
            block, re.DOTALL
        )
        beneficiary = ""
        if bene_match:
            beneficiary = re.sub(r"\s+", " ", bene_match.group(1).strip())

        record = {
            "foreclosure_number": foreclosure_num,
            "owner": owner,
            "address": address,
            "bid_amount": bid_amount,
            "deficiency": deficiency,
            "total_indebtedness": total_indebtedness,
            "beneficiary": beneficiary,
            "sale_date": sale_date,
            # Pre-sale: overbid unknown until auction completes
            "overbid": 0.0,
            "surplus": 0.0,
        }
        records.append(record)

    log.info("Parsed %d records from %s", len(records), pdf_path.name)
    return records


def ingest_records(records: list[dict], source_file: str = "") -> dict:
    """Ingest parsed El Paso records into the V2 database.

    Pre-sale records are ingested as PIPELINE leads with known
    indebtedness. They'll be upgraded when auction outcome data
    (overbid/surplus) becomes available.
    """
    db.init_db()
    stats = {"total": len(records), "inserted": 0, "updated": 0, "skipped": 0}
    now = datetime.now(timezone.utc).isoformat()

    for rec in records:
        # Skip if no meaningful indebtedness
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

        # Days remaining (180-day window from sale date)
        days_remaining = None
        if rec["sale_date"]:
            try:
                sale_dt = datetime.fromisoformat(rec["sale_date"])
                deadline = sale_dt + timedelta(days=180)
                days_remaining = (deadline - datetime.now(timezone.utc).replace(tzinfo=None)).days
            except (ValueError, TypeError):
                pass

        indebtedness = rec["total_indebtedness"]
        surplus = rec["surplus"]  # 0 for pre-sale (unknown until auction)

        completeness = 0.8 if all([
            rec["owner"], rec["address"], rec["sale_date"]
        ]) else 0.5

        # Pre-sale: confidence reflects known indebtedness but unknown outcome
        confidence = compute_confidence(
            surplus, indebtedness, rec["sale_date"],
            rec["owner"], rec["address"]
        )
        # Pre-sale leads are SILVER/PIPELINE (awaiting auction outcome)
        grade = "SILVER"
        record_class = "PIPELINE"

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
                asset_id, "El Paso", "CO", "elpaso_co",
                rec["foreclosure_number"], "FORECLOSURE_PRESALE",
                "elpaso_public_trustee_presale",
                "180 days from sale_date (C.R.S. § 38-38-111)",
                days_remaining, rec["owner"],
                rec["address"], rec["sale_date"],
                surplus, rec["overbid"], indebtedness,
                completeness, confidence, grade,
                rhash, source_file, now, now,
            ])

            conn.execute("""
                INSERT OR REPLACE INTO legal_status
                (asset_id, record_class, data_grade, days_remaining,
                 statute_window, last_evaluated_at)
                VALUES (?,?,?,?,?,?)
            """, [
                asset_id, record_class, grade, days_remaining,
                "180 days from sale_date (C.R.S. § 38-38-111)", now,
            ])

    log.info("El Paso ingestion: %d inserted, %d updated, %d skipped",
             stats["inserted"], stats["updated"], stats["skipped"])
    return stats


def run(pdf_path: str | None = None) -> dict:
    """Full pipeline: download → parse → ingest."""
    if pdf_path:
        paths = [Path(pdf_path)]
    else:
        paths = download_presale_pdfs()

    if not paths:
        return {"error": "No El Paso pre-sale PDFs available"}

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

    # Log pipeline event
    with db.get_db() as conn:
        conn.execute("""
            INSERT INTO pipeline_events
            (asset_id, event_type, old_value, new_value, actor, reason, created_at)
            VALUES ('SYSTEM', 'SCRAPE', 'elpaso_presale', ?, 'elpaso_presale_scraper',
                    ?, ?)
        """, [
            f"{total_stats['inserted']} new, {total_stats['updated']} updated",
            f"Processed {total_stats['files']} PDFs: {total_stats['total']} records",
            datetime.now(timezone.utc).isoformat(),
        ])

    return total_stats


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="El Paso County Pre-Sale Scraper")
    parser.add_argument("--file", help="Path to a local pre-sale PDF file")
    args = parser.parse_args()

    result = run(pdf_path=args.file)
    print()
    print("=" * 50)
    print("  EL PASO COUNTY PRE-SALE RESULTS")
    print("=" * 50)
    for k, v in result.items():
        print(f"  {k}: {v}")
    print("=" * 50)
