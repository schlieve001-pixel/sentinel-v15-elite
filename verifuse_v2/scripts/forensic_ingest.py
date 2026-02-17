#!/usr/bin/env python3
"""
forensic_ingest.py — Standalone PDF forensic ingestion engine.

Recursively scans directories for PDFs, extracts case/owner/surplus data
via regex, and upserts into the leads table. Fully idempotent via SHA256
deduplication in the ingestion_events table.

CONSTRAINT: Must be STANDALONE. Do not import verifuse.core.
Uses standard libraries (sqlite3, re, pathlib, hashlib) only.
"""

import argparse
import hashlib
import os
import re
import sqlite3
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path


# ─── Configuration ──────────────────────────────────────────────────────────

PATTERNS = {
    "case_number": [
        re.compile(r"(?:Case|File|Foreclosure|Reception)\s*(?:#|No\.?|Number)?[:\s]*([0-9]{2,4}[-/]?[A-Z]{0,4}[-/]?\d{3,10})", re.IGNORECASE),
        re.compile(r"\b(\d{4}[A-Z]{2}\d{4,8})\b"),
        re.compile(r"\b(\d{2}-\d{4}-[A-Z]+-\d{4,8})\b"),
        re.compile(r"(?:Case|File)\s*#?\s*:?\s*([A-Z0-9][-A-Z0-9]{5,20})", re.IGNORECASE),
    ],
    "owner": [
        re.compile(r"(?:Owner|Grantor|Borrower|Claimant|Defendant)\s*:?\s*(.+?)(?:\n|$)", re.IGNORECASE),
        re.compile(r"(?:Property\s+of|In\s+(?:the\s+)?(?:matter|name)\s+of)\s*:?\s*(.+?)(?:\n|$)", re.IGNORECASE),
    ],
    "surplus": [
        re.compile(r"(?:Surplus|Excess|Overbid|Over\s*bid|Unclaimed)\s*(?:Funds?|Amount)?\s*:?\s*\$?\s*([\d,]+\.\d{2})", re.IGNORECASE),
        re.compile(r"\$\s*([\d,]+\.\d{2})\s*(?:surplus|excess|overbid)", re.IGNORECASE),
        re.compile(r"(?:Amount|Balance|Funds?)\s*:?\s*\$\s*([\d,]+\.\d{2})", re.IGNORECASE),
    ],
    "sale_date": [
        re.compile(r"(?:Sale|Sold|Auction|Foreclosure)\s*Date\s*:?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", re.IGNORECASE),
        re.compile(r"(?:Sale|Sold|Auction)\s*Date\s*:?\s*(\w+\s+\d{1,2},?\s*\d{4})", re.IGNORECASE),
    ],
    "address": [
        re.compile(r"(?:Property\s+)?Address\s*:?\s*(.+?)(?:\n|$)", re.IGNORECASE),
        re.compile(r"(\d+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:St|Ave|Blvd|Dr|Rd|Ln|Way|Ct|Cir|Pl)\.?(?:\s*#?\s*\d+)?)", re.IGNORECASE),
    ],
    "county": [
        re.compile(r"(?:County\s*(?:of)?|(?:In|For)\s+(?:the\s+)?County\s+of)\s*:?\s*(\w+(?:\s+\w+)?)", re.IGNORECASE),
        re.compile(r"(Adams|Arapahoe|Boulder|Denver|Douglas|Eagle|El\s*Paso|Jefferson|Larimer|Mesa|Pueblo|San\s*Miguel|Summit|Teller|Weld)\s+County", re.IGNORECASE),
    ],
}


def sha256_file(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def extract_text_from_pdf(filepath: Path) -> str:
    # Try pdftotext first
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(filepath), "-"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and len(result.stdout.strip()) > 50:
            return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Try pdfplumber
    try:
        result = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(f"""\
                import pdfplumber
                with pdfplumber.open("{filepath}") as pdf:
                    for page in pdf.pages:
                        text = page.extract_text()
                        if text:
                            print(text)
            """)],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0 and len(result.stdout.strip()) > 50:
            return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback: raw ASCII extraction
    try:
        with open(filepath, "rb") as f:
            raw = f.read(500_000)
        strings = re.findall(rb"[\x20-\x7E]{4,}", raw)
        return "\n".join(s.decode("ascii", errors="ignore") for s in strings)
    except Exception:
        return ""


def extract_fields(text: str) -> dict:
    result = {}
    for field, patterns in PATTERNS.items():
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                value = match.group(1).strip()
                value = re.sub(r"\s+", " ", value)
                if field == "surplus":
                    value = value.replace(",", "")
                    try:
                        value = float(value)
                    except ValueError:
                        continue
                    if value <= 0:
                        continue
                result[field] = value
                break
    return result


def normalize_date(date_str: str) -> str:
    if not date_str:
        return ""
    date_str = date_str.strip()
    if re.match(r"\d{4}-\d{2}-\d{2}", date_str):
        return date_str[:10]
    m = re.match(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", date_str)
    if m:
        month, day, year = m.groups()
        if len(year) == 2:
            year = "20" + year if int(year) < 50 else "19" + year
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    m = re.match(r"(\w+)\s+(\d{1,2}),?\s*(\d{4})", date_str)
    if m:
        months = {
            "january": 1, "february": 2, "march": 3, "april": 4,
            "may": 5, "june": 6, "july": 7, "august": 8,
            "september": 9, "october": 10, "november": 11, "december": 12,
            "jan": 1, "feb": 2, "mar": 3, "apr": 4,
            "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        }
        month_name, day, year = m.groups()
        month_num = months.get(month_name.lower(), 0)
        if month_num:
            return f"{int(year):04d}-{month_num:02d}-{int(day):02d}"
    m = re.match(r"(\w{3})-(\d{2})", date_str)
    if m:
        months_short = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        }
        mon, yy = m.groups()
        month_num = months_short.get(mon.lower(), 0)
        if month_num:
            return f"{2000 + int(yy):04d}-{month_num:02d}-01"
    return date_str


def generate_lead_id(case_number: str, county: str, filename: str) -> str:
    seed = f"{case_number or ''}|{county or ''}|{filename}"
    return hashlib.sha256(seed.encode()).hexdigest()[:16]


def detect_county_from_path(filepath: Path) -> str:
    path_str = str(filepath).lower()
    counties = {
        "adams": "Adams", "arapahoe": "Arapahoe", "boulder": "Boulder",
        "denver": "Denver", "douglas": "Douglas", "eagle": "Eagle",
        "elpaso": "El Paso", "el_paso": "El Paso", "el paso": "El Paso",
        "jefferson": "Jefferson", "jeffco": "Jefferson",
        "larimer": "Larimer", "mesa": "Mesa", "pueblo": "Pueblo",
        "sanmiguel": "San Miguel", "san_miguel": "San Miguel",
        "summit": "Summit", "teller": "Teller", "weld": "Weld",
    }
    for key, name in counties.items():
        if key in path_str:
            return name
    return ""


def process_pdf(filepath: Path, conn: sqlite3.Connection, stats: dict):
    file_hash = sha256_file(filepath)

    existing = conn.execute(
        "SELECT id, status FROM ingestion_events WHERE sha256 = ?",
        [file_hash]
    ).fetchone()
    if existing:
        stats["skipped"] += 1
        return

    rel_path = str(filepath)

    try:
        text = extract_text_from_pdf(filepath)
        if len(text.strip()) < 20:
            conn.execute(
                "INSERT INTO ingestion_events (filename, status, sha256, records_found, error_message) VALUES (?, ?, ?, ?, ?)",
                [rel_path, "ERROR", file_hash, 0, "No extractable text"]
            )
            conn.commit()
            stats["errors"] += 1
            return

        fields = extract_fields(text)

        if "county" not in fields:
            county_from_path = detect_county_from_path(filepath)
            if county_from_path:
                fields["county"] = county_from_path

        case_number = fields.get("case_number", "")
        owner = fields.get("owner", "")
        surplus = fields.get("surplus", 0.0)
        sale_date = normalize_date(fields.get("sale_date", ""))
        address = fields.get("address", "")
        county = fields.get("county", "Unknown")

        if not case_number and not owner:
            conn.execute(
                "INSERT INTO ingestion_events (filename, status, sha256, records_found, error_message) VALUES (?, ?, ?, ?, ?)",
                [rel_path, "ERROR", file_hash, 0, "No case number or owner found"]
            )
            conn.commit()
            stats["errors"] += 1
            return

        lead_id = generate_lead_id(case_number, county, filepath.name)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        surplus_float = float(surplus) if surplus else 0.0

        conn.execute("""
            INSERT OR IGNORE INTO leads (
                id, case_number, county, owner_name, property_address,
                surplus_amount, estimated_surplus, sale_date, data_grade,
                source_name, status, confidence_score, updated_at,
                ingestion_source, processing_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            lead_id,
            case_number or None,
            county,
            owner or None,
            address or None,
            surplus_float if surplus_float > 0 else None,
            surplus_float if surplus_float > 0 else None,
            sale_date or None,
            "BRONZE",
            f"forensic_ingest:{filepath.name}",
            "STAGED",
            0.5,
            now,
            f"forensic_ingest:{filepath.name}",
            "STAGED",
        ])

        # Upgrade empty fields on existing records (never downgrade)
        if case_number:
            conn.execute("""
                UPDATE leads SET
                    owner_name = COALESCE(owner_name, ?),
                    property_address = COALESCE(property_address, ?),
                    surplus_amount = CASE
                        WHEN COALESCE(surplus_amount, 0) = 0 AND ? > 0 THEN ?
                        ELSE surplus_amount
                    END,
                    estimated_surplus = CASE
                        WHEN COALESCE(estimated_surplus, 0) = 0 AND ? > 0 THEN ?
                        ELSE estimated_surplus
                    END,
                    sale_date = COALESCE(sale_date, ?),
                    updated_at = ?
                WHERE case_number = ? AND county = ? AND id != ?
            """, [
                owner or None,
                address or None,
                surplus_float, surplus_float,
                surplus_float, surplus_float,
                sale_date or None,
                now,
                case_number, county, lead_id,
            ])

        stats["processed"] += 1
        if surplus_float > 0:
            stats["surplus_total"] += surplus_float

        conn.execute(
            "INSERT INTO ingestion_events (filename, status, sha256, records_found) VALUES (?, ?, ?, ?)",
            [rel_path, "PROCESSED", file_hash, 1]
        )
        conn.commit()

    except Exception as e:
        error_msg = str(e)[:500]
        stats["errors"] += 1
        try:
            conn.execute(
                "INSERT OR IGNORE INTO ingestion_events (filename, status, sha256, records_found, error_message) VALUES (?, ?, ?, ?, ?)",
                [rel_path, "ERROR", file_hash, 0, error_msg]
            )
            conn.commit()
        except Exception:
            pass


def find_pdfs(scan_dirs: list, base_dir: Path) -> list:
    pdfs = []
    for d in scan_dirs:
        search_path = base_dir / d
        if not search_path.exists():
            continue
        for root, dirs, files in os.walk(search_path):
            dirs[:] = [x for x in dirs if not x.startswith(".") and x not in ("node_modules", ".venv", "venv", "__pycache__")]
            for f in files:
                if f.lower().endswith(".pdf"):
                    pdfs.append(Path(root) / f)
    return sorted(pdfs)


def main():
    parser = argparse.ArgumentParser(description="Forensic PDF ingestion engine")
    parser.add_argument("--db", required=True, help="Path to verifuse_v2.db")
    parser.add_argument("--scan-dirs", required=True, help="Comma-separated directories to scan (relative to repo root)")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"FATAL: Database not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    base_dir = db_path.resolve().parent.parent.parent
    scan_dirs = [d.strip() for d in args.scan_dirs.split(",")]

    print(f"  Database:   {db_path}")
    print(f"  Base dir:   {base_dir}")
    print(f"  Scan dirs:  {scan_dirs}")

    pdfs = find_pdfs(scan_dirs, base_dir)
    print(f"  PDFs found: {len(pdfs)}")

    if not pdfs:
        print("  No PDFs to process. Done.")
        return

    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 10000")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS ingestion_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            filename        TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'PENDING',
            sha256          TEXT UNIQUE NOT NULL,
            records_found   INTEGER DEFAULT 0,
            error_message   TEXT,
            timestamp       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
    """)
    conn.commit()

    stats = {"processed": 0, "skipped": 0, "errors": 0, "surplus_total": 0.0}

    for i, pdf in enumerate(pdfs, 1):
        if i % 10 == 0 or i == len(pdfs):
            print(f"  Processing {i}/{len(pdfs)}: {pdf.name}")
        process_pdf(pdf, conn, stats)

    conn.close()

    print("")
    print("  ── FORENSIC INGEST RESULTS ──")
    print(f"  Processed:     {stats['processed']}")
    print(f"  Skipped (dup): {stats['skipped']}")
    print(f"  Errors:        {stats['errors']}")
    print(f"  New surplus:   ${stats['surplus_total']:,.2f}")
    print(f"  Total scanned: {len(pdfs)}")


if __name__ == "__main__":
    main()
