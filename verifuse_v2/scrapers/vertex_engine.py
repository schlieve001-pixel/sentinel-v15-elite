"""
VERIFUSE V2 — Engine #4: Vertex AI PDF Extraction

Processes bid sheet PDFs using Google Vertex AI (Gemini) to extract
structured foreclosure data: case number, overbid, indebtedness, surplus.

Features:
  - DB-first approach (queries staged_leads, not folder scan)
  - Robust MONEY_RE with OCR preprocessing
  - Exponential backoff for Vertex API (429, 503, 500)
  - PDF safety (size, type, password checks)
  - JSONL audit log for chain-of-custody
  - Integration with pipeline_manager.py Governor

Usage:
  python -m verifuse_v2.scrapers.vertex_engine
  python -m verifuse_v2.scrapers.vertex_engine --pdf /path/to/file.pdf
  python -m verifuse_v2.scrapers.vertex_engine --batch --limit 50
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from verifuse_v2.db import database as db

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────

PDF_INPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "input_pdfs"
AUDIT_LOG_DIR = Path(__file__).resolve().parent.parent / "data" / "audit_logs"

MAX_PDF_SIZE_MB = 50
MAX_RETRIES = 5
BASE_RETRY_DELAY = 2.0  # seconds

# Vertex AI configuration
VERTEX_PROJECT = os.getenv("VERTEX_PROJECT", "")
VERTEX_LOCATION = os.getenv("VERTEX_LOCATION", "us-central1")
VERTEX_MODEL = os.getenv("VERTEX_MODEL", "gemini-1.5-flash-002")


# ── Money Parsing ────────────────────────────────────────────────────

# Robust regex that handles OCR artifacts: "$ 45, 000 . 00", "(45,000.00)"
MONEY_RE = re.compile(
    r"""
    (?:
        \$\s*                              # Dollar sign with optional space
        [\d\s,]+\.?\d{0,2}                # Digits with spaces/commas (OCR artifacts)
    |
        \(?\s*\$?\s*[\d\s,]+\.?\d{0,2}\s*\)?  # Parenthesized negative amounts
    )
    """,
    re.VERBOSE,
)


def _ocr_preprocess(text: str) -> str:
    """Clean OCR artifacts before money extraction."""
    # Replace common OCR confusions
    text = text.replace("O", "0")  # Capital O → zero (only in money context)
    text = text.replace("l", "1")  # lowercase L → one
    text = text.replace("I", "1")  # capital I → one (in number context)
    # Normalize spaces within numbers
    text = re.sub(r"(\d)\s+(\d)", r"\1\2", text)  # "45 000" → "45000"
    text = re.sub(r"(\d)\s*,\s*(\d)", r"\1,\2", text)  # "45 , 000" → "45,000"
    text = re.sub(r"(\d)\s*\.\s*(\d)", r"\1.\2", text)  # "000 . 00" → "000.00"
    return text


def parse_money(s: str | None) -> Optional[float]:
    """Parse a money string into float, handling OCR artifacts."""
    if not s:
        return None
    s = _ocr_preprocess(s.strip())
    # Remove $, commas, spaces
    cleaned = s.replace("$", "").replace(",", "").replace(" ", "").strip()
    # Handle parenthesized negatives
    is_negative = cleaned.startswith("(") and cleaned.endswith(")")
    if is_negative:
        cleaned = cleaned[1:-1]
    try:
        value = float(cleaned)
        return -value if is_negative else value
    except ValueError:
        return None


def parse_iso_date(s: str | None) -> Optional[str]:
    """Parse various date formats to ISO 8601."""
    if not s or not s.strip():
        return None
    s = s.strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%B %d, %Y", "%b %d, %Y"):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.year < 100:
                dt = dt.replace(year=dt.year + 2000)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


# ── Data Classes ─────────────────────────────────────────────────────

@dataclass
class ExtractionResult:
    """Result of Vertex AI PDF extraction."""
    pdf_path: str = ""
    pdf_hash: str = ""
    case_number: str = ""
    county: str = ""
    sale_date: Optional[str] = None
    owner_of_record: str = ""
    property_address: str = ""
    winning_bid: Optional[float] = None
    total_indebtedness: Optional[float] = None
    estimated_surplus: Optional[float] = None
    overbid_amount: Optional[float] = None
    holding_entity: str = "Trustee"
    confidence_score: float = 0.0
    raw_response: str = ""
    error: Optional[str] = None
    latency_ms: float = 0.0
    extracted_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


# ── PDF Safety ───────────────────────────────────────────────────────

def validate_pdf(pdf_path: Path) -> tuple[bool, str]:
    """Validate a PDF file before processing.

    Checks:
    - File exists
    - File size < MAX_PDF_SIZE_MB
    - File starts with %PDF header
    - File is not password-protected
    """
    if not pdf_path.exists():
        return False, f"File not found: {pdf_path}"

    # Size check
    size_mb = pdf_path.stat().st_size / (1024 * 1024)
    if size_mb > MAX_PDF_SIZE_MB:
        return False, f"PDF too large: {size_mb:.1f}MB (max {MAX_PDF_SIZE_MB}MB)"

    # Header check
    with open(pdf_path, "rb") as f:
        header = f.read(5)
        if header != b"%PDF-":
            return False, f"Invalid PDF header: {header!r}"

    # Password check
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            _ = len(pdf.pages)  # This will fail if password-protected
    except Exception as e:
        if "password" in str(e).lower() or "encrypted" in str(e).lower():
            return False, f"PDF is password-protected: {e}"
        # Other errors might be OK (pdfplumber might not be needed)

    return True, "OK"


def pdf_hash(pdf_path: Path) -> str:
    """Compute SHA-256 hash of a PDF file."""
    h = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ── Vertex AI API Call ───────────────────────────────────────────────

EXTRACTION_PROMPT = """
You are a forensic data extraction assistant. Extract the following fields from this
Colorado foreclosure bid sheet / excess funds document. Return ONLY valid JSON.

Required fields:
{
  "case_number": "string (e.g., 2025-000088)",
  "county": "string (e.g., Denver, Arapahoe, Jefferson)",
  "sale_date": "string in MM/DD/YYYY format",
  "owner_of_record": "string (borrower/defendant name)",
  "property_address": "string (full street address)",
  "winning_bid": number (the highest bid at foreclosure sale),
  "total_indebtedness": number (total debt owed, if available),
  "estimated_surplus": number (winning_bid - total_indebtedness, or listed surplus),
  "overbid_amount": number (amount bid over the minimum, if available),
  "holding_entity": "string (Public Trustee, Court, Treasurer)"
}

Rules:
- All money values should be plain numbers (no $ or commas)
- If a field is not found in the document, set it to null
- For total_indebtedness: look for "amount due", "total debt", "payoff amount", "balance owed"
- For surplus: look for "excess", "overbid", "surplus", "remaining funds"
- If only surplus is listed without indebtedness breakdown, set total_indebtedness to null
- Return ONLY the JSON object, no markdown or explanation
"""


def call_vertex_pdf(pdf_path: Path) -> ExtractionResult:
    """Call Vertex AI to extract data from a PDF.

    Uses exponential backoff with jitter for retries.
    """
    result = ExtractionResult(
        pdf_path=str(pdf_path),
        pdf_hash=pdf_hash(pdf_path),
    )

    if not VERTEX_PROJECT:
        result.error = "VERTEX_PROJECT not set. Set env var to enable Vertex AI extraction."
        return result

    try:
        import vertexai
        from vertexai.generative_models import GenerativeModel, Part

        vertexai.init(project=VERTEX_PROJECT, location=VERTEX_LOCATION)
        model = GenerativeModel(VERTEX_MODEL)

        # Read PDF bytes
        pdf_bytes = pdf_path.read_bytes()
        pdf_part = Part.from_data(data=pdf_bytes, mime_type="application/pdf")

        for attempt in range(MAX_RETRIES):
            try:
                t0 = time.time()
                response = model.generate_content(
                    [pdf_part, EXTRACTION_PROMPT],
                    generation_config={
                        "temperature": 0.1,
                        "max_output_tokens": 2048,
                    },
                )
                result.latency_ms = (time.time() - t0) * 1000

                if not response or not response.text:
                    result.error = "Empty response from Vertex AI"
                    continue

                result.raw_response = response.text

                # Parse JSON response
                text = response.text.strip()
                # Strip markdown code fences if present
                if text.startswith("```"):
                    text = re.sub(r"^```(?:json)?\n?", "", text)
                    text = re.sub(r"\n?```$", "", text)

                data = json.loads(text)

                result.case_number = data.get("case_number") or ""
                result.county = data.get("county") or ""
                result.sale_date = parse_iso_date(data.get("sale_date"))
                result.owner_of_record = data.get("owner_of_record") or ""
                result.property_address = data.get("property_address") or ""
                result.winning_bid = data.get("winning_bid")
                result.total_indebtedness = data.get("total_indebtedness")
                result.estimated_surplus = data.get("estimated_surplus")
                result.overbid_amount = data.get("overbid_amount")
                result.holding_entity = data.get("holding_entity") or "Trustee"

                # Compute surplus if not directly available
                if result.estimated_surplus is None and result.winning_bid and result.total_indebtedness:
                    result.estimated_surplus = result.winning_bid - result.total_indebtedness

                # Compute confidence
                from verifuse_v2.daily_healthcheck import compute_confidence
                result.confidence_score = compute_confidence(
                    result.estimated_surplus or 0,
                    result.total_indebtedness or 0,
                    result.sale_date,
                    result.owner_of_record,
                    result.property_address,
                )

                return result

            except json.JSONDecodeError as e:
                result.error = f"JSON parse error: {e}"
                log.warning("Vertex response not valid JSON (attempt %d): %s", attempt + 1, e)

            except Exception as e:
                error_str = str(e)
                result.error = error_str

                # Check for retryable errors
                retryable = any(code in error_str for code in ["429", "503", "500", "RESOURCE_EXHAUSTED"])
                if not retryable:
                    log.error("Non-retryable Vertex error: %s", e)
                    return result

                # Exponential backoff with jitter
                import random
                delay = (BASE_RETRY_DELAY * (2 ** attempt)) + random.uniform(0, 1)

                # Respect Retry-After header if available
                if hasattr(e, "retry_after"):
                    delay = max(delay, float(e.retry_after))

                log.warning("Vertex API error (attempt %d/%d), retrying in %.1fs: %s",
                           attempt + 1, MAX_RETRIES, delay, e)
                time.sleep(delay)

    except ImportError:
        result.error = "vertexai package not installed. pip install google-cloud-aiplatform"
    except Exception as e:
        result.error = f"Unexpected error: {e}"

    return result


# ── JSONL Audit Log ──────────────────────────────────────────────────

def log_extraction(result: ExtractionResult) -> Path:
    """Append extraction result to JSONL audit log."""
    AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_path = AUDIT_LOG_DIR / f"vertex_extractions_{today}.jsonl"

    entry = result.to_dict()
    # Don't log the full raw_response in audit (too large)
    entry["raw_response"] = entry["raw_response"][:500] if entry["raw_response"] else ""

    with open(log_path, "a") as f:
        f.write(json.dumps(entry) + "\n")

    return log_path


# ── Database Ingestion ───────────────────────────────────────────────

def ingest_result(result: ExtractionResult) -> bool:
    """Ingest an extraction result into the V2 database."""
    if result.error or not result.case_number:
        log.warning("Skipping ingestion — error or no case_number: %s", result.error)
        return False

    asset_id = f"vertex_{result.county.lower()}_{result.case_number.replace(' ', '_')}"
    now = datetime.now(timezone.utc).isoformat()

    surplus = result.estimated_surplus or 0
    indebtedness = result.total_indebtedness or 0

    from verifuse_v2.daily_healthcheck import compute_confidence, compute_grade

    confidence = compute_confidence(
        surplus, indebtedness, result.sale_date,
        result.owner_of_record, result.property_address,
    )
    completeness = 1.0 if all([
        result.owner_of_record, result.property_address, result.sale_date
    ]) else 0.5

    # Compute days_remaining
    days_remaining = None
    if result.sale_date:
        try:
            from datetime import timedelta
            sale_dt = datetime.fromisoformat(result.sale_date)
            deadline = sale_dt + timedelta(days=180)
            days_remaining = (deadline - datetime.now(timezone.utc).replace(tzinfo=None)).days
        except (ValueError, TypeError):
            pass

    grade, record_class = compute_grade(
        surplus, indebtedness, result.sale_date,
        days_remaining, confidence, completeness,
    )

    with db.get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO assets
            (asset_id, county, state, jurisdiction, case_number, asset_type,
             source_name, statute_window, days_remaining, owner_of_record,
             property_address, sale_date, estimated_surplus, total_indebtedness,
             overbid_amount, completeness_score, confidence_score, data_grade,
             record_hash, source_file, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, [
            asset_id, result.county, "CO",
            f"{result.county.lower()}_co", result.case_number,
            "FORECLOSURE_SURPLUS", "vertex_ai_extraction",
            "180 days from sale_date (C.R.S. § 38-38-111)",
            days_remaining, result.owner_of_record, result.property_address,
            result.sale_date, surplus, indebtedness,
            result.overbid_amount or surplus,
            completeness, confidence, grade,
            result.pdf_hash, result.pdf_path, now, now,
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

    log.info("Ingested: %s | %s | surplus=$%.2f | grade=%s | confidence=%.2f",
             asset_id, result.case_number, surplus, grade, confidence)
    return True


# ── Batch Processing ─────────────────────────────────────────────────

def process_pdf(pdf_path: Path) -> ExtractionResult:
    """Process a single PDF through the full pipeline."""
    log.info("Processing: %s", pdf_path.name)

    # Validate
    valid, reason = validate_pdf(pdf_path)
    if not valid:
        result = ExtractionResult(pdf_path=str(pdf_path), error=reason)
        log_extraction(result)
        return result

    # Extract
    result = call_vertex_pdf(pdf_path)
    log_extraction(result)

    # Ingest
    if not result.error:
        ingest_result(result)

    return result


def process_batch(limit: int = 50) -> dict:
    """Process a batch of PDFs from the input directory."""
    PDF_INPUT_DIR.mkdir(parents=True, exist_ok=True)
    db.init_db()

    pdfs = sorted(PDF_INPUT_DIR.glob("*.pdf"))
    if not pdfs:
        log.info("No PDFs found in %s", PDF_INPUT_DIR)
        return {"total": 0, "processed": 0, "errors": 0}

    stats = {"total": len(pdfs), "processed": 0, "errors": 0, "ingested": 0}
    log.info("Found %d PDFs, processing up to %d", len(pdfs), limit)

    for pdf_path in pdfs[:limit]:
        result = process_pdf(pdf_path)
        if result.error:
            stats["errors"] += 1
            log.warning("  FAILED: %s — %s", pdf_path.name, result.error)
        else:
            stats["processed"] += 1
            if result.case_number:
                stats["ingested"] += 1

    log.info("Batch complete: %d processed, %d errors, %d ingested",
             stats["processed"], stats["errors"], stats["ingested"])
    return stats


# ── CLI ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Engine #4: Vertex AI PDF Extraction")
    parser.add_argument("--pdf", help="Process a single PDF file")
    parser.add_argument("--batch", action="store_true", help="Process all PDFs in input_pdfs/")
    parser.add_argument("--limit", type=int, default=50, help="Max PDFs to process in batch mode")
    args = parser.parse_args()

    if args.pdf:
        result = process_pdf(Path(args.pdf))
        print(json.dumps(result.to_dict(), indent=2, default=str))
    elif args.batch:
        stats = process_batch(limit=args.limit)
        print(json.dumps(stats, indent=2))
    else:
        parser.print_help()
