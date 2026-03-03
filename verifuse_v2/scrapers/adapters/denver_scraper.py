"""
Denver County Public Trustee — PDF Scraper
==========================================
Parses real weekly auction results + excess funds list from denvergov.org.

Data sources (updated every Thursday / monthly):
  Sales Results: Current_Sales_Results.pdf  → overbid amounts, sale dates, owner names
  Excess Funds:  excess-funds-list-as-of-*.pdf → confirmed unclaimed surplus held by Trustee

Grade logic (fail-closed, consistent with pipeline):
  Excess funds + restriction expired  → GOLD  (money confirmed + eligible to contact)
  Excess funds + restriction active   → SILVER (confirmed money, timer still running)
  Sales result overbid + confirmed    → BRONZE (math confirmed, restriction may apply)

C.R.S. § 38-38-111(5): 6-month contact restriction from sale date.

Usage (direct):
    python3 -m verifuse_v2.scrapers.adapters.denver_scraper

Usage (via bin/vf):
    bin/vf denver-scrape
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

log = logging.getLogger(__name__)

# ── Public URLs — Denver Clerk & Recorder ─────────────────────────────────────

SALES_RESULTS_URL = (
    "https://www.denvergov.org/media/denvergov/clerkandrecorder/"
    "AuctionResults/Current_Sales_Results.pdf"
)

# Excess funds list — updated monthly; URL encodes the date so we probe a range
EXCESS_FUNDS_URL_PATTERN = (
    "https://www.denvergov.org/files/assets/public/v/1/clerk-and-recorder/"
    "documents/recording-division/public-trustee-amp-recorder/{year}/"
    "excess-funds-list-as-of-{month}.{day}.{yy}.pdf"
)

_FALLBACK_EXCESS_URL = (
    "https://www.denvergov.org/files/assets/public/v/1/clerk-and-recorder/"
    "documents/recording-division/public-trustee-amp-recorder/2026/"
    "excess-funds-list-as-of-2.4.26.pdf"
)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; VeriFuse/2.0; +https://verifuse.tech)",
    "Accept": "application/pdf,*/*",
}

_RESTRICTION_DAYS = 182  # 6 months ≈ 182 days (§ 38-38-111)
_COUNTY = "denver"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _db_path() -> str:
    return os.getenv(
        "VERIFUSE_DB_PATH",
        str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent / "data" / "verifuse_v2.db"),
    )


def _lead_id(case_number: str) -> str:
    h = hashlib.md5(f"denver_{case_number}".encode()).hexdigest()[:12]
    return f"denver_pdf_{h}"


def _parse_amount(text: str) -> float:
    """Parse a dollar amount string that may contain spaces, e.g. '$ 3 66,672.27' → 366672.27."""
    # Remove $ and spaces, then rejoin digit groups around commas
    text = text.replace("$", "").strip()
    # Collapse internal spaces: '3 66,672.27' → '366,672.27'
    # Pattern: single/double digit followed by space followed by more digits
    text = re.sub(r"(\d)\s+(\d)", r"\1\2", text)
    text = re.sub(r"[\s,]", "", text)
    try:
        return float(text)
    except ValueError:
        return 0.0


def _parse_date(text: str) -> str | None:
    """Parse 'MM/DD/YY' or 'MM/DD/YYYY' → 'YYYY-MM-DD'."""
    text = text.strip()
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _restriction_status(sale_date_str: str | None) -> str:
    """Return 'ACTIVE' (within 6 months) or 'EXPIRED'."""
    if not sale_date_str:
        return "ACTIVE"
    try:
        sd = datetime.strptime(sale_date_str, "%Y-%m-%d").date()
        cutoff = sd + timedelta(days=_RESTRICTION_DAYS)
        return "ACTIVE" if date.today() < cutoff else "EXPIRED"
    except ValueError:
        return "ACTIVE"


def _fetch_pdf(url: str) -> bytes | None:
    """Download a PDF. Returns bytes or None on failure."""
    import urllib.request
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = r.read()
        log.info("Downloaded %d bytes from %s", len(data), url)
        return data
    except Exception as exc:
        log.warning("Failed to fetch %s: %s", url, exc)
        return None


def _probe_excess_funds_url() -> str:
    """Probe for the most recent excess funds PDF URL."""
    import urllib.request
    today = date.today()
    # Try up to 60 days back to find the current monthly list
    for delta in range(0, 60, 7):
        check = today - timedelta(days=delta)
        url = EXCESS_FUNDS_URL_PATTERN.format(
            year=check.year,
            month=check.month,
            day=check.day,
            yy=str(check.year)[-2:],
        )
        try:
            req = urllib.request.Request(url, headers=_HEADERS, method="HEAD")
            with urllib.request.urlopen(req, timeout=5):
                return url
        except Exception:
            continue
    return _FALLBACK_EXCESS_URL


# ── PDF Parsers ───────────────────────────────────────────────────────────────

def parse_sales_results(pdf_bytes: bytes) -> list[dict]:
    """
    Parse Current_Sales_Results.pdf.
    Returns list of case dicts with: case_number, owner_name, property_address,
    sale_date, total_due, winning_bid, overbid, restriction_status, data_grade.
    """
    import pdfplumber

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    except Exception as exc:
        log.error("pdfplumber failed on sales results: %s", exc)
        return []

    results = []
    case_re = re.compile(r"^(\d{4}-\d{6})\s+(.*)", re.MULTILINE)
    dollar_re = re.compile(r"\$[\s\d,]+\.\d{2}")

    matches = list(case_re.finditer(full_text))
    for i, m in enumerate(matches):
        cn = m.group(1)
        rest = m.group(2)
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        block = full_text[m.start():end]

        # Dollar amounts — order: Written Bid | Deficiency | Total Due | Winning Bid
        raw_amounts = dollar_re.findall(block)
        amounts = [_parse_amount(a) for a in raw_amounts]

        if len(amounts) < 4:
            log.debug("Case %s: too few amounts (%d), skipping", cn, len(amounts))
            continue

        written_bid = amounts[0]
        deficiency = amounts[1]
        total_due = amounts[2]
        winning_bid = amounts[-1]
        overbid = round(max(0.0, winning_bid - total_due), 2)

        # Sale date = 2nd MM/DD/YYYY in block
        dates = re.findall(r"\d{2}/\d{2}/\d{4}", block)
        sale_date = _parse_date(dates[1]) if len(dates) >= 2 else _parse_date(dates[0] if dates else "")

        # Owner name: text before the first street number pattern in `rest`
        addr_start = re.search(r"\b\d{3,5}\s+[A-Z]", rest)
        if addr_start:
            owner_name = rest[: addr_start.start()].strip().rstrip(",")
        else:
            fn_m = re.search(r"\s+(CO-\d{2}-|\d{2}-\d{5,}|00\d{7,})", rest)
            owner_name = rest[: fn_m.start()].strip() if fn_m else rest[:40].strip()

        # Property address: find the line in block that ends with CO NNNNN
        addr_lines = [l.strip() for l in block.split("\n")
                      if re.search(r"CO\s+\d{5}", l, re.I)]
        property_address = addr_lines[0] if addr_lines else ""
        # Clean: strip attorney firm names (CO-NN-NNNNNN patterns, MCCARTHY, JANEWAY etc.)
        if property_address:
            # Truncate at attorney file number or firm name patterns
            property_address = re.sub(
                r"\s+(?:CO-\d{2}-|25-\d{5,}|00\d{7,}|MCCARTHY|JANEWAY|BARRETT|HOLTHUS|FRAPPIER).*$",
                "", property_address, flags=re.I,
            )
            property_address = property_address.strip()
        # Prepend the street portion from rest if address line is just "DENVER, CO NNNNN"
        if property_address and re.match(r"DENVER.*CO\s+\d{5}", property_address, re.I):
            if addr_start:
                street_raw = rest[addr_start.start():]
                # Grab up to the file number or first date
                fn_pos = re.search(r"\s+(?:CO-\d{2}-|\d{2}-\d{5,}|00\d{7,})", street_raw)
                date_pos = re.search(r"\s+\d{2}/\d{2}/\d{4}", street_raw)
                end = min(
                    fn_pos.start() if fn_pos else 999,
                    date_pos.start() if date_pos else 999,
                    80,
                )
                street = re.sub(r"\s+", " ", street_raw[:end]).strip().rstrip(",")
                property_address = street + ", " + property_address

        restriction = _restriction_status(sale_date)
        if overbid > 0:
            data_grade = "BRONZE"  # confirmed math, but restriction may apply
        else:
            data_grade = "REJECT"  # no surplus

        results.append({
            "case_number": cn,
            "owner_name": owner_name[:120],
            "property_address": property_address[:250],
            "sale_date": sale_date,
            "total_due": round(total_due, 2),
            "winning_bid": round(winning_bid, 2),
            "overbid": overbid,
            "restriction_status": restriction,
            "data_grade": data_grade,
            "source": "sales_results",
        })

    log.info("Parsed %d cases from sales results PDF (%d with overbid)",
             len(results), sum(1 for r in results if r["overbid"] > 0))
    return results


def parse_excess_funds(pdf_bytes: bytes) -> list[dict]:
    """
    Parse Denver Excess Funds list PDF.
    Returns list of case dicts with confirmed surplus held by the Public Trustee.
    These are the HIGHEST VALUE leads — money is already being held.
    """
    import pdfplumber

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    except Exception as exc:
        log.error("pdfplumber failed on excess funds: %s", exc)
        return []

    skip_keywords = [
        "Borrower", "Available Excess", "No one may", "Any excess",
        "If your name", "Homeowners can", "Great Colorado",
    ]

    results = []
    for line in full_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if any(kw in line for kw in skip_keywords):
            continue

        # Must end with a dollar amount (possibly with spaces)
        # Pattern at end: $[space][digits][space][digits].[digits] or $[digits,].[digits]
        amt_m = re.search(r"\$\s*([\d\s,]+\.\d{2})\s*$", line)
        if not amt_m:
            continue

        pending_amount = _parse_amount("$" + amt_m.group(1))
        if pending_amount <= 0:
            continue

        # Case number: YYYY-NNNNNN
        case_m = re.search(r"(\d{4}-\d{6})", line)
        case_number = case_m.group(1) if case_m else ""

        # Sale date: MM/DD/YY (2-digit year)
        date_m = re.search(r"\b(\d{2}/\d{2}/\d{2})\b", line)
        sale_date = _parse_date(date_m.group(1)) if date_m else None

        # State/zip: CO NNNNN
        state_m = re.search(r"\bCO\s+(\d{5})\b", line)
        zip_code = state_m.group(1) if state_m else ""

        # Address: everything between owner (start) and CO ZIP (+ case + amount at end)
        # Landmark: CO appears before zip and case number
        if state_m:
            before_state = line[: state_m.start()].strip()
            # Find first digit sequence ≥ 3 digits (street number) — that starts the address
            # But skip if the number is part of a company name (followed by LLC/INC/ECO etc.)
            addr_start_m = None
            for cand in re.finditer(r"\b(\d{3,5})\s+([A-Z])", before_state):
                # Check if the surrounding context looks like a company name (LLC, ECO etc after digits)
                following = before_state[cand.start():]
                if re.search(r"^\d+\s+[A-Z\s]+(?:LLC|INC|CORP|ECO|CO\.|LTD)\b", following, re.I):
                    continue  # Skip — this is a company name not a street address
                addr_start_m = cand
                break
            if addr_start_m:
                owner_name = before_state[: addr_start_m.start()].strip().rstrip(",")
                street_and_city = before_state[addr_start_m.start():].strip()
                # City detection: last 1-3 all-caps words before "CO" — typically "DENVER"
                # or "SOUTH DENVER", "AURORA", etc.
                city_m = re.search(
                    r"\b((?:SOUTH\s+)?DENVER|AURORA|WESTMINSTER|LITTLETON|THORNTON|ARVADA|LAKEWOOD|MONTBELLO)\b",
                    street_and_city,
                    re.I,
                )
                if city_m:
                    street = street_and_city[: city_m.start()].strip().rstrip(",")
                    city = city_m.group(1).strip()
                else:
                    # Fallback: last 1-2 words before CO are city
                    parts = street_and_city.rsplit(None, 3)
                    street = " ".join(parts[:-1]) if len(parts) > 1 else street_and_city
                    city = "Denver"
                property_address = f"{street}, {city}, CO {zip_code}".strip(", ")
            else:
                owner_name = before_state[:60]
                property_address = ""
        else:
            owner_name = line[:60]
            property_address = ""

        restriction = _restriction_status(sale_date)
        # Confirmed money + restriction expired = GOLD; confirmed + active = SILVER
        if restriction == "EXPIRED":
            data_grade = "GOLD"
        else:
            data_grade = "SILVER"

        results.append({
            "case_number": case_number,
            "owner_name": owner_name[:120],
            "property_address": property_address[:250],
            "sale_date": sale_date,
            "overbid": round(pending_amount, 2),
            "restriction_status": restriction,
            "data_grade": data_grade,
            "source": "excess_funds",
        })

    log.info("Parsed %d cases from excess funds PDF (%d GOLD, %d SILVER)",
             len(results),
             sum(1 for r in results if r["data_grade"] == "GOLD"),
             sum(1 for r in results if r["data_grade"] == "SILVER"))
    return results


# ── Database ingestion ────────────────────────────────────────────────────────

def _upsert_lead(conn: sqlite3.Connection, record: dict, now_ts: str) -> str:
    """Insert or update a Denver lead. Returns action: 'inserted' | 'upgraded' | 'skipped'."""
    lead_id = _lead_id(record["case_number"])
    existing = conn.execute(
        "SELECT id, data_grade FROM leads WHERE county=? AND case_number=?",
        [_COUNTY, record["case_number"]],
    ).fetchone()

    GRADE_RANK = {"GOLD": 4, "SILVER": 3, "BRONZE": 2, "REJECT": 1}
    new_rank = GRADE_RANK.get(record["data_grade"], 0)

    if existing:
        old_rank = GRADE_RANK.get(existing["data_grade"], 0)
        if new_rank <= old_rank:
            return "skipped"
        # Upgrade existing lead
        # Map restriction_status → statute_window_status (the actual DB column)
        statute_status = "EXPIRED" if record.get("restriction_status") == "EXPIRED" else "RESTRICTED"
        conn.execute(
            """UPDATE leads SET data_grade=?, overbid_amount=?, estimated_surplus=?,
               sale_date=?, owner_name=?, property_address=?, statute_window_status=?,
               ingestion_source=?, updated_at=?
               WHERE county=? AND case_number=?""",
            [
                record["data_grade"],
                record["overbid"],
                record["overbid"],
                record.get("sale_date"),
                record.get("owner_name", ""),
                record.get("property_address", ""),
                statute_status,
                "denver_pdf_scraper",
                now_ts,
                _COUNTY,
                record["case_number"],
            ],
        )
        return "upgraded"

    # Insert new lead
    # Map restriction_status → statute_window_status (the actual DB column)
    statute_status = "EXPIRED" if record.get("restriction_status") == "EXPIRED" else "RESTRICTED"
    conn.execute(
        """INSERT INTO leads
           (id, county, case_number, owner_name, property_address, sale_date,
            overbid_amount, estimated_surplus, data_grade, statute_window_status,
            ingestion_source, surplus_stream, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            lead_id,
            _COUNTY,
            record["case_number"],
            record.get("owner_name", ""),
            record.get("property_address", ""),
            record.get("sale_date"),
            record.get("overbid", 0.0),
            record.get("overbid", 0.0),
            record["data_grade"],
            statute_status,
            "denver_pdf_scraper",
            "FORECLOSURE_OVERBID",
            now_ts,
        ],
    )
    return "inserted"


def run_denver_scrape(db_path: str | None = None, dry_run: bool = False) -> dict:
    """
    Full Denver scrape: download PDFs, parse, upsert to DB.
    Returns summary dict: gold, silver, bronze, reject, inserted, upgraded, skipped, errors.
    """
    db_path = db_path or _db_path()
    now_ts = datetime.now(timezone.utc).isoformat()
    summary = {
        "gold": 0, "silver": 0, "bronze": 0, "reject": 0,
        "inserted": 0, "upgraded": 0, "skipped": 0, "errors": 0,
        "leads": [],
    }

    # 1. Download and parse sales results
    sales_bytes = _fetch_pdf(SALES_RESULTS_URL)
    sales_records: list[dict] = []
    if sales_bytes:
        sales_records = parse_sales_results(sales_bytes)
    else:
        log.warning("Could not download Denver sales results PDF")
        summary["errors"] += 1

    # 2. Download and parse excess funds
    excess_url = _probe_excess_funds_url()
    excess_bytes = _fetch_pdf(excess_url)
    excess_records: list[dict] = []
    if excess_bytes:
        excess_records = parse_excess_funds(excess_bytes)
    else:
        log.warning("Could not download Denver excess funds PDF (tried %s)", excess_url)
        summary["errors"] += 1

    # Merge: excess funds take priority over sales results for the same case
    all_records: dict[str, dict] = {}
    for r in sales_records:
        all_records[r["case_number"]] = r
    for r in excess_records:
        # Excess funds override sales results (higher confidence)
        all_records[r["case_number"]] = r

    if dry_run:
        for r in all_records.values():
            log.info("[DRY RUN] %s", r)
            g = r["data_grade"].lower()
            summary[g] = summary.get(g, 0) + 1
        return summary

    # 3. Upsert to DB
    conn = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
        for record in all_records.values():
            try:
                action = _upsert_lead(conn, record, now_ts)
                summary[action] = summary.get(action, 0) + 1
                g = record["data_grade"].lower()
                summary[g] = summary.get(g, 0) + 1
                if action in ("inserted", "upgraded") and record["data_grade"] in ("GOLD", "SILVER"):
                    summary["leads"].append({
                        "case_number": record["case_number"],
                        "grade": record["data_grade"],
                        "overbid": record["overbid"],
                        "owner": record.get("owner_name", ""),
                        "address": record.get("property_address", ""),
                        "sale_date": record.get("sale_date", ""),
                        "restriction": record.get("restriction_status", ""),
                        "source": record.get("source", ""),
                    })
            except Exception as exc:
                log.error("Upsert error for %s: %s", record.get("case_number"), exc)
                summary["errors"] += 1
        conn.execute("COMMIT")
    except Exception as exc:
        log.error("DB transaction failed: %s", exc)
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        summary["errors"] += 1
    finally:
        conn.close()

    log.info(
        "Denver scrape complete: GOLD=%d SILVER=%d BRONZE=%d REJECT=%d "
        "inserted=%d upgraded=%d skipped=%d errors=%d",
        summary["gold"], summary["silver"], summary["bronze"], summary["reject"],
        summary["inserted"], summary["upgraded"], summary["skipped"], summary["errors"],
    )
    return summary


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import json

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Denver County Public Trustee PDF Scraper")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, do not write to DB")
    parser.add_argument("--db", default=None, help="Override DB path")
    args = parser.parse_args()

    result = run_denver_scrape(db_path=args.db, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
