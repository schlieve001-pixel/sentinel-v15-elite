"""
VERIFUSE V2 — vertex_engine_enterprise.py (The Engine)

Extracts financial data from PDFs using Vertex AI (Gemini) and
upserts into the `leads` table.

Canonical source of truth: VERIFUSE_DB_PATH env var.

Flow:
  1. Recursive walk of verifuse_v2/data/raw_pdfs
  2. Extract case_number from filename or PDF content
  3. Call gemini-2.0-flash for: winning_bid, total_debt, surplus_amount
  4. UPSERT: UPDATE if case_number exists, INSERT if new
  5. Log success/failure to stdout

Usage:
    export VERIFUSE_DB_PATH=/path/to/verifuse_v2.db
    export GOOGLE_APPLICATION_CREDENTIALS=/path/to/creds.json
    python -m verifuse_v2.scrapers.vertex_engine_enterprise
    python -m verifuse_v2.scrapers.vertex_engine_enterprise --dry-run
    python -m verifuse_v2.scrapers.vertex_engine_enterprise --limit 10
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# ── Fail-fast: require VERIFUSE_DB_PATH ─────────────────────────────

DB_PATH = os.environ.get("VERIFUSE_DB_PATH")
if not DB_PATH:
    print("FATAL: VERIFUSE_DB_PATH environment variable is not set.")
    sys.exit(1)

# ── Constants ────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent
PDF_DIR = BASE_DIR / "data" / "raw_pdfs"
MAX_PDF_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_RETRIES = 5
CONFIDENCE_GATE = 0.6

# Gemini response schema
EXTRACTION_SCHEMA = {
    "type": "object",
    "required": ["winning_bid", "total_debt", "surplus_amount",
                  "case_numbers", "sale_date", "property_addresses",
                  "owner_names", "is_illegible"],
    "properties": {
        "winning_bid": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "total_debt": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "surplus_amount": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "case_numbers": {
            "type": "array",
            "items": {"type": "string"},
        },
        "sale_date": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "property_addresses": {
            "type": "array",
            "items": {"type": "string"},
        },
        "owner_names": {
            "type": "array",
            "items": {"type": "string"},
        },
        "is_illegible": {"type": "boolean"},
    },
}

# Prompt for Gemini
EXTRACTION_PROMPT = """You are a forensic financial analyst specializing in Colorado foreclosure surplus documents.

Extract ALL of the following from this document:
- winning_bid: The winning bid, sale price, or highest bid amount (string with $)
- total_debt: The total debt, indebtedness, total liens, or amount owed (string with $)
- surplus_amount: The surplus, overbid, excess funds, or overage amount (string with $)
- case_numbers: ALL case/reception numbers found (array of strings like "2024CV30123" or "0602-2022")
- sale_date: The foreclosure sale date (string)
- property_addresses: ALL property addresses found (array of strings)
- owner_names: ALL owner/borrower/grantor names found (array of strings)
- is_illegible: true ONLY if the document is completely unreadable

This may be a multi-page document listing MULTIPLE properties. Extract data for each one.
If a value is not found, use null. Return ONLY the JSON."""


# ── Database ─────────────────────────────────────────────────────────

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ── Parsers ──────────────────────────────────────────────────────────

def parse_money(raw: Optional[str]) -> Optional[float]:
    """OCR-aware money parser."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    s = s.replace("O", "0").replace("o", "0")
    s = s.replace("$", "").replace(",", "").strip()
    s = re.sub(r"(\d)\s+(\d)", r"\1\2", s)
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        m = re.search(r"[\d.]+", s)
        if m:
            try:
                return float(m.group(0))
            except ValueError:
                pass
        return None


def parse_date(raw: Optional[str]) -> Optional[str]:
    """Parse date strings into ISO format."""
    if raw is None:
        return None
    s = str(raw).strip()
    iso_re = re.compile(r"\b(20\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b")
    m = iso_re.search(s)
    if m:
        return m.group(0)
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def extract_case_from_filename(filename: str) -> Optional[str]:
    """Try to extract case number from PDF filename."""
    patterns = [
        r"(\d{4}[A-Z]{2}\d+)",           # 2024CV30123
        r"(\d{4}-\d{4})",                 # 0602-2022
        r"D-(\d{4}[A-Z]{2}\d+)",          # D-2024CV30123
        r"case[_-]?(\d+)",                # case_12345
    ]
    for pat in patterns:
        m = re.search(pat, filename, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def make_lead_id(county: str, case_number: str, pdf_name: str) -> str:
    """Generate a deterministic lead ID."""
    key = f"{county}_{case_number}_{pdf_name}"
    h = hashlib.sha256(key.encode()).hexdigest()[:12]
    return f"{county.lower()}_vertex_{h}"


# ── PDF Validation ───────────────────────────────────────────────────

def validate_pdf(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "File not found"
    if path.stat().st_size > MAX_PDF_SIZE:
        return False, "Too large"
    if path.stat().st_size < 100:
        return False, "Too small"
    header = path.read_bytes()[:5]
    if header != b"%PDF-":
        return False, "Not a PDF"
    return True, "OK"


# ── Vertex AI Extraction ────────────────────────────────────────────

def extract_from_pdf(client, model: str, pdf_path: Path) -> dict:
    """Call Vertex AI to extract financial data from a PDF."""
    from google.genai import types

    pdf_bytes = pdf_path.read_bytes()
    pdf_part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")

    for attempt in range(MAX_RETRIES):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=[EXTRACTION_PROMPT, pdf_part],
                config={
                    "response_mime_type": "application/json",
                    "response_schema": EXTRACTION_SCHEMA,
                },
            )

            parsed = resp.parsed
            if not parsed:
                return {"ok": False, "error": "empty_response", "data": None}

            if parsed.get("is_illegible"):
                return {"ok": False, "error": "illegible", "data": None}

            return {"ok": True, "error": None, "data": parsed}

        except Exception as e:
            err_str = str(e)
            if any(code in err_str for code in ["429", "503", "500", "RESOURCE_EXHAUSTED"]):
                wait = (2 ** attempt) + random.uniform(0, 1)
                print(f"    Retry {attempt + 1}/{MAX_RETRIES} ({wait:.1f}s): {err_str[:80]}")
                time.sleep(wait)
                continue
            return {"ok": False, "error": err_str[:200], "data": None}

    return {"ok": False, "error": "max_retries_exceeded", "data": None}


# ── Upsert Logic ────────────────────────────────────────────────────

def upsert_lead(conn: sqlite3.Connection, lead: dict) -> str:
    """Check if case_number exists in leads. UPDATE if yes, INSERT if no.

    Returns 'updated', 'inserted', or 'skipped'.
    """
    case_number = lead.get("case_number")
    lead_id = lead.get("id")
    now = datetime.now(timezone.utc).isoformat()

    # Check by case_number first
    existing = None
    if case_number:
        existing = conn.execute(
            "SELECT id FROM leads WHERE case_number = ?", [case_number]
        ).fetchone()

    if existing:
        # UPDATE: enrich existing row
        conn.execute("""
            UPDATE leads SET
                winning_bid     = COALESCE(NULLIF(?, 0.0), winning_bid),
                total_debt      = COALESCE(NULLIF(?, 0.0), total_debt),
                surplus_amount  = COALESCE(NULLIF(?, 0.0), surplus_amount),
                overbid_amount  = COALESCE(NULLIF(?, 0.0), overbid_amount),
                confidence_score = COALESCE(NULLIF(?, 0.0), confidence_score),
                sale_date       = COALESCE(?, sale_date),
                claim_deadline  = COALESCE(?, claim_deadline),
                data_grade      = COALESCE(?, data_grade),
                source_name     = COALESCE(?, source_name),
                vertex_processed = 1,
                status          = 'ENRICHED',
                updated_at      = ?
            WHERE case_number = ?
        """, [
            lead.get("winning_bid", 0.0),
            lead.get("total_debt", 0.0),
            lead.get("surplus_amount", 0.0),
            lead.get("overbid_amount", 0.0),
            lead.get("confidence_score", 0.0),
            lead.get("sale_date"),
            lead.get("claim_deadline"),
            lead.get("data_grade"),
            lead.get("source_name"),
            now,
            case_number,
        ])
        return "updated"

    else:
        # INSERT: new lead
        conn.execute("""
            INSERT OR IGNORE INTO leads
                (id, case_number, county, owner_name, property_address,
                 estimated_surplus, winning_bid, total_debt, surplus_amount,
                 overbid_amount, confidence_score, sale_date, claim_deadline,
                 data_grade, source_name, vertex_processed, status, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,'NEW',?)
        """, [
            lead_id,
            case_number,
            lead.get("county", "Unknown"),
            lead.get("owner_name"),
            lead.get("property_address"),
            lead.get("surplus_amount", 0.0),
            lead.get("winning_bid", 0.0),
            lead.get("total_debt", 0.0),
            lead.get("surplus_amount", 0.0),
            lead.get("overbid_amount", 0.0),
            lead.get("confidence_score", 0.0),
            lead.get("sale_date"),
            lead.get("claim_deadline"),
            lead.get("data_grade", "BRONZE"),
            lead.get("source_name"),
            now,
        ])
        return "inserted"


# ── Confidence Scoring ──────────────────────────────────────────────

def compute_confidence(bid: float, debt: float, sale_date: str,
                       address: str, owner: str) -> float:
    """Score 0.0–1.0 based on data completeness."""
    score = 0.0
    if bid and bid > 0:
        score += 0.25
    if debt and debt > 0:
        score += 0.25
    if sale_date:
        score += 0.15
    if address and len(address) > 5:
        score += 0.2
    if owner and len(owner) > 2:
        score += 0.15
    return min(score, 1.0)


def compute_grade(surplus: float, confidence: float) -> str:
    if surplus >= 10000 and confidence >= 0.8:
        return "GOLD"
    if surplus >= 5000 and confidence >= 0.6:
        return "SILVER"
    if surplus > 0:
        return "BRONZE"
    return "IRON"


# ── Main Processing ─────────────────────────────────────────────────

def scan_pdfs() -> list[tuple[Path, str]]:
    """Recursive walk of raw_pdfs directory. Returns (path, county) pairs."""
    results = []
    if not PDF_DIR.exists():
        print(f"  [WARN] PDF directory not found: {PDF_DIR}")
        return results

    # Top-level PDFs → county from filename
    for pdf in PDF_DIR.glob("*.pdf"):
        # Guess county from filename
        name = pdf.stem.lower()
        if "denver" in name:
            county = "Denver"
        elif "adams" in name:
            county = "Adams"
        elif "elpaso" in name or "el_paso" in name:
            county = "El Paso"
        elif "jefferson" in name:
            county = "Jefferson"
        elif "arapahoe" in name:
            county = "Arapahoe"
        else:
            county = "Unknown"
        results.append((pdf, county))

    # Subdirectory PDFs → county from directory name
    for subdir in PDF_DIR.iterdir():
        if subdir.is_dir():
            county = subdir.name.replace("_", " ").title()
            for pdf in subdir.glob("*.pdf"):
                results.append((pdf, county))

    return results


def process_all(limit: int = 100, dry_run: bool = False,
                model: str = "gemini-2.0-flash") -> dict:
    """Main processing loop."""
    stats = {
        "pdfs_found": 0, "processed": 0, "updated": 0,
        "inserted": 0, "failed": 0, "skipped": 0, "errors": [],
    }

    pdfs = scan_pdfs()
    stats["pdfs_found"] = len(pdfs)
    print(f"\n  Found {len(pdfs)} PDFs in {PDF_DIR}")

    if not pdfs:
        return stats

    # Init Vertex AI client
    client = None
    if not dry_run:
        cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
        if not cred_path or not Path(cred_path).exists():
            stats["errors"].append("GOOGLE_APPLICATION_CREDENTIALS not set or file missing")
            print(f"  [ERROR] {stats['errors'][-1]}")
            return stats

        try:
            from google import genai
            cred_data = json.loads(Path(cred_path).read_text())
            project = cred_data.get("project_id")
            client = genai.Client(vertexai=True, project=project, location="us-central1")
            print(f"  Vertex AI client: project={project}, model={model}")
        except Exception as e:
            stats["errors"].append(f"Vertex AI init failed: {e}")
            print(f"  [ERROR] {stats['errors'][-1]}")
            return stats

    conn = get_connection()
    try:
        for i, (pdf_path, county) in enumerate(pdfs[:limit]):
            valid, msg = validate_pdf(pdf_path)
            if not valid:
                print(f"  [{i+1}/{min(limit, len(pdfs))}] SKIP {pdf_path.name}: {msg}")
                stats["skipped"] += 1
                continue

            print(f"  [{i+1}/{min(limit, len(pdfs))}] {county}: {pdf_path.name} ({pdf_path.stat().st_size/1024:.0f}KB)")

            if dry_run:
                print(f"    DRY RUN — would process")
                stats["processed"] += 1
                continue

            # Extract via Vertex AI
            result = extract_from_pdf(client, model, pdf_path)
            stats["processed"] += 1

            if not result["ok"]:
                print(f"    FAILED: {result['error']}")
                stats["failed"] += 1
                continue

            data = result["data"]
            bid = parse_money(data.get("winning_bid")) or 0.0
            debt = parse_money(data.get("total_debt")) or 0.0
            surplus = parse_money(data.get("surplus_amount")) or max(0.0, bid - debt)
            sale_date = parse_date(data.get("sale_date"))
            case_numbers = data.get("case_numbers", [])
            addresses = data.get("property_addresses", [])
            owners = data.get("owner_names", [])

            # Use filename-derived case number as fallback
            if not case_numbers:
                fn_case = extract_case_from_filename(pdf_path.stem)
                if fn_case:
                    case_numbers = [fn_case]

            # If no case numbers found, use PDF hash as identifier
            if not case_numbers:
                pdf_hash = hashlib.md5(pdf_path.read_bytes()[:4096]).hexdigest()[:8]
                case_numbers = [f"PDF-{pdf_hash}"]

            # Process each case found in the document
            for idx, case_num in enumerate(case_numbers):
                address = addresses[idx] if idx < len(addresses) else (addresses[0] if addresses else None)
                owner = owners[idx] if idx < len(owners) else (owners[0] if owners else None)

                confidence = compute_confidence(bid, debt, sale_date, address or "", owner or "")
                overbid = max(0.0, bid - debt) if bid > 0 and debt > 0 else 0.0

                # Claim deadline: 180 days from sale
                claim_deadline = None
                if sale_date:
                    try:
                        dt = datetime.fromisoformat(sale_date)
                        claim_deadline = (dt + timedelta(days=180)).strftime("%Y-%m-%d")
                    except ValueError:
                        pass

                grade = compute_grade(surplus, confidence)
                lead_id = make_lead_id(county, case_num, pdf_path.name)

                lead = {
                    "id": lead_id,
                    "case_number": case_num,
                    "county": county,
                    "owner_name": owner,
                    "property_address": address,
                    "winning_bid": bid,
                    "total_debt": debt,
                    "surplus_amount": surplus,
                    "overbid_amount": overbid,
                    "confidence_score": confidence,
                    "sale_date": sale_date,
                    "claim_deadline": claim_deadline,
                    "data_grade": grade,
                    "source_name": f"vertex_enterprise_{pdf_path.name}",
                }

                action = upsert_lead(conn, lead)
                if action == "updated":
                    stats["updated"] += 1
                    print(f"    UPDATE case={case_num} bid=${bid:,.2f} debt=${debt:,.2f} surplus=${surplus:,.2f}")
                elif action == "inserted":
                    stats["inserted"] += 1
                    print(f"    INSERT case={case_num} bid=${bid:,.2f} debt=${debt:,.2f} surplus=${surplus:,.2f}")

            # Rate limiting courtesy
            time.sleep(1.0)

        conn.commit()

    except Exception as e:
        conn.rollback()
        stats["errors"].append(str(e))
        print(f"  [FATAL] {e}")
    finally:
        conn.close()

    return stats


# ── CLI ──────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Engine Enterprise — Vertex AI PDF Extraction → leads table"
    )
    ap.add_argument("--limit", type=int, default=100, help="Max PDFs to process")
    ap.add_argument("--dry-run", action="store_true", help="Scan PDFs without calling Vertex AI")
    ap.add_argument("--model", default="gemini-2.0-flash", help="Gemini model to use")
    args = ap.parse_args()

    print("\n" + "=" * 60)
    print("  VERIFUSE ENGINE ENTERPRISE — Vertex AI → leads")
    print("=" * 60)
    print(f"  DB: {DB_PATH}")
    print(f"  PDFs: {PDF_DIR}")
    print(f"  Model: {args.model}")
    print(f"  Limit: {args.limit}")
    print(f"  Dry run: {args.dry_run}")
    print("=" * 60)

    stats = process_all(limit=args.limit, dry_run=args.dry_run, model=args.model)

    print(f"\n{'='*60}")
    print("  RESULTS")
    print(f"{'='*60}")
    for k, v in stats.items():
        if k != "errors":
            print(f"  {k:15s}: {v}")
    if stats["errors"]:
        print(f"  ERRORS: {stats['errors']}")
    print(f"{'='*60}\n")

    if stats["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
