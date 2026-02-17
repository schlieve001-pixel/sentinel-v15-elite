"""
VERIFUSE V2 — Engine V2: The Instrumentalist

Deterministic PDF enrichment using the Titanium Parser Registry.
No AI required — pure regex extraction with confidence scoring.

Flow:
  1. Scan raw_pdfs/ recursively for all PDFs
  2. Extract text via pdfplumber
  3. Iterate registered parsers: if detect() → extract()
  4. For each record, compute confidence_score via score()
  5. Threshold routing:
     - score > 0.8  → UPDATE leads SET status='ENRICHED'
     - 0.5 < score ≤ 0.8 → UPDATE leads SET status='REVIEW_REQUIRED'
     - score ≤ 0.5  → Log as ANOMALY, skip DB write

Canonical source of truth: VERIFUSE_DB_PATH env var.

Usage:
    export VERIFUSE_DB_PATH=/path/to/verifuse_v2.db
    python -m verifuse_v2.scrapers.engine_v2
    python -m verifuse_v2.scrapers.engine_v2 --dry-run
    python -m verifuse_v2.scrapers.engine_v2 --verbose
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber

from verifuse_v2.scrapers.registry import (
    PARSER_REGISTRY,
    CountyParser,
    get_parser_for,
)

# ── Fail-fast ────────────────────────────────────────────────────────

DB_PATH = os.environ.get("VERIFUSE_DB_PATH")
if not DB_PATH:
    print("FATAL: VERIFUSE_DB_PATH not set.")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
PDF_DIR = BASE_DIR / "data" / "raw_pdfs"
LOG_DIR = BASE_DIR / "logs"
ANOMALY_LOG = LOG_DIR / "engine_v2_anomalies.jsonl"

# ── Thresholds ───────────────────────────────────────────────────────

ENRICHED_THRESHOLD = 0.8
REVIEW_THRESHOLD = 0.5


# ── Database ─────────────────────────────────────────────────────────

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ── Anomaly Logging ──────────────────────────────────────────────────

def log_anomaly(record: dict, confidence: float, reason: str, source: str) -> None:
    """Append anomaly to JSONL log."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "engine": "engine_v2",
        "confidence": confidence,
        "reason": reason,
        "source_file": source,
        "case_number": record.get("case_number"),
        "county": record.get("county"),
        "winning_bid": record.get("winning_bid"),
        "total_debt": record.get("total_debt"),
        "surplus_amount": record.get("surplus_amount"),
    }
    with open(ANOMALY_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ── Upsert Logic ────────────────────────────────────────────────────

def upsert_to_leads(conn: sqlite3.Connection, record: dict,
                    confidence: float, grade: str, status: str) -> str:
    """Upsert a parsed record into the leads table.

    Strategy:
      - If case_number exists → UPDATE (enrich)
      - If case_number doesn't exist → INSERT (new lead)

    Returns: 'updated', 'inserted', or 'skipped'
    """
    case_number = record.get("case_number", "")
    now = datetime.now(timezone.utc).isoformat()

    # Check by case_number
    existing = None
    if case_number:
        existing = conn.execute(
            "SELECT id FROM leads WHERE case_number = ?", [case_number]
        ).fetchone()

    if existing:
        # UPDATE: enrich existing row (only overwrite non-null values)
        conn.execute("""
            UPDATE leads SET
                winning_bid      = CASE WHEN ? > 0 THEN ? ELSE winning_bid END,
                total_debt       = CASE WHEN ? > 0 THEN ? ELSE total_debt END,
                surplus_amount   = CASE WHEN ? > 0 THEN ? ELSE surplus_amount END,
                overbid_amount   = CASE WHEN ? > 0 THEN ? ELSE overbid_amount END,
                confidence_score = CASE WHEN ? > COALESCE(confidence_score, 0) THEN ? ELSE confidence_score END,
                sale_date        = COALESCE(?, sale_date),
                claim_deadline   = COALESCE(?, claim_deadline),
                data_grade       = CASE WHEN ? IN ('GOLD','SILVER') THEN ? ELSE data_grade END,
                source_name      = COALESCE(?, source_name),
                vertex_processed = 0,
                status           = ?,
                updated_at       = ?
            WHERE case_number = ?
        """, [
            record.get("winning_bid", 0), record.get("winning_bid", 0),
            record.get("total_debt", 0), record.get("total_debt", 0),
            record.get("surplus_amount", 0), record.get("surplus_amount", 0),
            record.get("overbid_amount", 0), record.get("overbid_amount", 0),
            confidence, confidence,
            record.get("sale_date"),
            record.get("claim_deadline"),
            grade, grade,
            record.get("source_name"),
            status,
            now,
            case_number,
        ])
        return "updated"
    else:
        # INSERT new lead
        parser = record.get("_parser")
        lead_id = record.get("lead_id", f"v2_{case_number}")

        conn.execute("""
            INSERT OR IGNORE INTO leads
            (id, case_number, county, owner_name, property_address,
             estimated_surplus, winning_bid, total_debt, surplus_amount,
             overbid_amount, confidence_score, sale_date, claim_deadline,
             data_grade, source_name, vertex_processed, status, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)
        """, [
            lead_id,
            case_number,
            record.get("county", "Unknown"),
            record.get("owner_name"),
            record.get("property_address"),
            record.get("surplus_amount", 0),
            record.get("winning_bid", 0),
            record.get("total_debt", 0),
            record.get("surplus_amount", 0),
            record.get("overbid_amount", 0),
            confidence,
            record.get("sale_date"),
            record.get("claim_deadline"),
            grade,
            record.get("source_name"),
            status,
            now,
        ])
        return "inserted"


# ── Core Engine ──────────────────────────────────────────────────────

def extract_text(pdf_path: Path) -> str:
    """Extract all text from a PDF using pdfplumber."""
    text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        log.warning("PDF read error %s: %s", pdf_path.name, e)
    return text


def _vertex_fallback_enabled() -> bool:
    """Check if Vertex AI fallback is available."""
    return bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))


def _vertex_fallback(pdf_path: Path, source_file: str) -> list[dict]:
    """Send unmatched PDF to Vertex AI for extraction. Returns list of records."""
    try:
        from verifuse_v2.scrapers.vertex_engine import extract_from_pdf, validate_pdf, _sha256_file
        import hashlib

        valid, msg = validate_pdf(pdf_path)
        if not valid:
            log.debug("Vertex fallback skip %s: %s", pdf_path.name, msg)
            return []

        # Budget check via vertex_usage table
        from verifuse_v2.scrapers.vertex_engine import _get_daily_usage, _log_vertex_usage, DAILY_PDF_CAP
        conn_check = sqlite3.connect(DB_PATH)
        conn_check.execute("PRAGMA journal_mode=WAL")
        daily_used = _get_daily_usage(conn_check)
        if daily_used >= DAILY_PDF_CAP:
            log.warning("Vertex fallback: budget exceeded (%d/%d)", daily_used, DAILY_PDF_CAP)
            conn_check.close()
            return []

        from google import genai
        import json as _json

        cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
        project = None
        if cred_path and Path(cred_path).exists():
            cred_data = _json.loads(Path(cred_path).read_text())
            project = cred_data.get("project_id")

        if not project:
            conn_check.close()
            return []

        model = "gemini-2.0-flash"
        client = genai.Client(vertexai=True, project=project, location="us-central1")
        result = extract_from_pdf(client, model, pdf_path)

        # Log usage
        pdf_sha256 = _sha256_file(pdf_path)
        status_str = "OK" if result.get("ok") else result.get("error", "FAILED")
        _log_vertex_usage(conn_check, pdf_sha256, model, status_str)
        conn_check.close()

        if not result.get("ok"):
            return []

        # Convert Vertex result to engine_v2 record format
        county = pdf_path.parent.name.capitalize() if pdf_path.parent != PDF_DIR else "Unknown"
        record = {
            "case_number": "",
            "county": county,
            "owner_name": None,
            "property_address": None,
            "winning_bid": result.get("winning_bid", 0) or 0,
            "total_debt": result.get("total_debt", 0) or 0,
            "surplus_amount": result.get("surplus", 0) or 0,
            "overbid_amount": max(0, (result.get("winning_bid") or 0) - (result.get("total_debt") or 0)),
            "sale_date": result.get("sale_date"),
            "source_file": source_file,
            "confidence_score": 0.85 if result.get("ok") else 0.5,
        }
        return [record]

    except ImportError:
        log.debug("Vertex AI packages not installed — fallback disabled")
        return []
    except Exception as e:
        log.warning("Vertex fallback error for %s: %s", pdf_path.name, e)
        return []


def process_all(dry_run: bool = False, verbose: bool = False) -> dict:
    """Main processing loop."""
    stats = {
        "pdfs_scanned": 0,
        "pdfs_matched": 0,
        "records_extracted": 0,
        "enriched": 0,        # score > 0.8
        "review_required": 0,  # 0.5 < score ≤ 0.8
        "anomaly": 0,          # score ≤ 0.5
        "updated": 0,
        "inserted": 0,
        "parser_hits": {},
        "errors": [],
    }

    if not PDF_DIR.exists():
        stats["errors"].append(f"PDF directory not found: {PDF_DIR}")
        return stats

    # Collect all PDFs
    pdfs = sorted(PDF_DIR.rglob("*.pdf"))
    stats["pdfs_scanned"] = len(pdfs)
    print(f"\n  Scanning {len(pdfs)} PDFs in {PDF_DIR}")
    print(f"  Registered parsers: {[p.__class__.__name__ for p in PARSER_REGISTRY]}")
    print()

    conn = get_conn() if not dry_run else None

    try:
        for pdf_path in pdfs:
            rel = pdf_path.relative_to(PDF_DIR)
            text = extract_text(pdf_path)

            if not text.strip():
                if verbose:
                    print(f"  [EMPTY] {rel}")
                continue

            # Find matching parser
            parser = get_parser_for(text)
            if not parser:
                # ── Vertex AI Fallback ────────────────────────────────
                if _vertex_fallback_enabled():
                    if verbose:
                        print(f"  [VERTEX FALLBACK] {rel}")
                    vertex_records = _vertex_fallback(pdf_path, str(rel))
                    if vertex_records:
                        stats["pdfs_matched"] += 1
                        stats["parser_hits"]["VertexAI"] = stats["parser_hits"].get("VertexAI", 0) + 1
                        for vr in vertex_records:
                            confidence = vr.get("confidence_score", 0.0)
                            surplus = vr.get("surplus_amount", 0) or 0.0
                            grade = "GOLD" if surplus >= 10000 and confidence >= 0.8 else "SILVER" if surplus >= 5000 and confidence >= 0.6 else "BRONZE" if surplus > 0 else "IRON"
                            vr["source_name"] = "engine_v2_VertexAI"
                            vr["lead_id"] = f"vertex_{vr.get('case_number', pdf_path.stem)}"

                            if confidence > ENRICHED_THRESHOLD:
                                status = "ENRICHED"
                                stats["enriched"] += 1
                            elif confidence > REVIEW_THRESHOLD:
                                status = "REVIEW_REQUIRED"
                                stats["review_required"] += 1
                            else:
                                stats["anomaly"] += 1
                                log_anomaly(vr, confidence, "vertex_low_confidence", str(rel))
                                continue

                            stats["records_extracted"] += 1
                            if not dry_run and conn:
                                action = upsert_to_leads(conn, vr, confidence, grade, status)
                                if action == "updated":
                                    stats["updated"] += 1
                                elif action == "inserted":
                                    stats["inserted"] += 1
                        continue
                if verbose:
                    print(f"  [NO MATCH] {rel}")
                continue

            stats["pdfs_matched"] += 1
            parser_name = parser.__class__.__name__
            stats["parser_hits"][parser_name] = stats["parser_hits"].get(parser_name, 0) + 1

            # Extract records
            records = parser.extract(text, source_file=str(rel))
            stats["records_extracted"] += len(records)

            if verbose or len(records) > 0:
                print(f"  [{parser_name}] {rel}: {len(records)} records")

            for record in records:
                # Compute confidence
                confidence = parser.score(record)
                surplus = record.get("surplus_amount", 0) or 0.0
                grade = parser.grade(surplus, confidence)
                deadline = parser.compute_deadline(record.get("sale_date"))
                record["claim_deadline"] = deadline
                record["source_name"] = f"engine_v2_{parser_name}"

                # Generate lead ID
                lead_id = parser.make_lead_id(
                    record.get("case_number", ""),
                    record.get("source_file", ""),
                )
                record["lead_id"] = lead_id

                # ── Threshold routing ────────────────────────────────
                if confidence > ENRICHED_THRESHOLD:
                    status = "ENRICHED"
                    stats["enriched"] += 1
                elif confidence > REVIEW_THRESHOLD:
                    status = "REVIEW_REQUIRED"
                    stats["review_required"] += 1
                else:
                    status = "ANOMALY"
                    stats["anomaly"] += 1
                    log_anomaly(record, confidence, "low_confidence", str(rel))
                    if verbose:
                        print(f"    ANOMALY: case={record.get('case_number')} "
                              f"conf={confidence:.2f} surplus=${surplus:,.2f}")
                    continue  # Skip DB write for anomalies

                if verbose:
                    bid = record.get("winning_bid", 0)
                    debt = record.get("total_debt", 0)
                    print(f"    {status}: case={record.get('case_number')} "
                          f"bid=${bid:,.2f} debt=${debt:,.2f} "
                          f"surplus=${surplus:,.2f} conf={confidence:.2f} "
                          f"grade={grade}")

                # ── Upsert to DB ─────────────────────────────────────
                if not dry_run and conn:
                    action = upsert_to_leads(conn, record, confidence, grade, status)
                    if action == "updated":
                        stats["updated"] += 1
                    elif action == "inserted":
                        stats["inserted"] += 1

        if conn:
            conn.commit()

    except Exception as e:
        stats["errors"].append(str(e))
        log.error("Engine V2 error: %s", e)
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

    # Add alias keys for runner integration
    stats["parsed_records"] = stats["records_extracted"]
    stats["leads_inserted"] = stats["inserted"]
    stats["rejects"] = stats["anomaly"]

    return stats


# ── CLI ──────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Engine V2 — Titanium Registry Parser"
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="Parse PDFs without writing to DB")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="Show per-record output")
    args = ap.parse_args()

    print("\n" + "=" * 60)
    print("  ENGINE V2 — TITANIUM REGISTRY")
    print("=" * 60)
    print(f"  DB: {DB_PATH}")
    print(f"  PDFs: {PDF_DIR}")
    print(f"  Parsers: {len(PARSER_REGISTRY)}")
    print(f"  Thresholds: ENRICHED>{ENRICHED_THRESHOLD} REVIEW>{REVIEW_THRESHOLD}")
    print(f"  Dry run: {args.dry_run}")
    print("=" * 60)

    stats = process_all(dry_run=args.dry_run, verbose=args.verbose)

    print(f"\n{'='*60}")
    print("  ENGINE V2 RESULTS")
    print(f"{'='*60}")
    print(f"  PDFs scanned:        {stats['pdfs_scanned']}")
    print(f"  PDFs matched:        {stats['pdfs_matched']}")
    print(f"  Records extracted:   {stats['records_extracted']}")
    print(f"  ──────────────────────────────")
    print(f"  ENRICHED (>0.8):     {stats['enriched']}")
    print(f"  REVIEW_REQUIRED:     {stats['review_required']}")
    print(f"  ANOMALY (≤0.5):      {stats['anomaly']}")
    print(f"  ──────────────────────────────")
    print(f"  DB updated:          {stats['updated']}")
    print(f"  DB inserted:         {stats['inserted']}")
    print(f"  ──────────────────────────────")
    print(f"  Parser hits:         {stats['parser_hits']}")
    if stats["errors"]:
        print(f"  ERRORS:              {stats['errors']}")
    print(f"{'='*60}\n")

    if stats["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
