"""
VERIFUSE V2 — Engine #4: Vertex AI PDF Reader (Titanium Production)

Standalone CLI script. Extracts financial data from foreclosure PDFs
using Google Vertex AI (Gemini) with Titanium reliability guarantees.

Guarantees:
  - Atomic lockfile prevents concurrent runs
  - Idempotent: skips leads with existing winning_bid + total_debt
  - Safety gate: only writes if confidence > 0.8 AND bid >= debt
  - Structured JSONL audit log for every action

Usage:
    python -m verifuse_v2.scrapers.vertex_engine_production --preflight-only
    python -m verifuse_v2.scrapers.vertex_engine_production --limit 50
    python -m verifuse_v2.scrapers.vertex_engine_production --limit 10 --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from verifuse_v2.db import database as db
from verifuse_v2.daily_healthcheck import compute_confidence, compute_grade

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
AUDIT_LOG = LOG_DIR / "engine4_audit.jsonl"
LOCK_FILE = BASE_DIR / "data" / ".vertex_engine.lock"
MAX_PDF_SIZE = 50 * 1024 * 1024  # 50MB
MAX_RETRIES = 5
CONFIDENCE_GATE = 0.8  # Only write if confidence > this

# ── Regex ────────────────────────────────────────────────────────────

ISO_DATE_RE = re.compile(r"\b(20\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b")

FORCE_SCHEMA = {
    "type": "object",
    "required": ["winning_bid_raw", "total_debt_raw", "sale_date_raw", "evidence", "is_illegible"],
    "properties": {
        "winning_bid_raw": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "total_debt_raw": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "sale_date_raw": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "is_illegible": {"type": "boolean"},
        "evidence": {
            "type": "object",
            "properties": {
                "winning_bid": {"type": "object", "properties": {"snippet": {"type": "string"}}},
                "total_debt": {"type": "object", "properties": {"snippet": {"type": "string"}}},
                "sale_date": {"type": "object", "properties": {"snippet": {"type": "string"}}},
            },
        },
    },
}


# ── Atomic Lockfile ──────────────────────────────────────────────────

class LockFile:
    """Atomic lockfile using os.open with O_CREAT | O_EXCL."""

    def __init__(self, path: Path):
        self.path = path
        self.fd: Optional[int] = None

    def acquire(self) -> bool:
        """Acquire the lock. Returns True if successful."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(self.fd, f"{os.getpid()}\n".encode())
            return True
        except FileExistsError:
            # Check if the PID in the lockfile is still alive
            try:
                pid = int(self.path.read_text().strip())
                os.kill(pid, 0)  # Check if process exists
                return False  # Process is alive — real lock
            except (ValueError, ProcessLookupError, PermissionError):
                # Stale lock — remove and retry
                log.warning("Removing stale lockfile (PID no longer running)")
                self.path.unlink(missing_ok=True)
                try:
                    self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.write(self.fd, f"{os.getpid()}\n".encode())
                    return True
                except FileExistsError:
                    return False

    def release(self) -> None:
        """Release the lock."""
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        self.path.unlink(missing_ok=True)


# ── OCR-aware money parser ───────────────────────────────────────────

def parse_money(raw: Optional[str]) -> Optional[float]:
    """Parse money values with OCR-aware corrections."""
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
        log.warning("Could not parse money: %r", raw)
        return None


def parse_iso_date(raw: Optional[str]) -> Optional[str]:
    """Parse date strings into ISO format."""
    if raw is None:
        return None
    m = ISO_DATE_RE.search(str(raw).strip())
    if m:
        return m.group(0)
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y"):
        try:
            dt = datetime.strptime(str(raw).strip(), fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


# ── Pre-flight checks ───────────────────────────────────────────────

def validate_credentials() -> tuple[bool, str]:
    """Validate GOOGLE_APPLICATION_CREDENTIALS JSON file."""
    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not cred_path:
        return False, "GOOGLE_APPLICATION_CREDENTIALS env var not set"

    path = Path(cred_path)
    if not path.exists():
        return False, f"Credentials file not found: {cred_path}"

    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON in credentials: {e}"

    if "private_key" not in data:
        return False, "Credentials missing 'private_key' field"
    if "project_id" not in data:
        return False, "Credentials missing 'project_id' field"

    return True, f"OK (project: {data['project_id']})"


def validate_schema() -> tuple[bool, str]:
    """Validate DB schema has required columns."""
    required = {
        "assets": ["winning_bid", "total_debt", "surplus_amount"],
        "assets_staging": ["pdf_path", "status"],
    }
    try:
        with db.get_db() as conn:
            for table, cols in required.items():
                existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
                missing = [c for c in cols if c not in existing]
                if missing:
                    return False, f"Table '{table}' missing: {missing}. Run: python -m verifuse_v2.db.migrate_titanium"
        return True, "Schema OK"
    except Exception as e:
        return False, f"DB error: {e}"


def count_staged() -> tuple[int, str]:
    """Count staged records ready for processing."""
    try:
        with db.get_db() as conn:
            total = conn.execute("SELECT COUNT(*) FROM assets_staging").fetchone()[0]
            with_pdf = conn.execute(
                "SELECT COUNT(*) FROM assets_staging WHERE pdf_path IS NOT NULL AND status = 'STAGED'"
            ).fetchone()[0]
            return with_pdf, f"{with_pdf} ready (of {total} total staged)"
    except Exception as e:
        return 0, f"Error: {e}"


def run_preflight() -> bool:
    """Run all pre-flight checks."""
    print("\n" + "=" * 60)
    print("  ENGINE #4 — TITANIUM PRE-FLIGHT")
    print("=" * 60)

    all_pass = True

    ok, msg = validate_credentials()
    print(f"  [{'PASS' if ok else 'FAIL'}] Credentials: {msg}")
    if not ok:
        all_pass = False

    ok, msg = validate_schema()
    print(f"  [{'PASS' if ok else 'FAIL'}] Schema: {msg}")
    if not ok:
        all_pass = False

    count, msg = count_staged()
    print(f"  [{'PASS' if count > 0 else 'WARN'}] Staged: {msg}")

    print("=" * 60)
    print(f"  PRE-FLIGHT: {'ALL CHECKS PASSED' if all_pass else 'FAILED'}")
    print("=" * 60 + "\n")

    return all_pass


# ── PDF validation ───────────────────────────────────────────────────

def validate_pdf(pdf_path: Path) -> tuple[bool, str]:
    """Validate a PDF file before sending to Vertex AI."""
    if not pdf_path.exists():
        return False, "File not found"
    size = pdf_path.stat().st_size
    if size > MAX_PDF_SIZE:
        return False, f"Too large: {size / 1024 / 1024:.1f}MB"
    if size < 100:
        return False, f"Too small: {size} bytes"
    header = pdf_path.read_bytes()[:5]
    if header != b"%PDF-":
        return False, f"Not a PDF (header: {header!r})"
    return True, "OK"


# ── Audit logging ────────────────────────────────────────────────────

def _audit_log(entry: dict) -> None:
    """Append structured JSON to audit log."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    entry["timestamp"] = datetime.now(timezone.utc).isoformat()
    entry["engine"] = "vertex_engine_production"
    with open(AUDIT_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ── Core extraction ──────────────────────────────────────────────────

def extract_from_pdf(client, model: str, pdf_path: Path) -> dict:
    """Extract financial data from a PDF using Vertex AI."""
    from google.genai import types

    pdf_bytes = pdf_path.read_bytes()

    prompt = (
        "You are a forensic financial analyst. Extract the following from this "
        "foreclosure/surplus document:\n"
        "- winning_bid_raw: The winning bid or sale price amount\n"
        "- total_debt_raw: The total debt, indebtedness, or lien amount\n"
        "- sale_date_raw: The foreclosure sale date\n"
        "- is_illegible: true if the document is unreadable\n"
        "- evidence: snippets of text where you found each value\n"
        "Return ONLY the JSON. If a field is not found, use null."
    )

    pdf_part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")

    for attempt in range(MAX_RETRIES):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=[prompt, pdf_part],
                config={
                    "response_mime_type": "application/json",
                    "response_schema": FORCE_SCHEMA,
                },
            )

            parsed = resp.parsed
            if not parsed:
                return {"ok": False, "error": "empty_response"}

            if parsed.get("is_illegible"):
                return {"ok": False, "error": "illegible"}

            bid = parse_money(parsed.get("winning_bid_raw"))
            debt = parse_money(parsed.get("total_debt_raw"))
            sale_date = parse_iso_date(parsed.get("sale_date_raw"))
            surplus = max(0.0, bid - debt) if (bid is not None and debt is not None) else None

            ok = bid is not None and debt is not None and sale_date is not None

            return {
                "ok": ok,
                "winning_bid": bid,
                "total_debt": debt,
                "sale_date": sale_date,
                "surplus": surplus,
                "evidence": parsed.get("evidence", {}),
                "error": None if ok else "missing_fields",
            }

        except Exception as e:
            err_str = str(e)
            if any(code in err_str for code in ["429", "503", "500", "RESOURCE_EXHAUSTED"]):
                wait = (2 ** attempt) + random.uniform(0, 1)
                log.warning("Retry %d/%d (%.1fs): %s", attempt + 1, MAX_RETRIES, wait, err_str[:100])
                time.sleep(wait)
                continue
            return {"ok": False, "error": err_str}

    return {"ok": False, "error": f"max_retries_exceeded ({MAX_RETRIES})"}


# ── Main processing loop ────────────────────────────────────────────

def process_batch(limit: int = 50, project: str | None = None,
                  model: str = "gemini-2.0-flash", dry_run: bool = False) -> dict:
    """Process a batch of staged PDFs through Vertex AI.

    Titanium guarantees:
      - Idempotent: skips leads where winning_bid AND total_debt already set
      - Safety gate: only writes if confidence > 0.8 AND bid >= debt
      - Audit log: every action logged to JSONL
    """
    from google import genai

    stats = {"processed": 0, "ingested": 0, "failed": 0, "skipped": 0,
             "idempotent_skip": 0, "safety_reject": 0, "errors": []}
    now = datetime.now(timezone.utc).isoformat()

    if not project:
        cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
        if cred_path and Path(cred_path).exists():
            cred_data = json.loads(Path(cred_path).read_text())
            project = cred_data.get("project_id")

    if not project:
        stats["errors"].append("No project ID found")
        return stats

    client = genai.Client(vertexai=True, project=project, location="us-central1")
    log.info("Vertex AI client initialized (project: %s, model: %s)", project, model)

    # Query staged records
    with db.get_db() as conn:
        rows = conn.execute("""
            SELECT asset_id, county, case_number, property_address,
                   owner_of_record, sale_date, pdf_path
            FROM assets_staging
            WHERE status = 'STAGED' AND pdf_path IS NOT NULL
            LIMIT ?
        """, [limit]).fetchall()

    if not rows:
        log.info("No staged records with PDFs to process")
        return stats

    log.info("Processing %d staged records...", len(rows))

    for row in rows:
        asset_id = row[0]
        county = row[1] or "Unknown"
        case_number = row[2] or ""
        address = row[3] or ""
        owner = row[4] or ""
        sale_date = row[5]
        pdf_path = Path(row[6])

        if not pdf_path.is_absolute():
            pdf_path = BASE_DIR / pdf_path

        # ── Idempotency check ────────────────────────────────────
        with db.get_db() as conn:
            existing = conn.execute(
                "SELECT winning_bid, total_debt FROM assets WHERE asset_id = ?",
                [asset_id],
            ).fetchone()
            if existing and existing[0] and existing[1]:
                log.info("  [SKIP] %s: already has bid=%.2f debt=%.2f", asset_id[:20], existing[0], existing[1])
                stats["idempotent_skip"] += 1
                _audit_log({"action": "idempotent_skip", "asset_id": asset_id,
                            "winning_bid": existing[0], "total_debt": existing[1]})
                continue

        # ── PDF validation ───────────────────────────────────────
        valid, msg = validate_pdf(pdf_path)
        if not valid:
            log.warning("  [SKIP] %s: %s", asset_id[:20], msg)
            stats["skipped"] += 1
            _audit_log({"action": "skip", "asset_id": asset_id, "reason": msg})
            continue

        log.info("  [%s] %s / %s ...", asset_id[:20], county, case_number or pdf_path.name)

        if dry_run:
            log.info("    DRY RUN — would process %s", pdf_path.name)
            stats["processed"] += 1
            continue

        # ── Extract via Vertex AI ────────────────────────────────
        result = extract_from_pdf(client, model, pdf_path)
        stats["processed"] += 1

        _audit_log({
            "action": "extract",
            "asset_id": asset_id,
            "county": county,
            "case_number": case_number,
            "pdf_path": str(pdf_path),
            "result": {k: v for k, v in result.items() if k != "evidence"},
        })

        if not result["ok"]:
            log.warning("    FAILED: %s", result["error"])
            stats["failed"] += 1
            with db.get_db() as conn:
                conn.execute(
                    "UPDATE assets_staging SET status = 'FAILED', engine_version = 'titanium_v1', processed_at = ? WHERE asset_id = ?",
                    [now, asset_id],
                )
            continue

        bid = result["winning_bid"] or 0.0
        debt = result["total_debt"] or 0.0
        surplus = result["surplus"] or max(0.0, bid - debt)
        extracted_date = result["sale_date"] or sale_date

        # ── Safety gate: confidence > 0.8 AND bid >= debt ────────
        completeness = 1.0 if all([address, extracted_date, debt > 0]) else (0.8 if address else 0.5)
        confidence = compute_confidence(surplus, debt, extracted_date, owner, address)

        if confidence <= CONFIDENCE_GATE:
            log.warning("    SAFETY REJECT: confidence=%.2f (gate=%.2f)", confidence, CONFIDENCE_GATE)
            stats["safety_reject"] += 1
            _audit_log({"action": "safety_reject", "asset_id": asset_id,
                        "confidence": confidence, "gate": CONFIDENCE_GATE,
                        "bid": bid, "debt": debt})
            with db.get_db() as conn:
                conn.execute(
                    "UPDATE assets_staging SET status = 'LOW_CONFIDENCE', engine_version = 'titanium_v1', processed_at = ? WHERE asset_id = ?",
                    [now, asset_id],
                )
            continue

        if bid < debt and surplus == 0:
            log.warning("    SAFETY REJECT: bid ($%.2f) < debt ($%.2f), no surplus", bid, debt)
            stats["safety_reject"] += 1
            _audit_log({"action": "safety_reject", "asset_id": asset_id,
                        "reason": "bid_less_than_debt", "bid": bid, "debt": debt})
            with db.get_db() as conn:
                conn.execute(
                    "UPDATE assets_staging SET status = 'NO_SURPLUS', engine_version = 'titanium_v1', processed_at = ? WHERE asset_id = ?",
                    [now, asset_id],
                )
            continue

        # ── Compute grade and claim deadline ─────────────────────
        claim_deadline = None
        days_remaining = None
        if extracted_date:
            try:
                dt = datetime.fromisoformat(extracted_date)
                deadline = dt + timedelta(days=180)
                claim_deadline = deadline.strftime("%Y-%m-%d")
                days_remaining = (deadline - datetime.now(timezone.utc).replace(tzinfo=None)).days
            except (ValueError, TypeError):
                pass

        grade, record_class = compute_grade(surplus, debt, extracted_date, days_remaining, confidence, completeness)

        # ── Write to DB ──────────────────────────────────────────
        with db.get_db() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO assets
                (asset_id, county, state, jurisdiction, case_number, asset_type,
                 source_name, statute_window, days_remaining, owner_of_record,
                 property_address, sale_date, claim_deadline,
                 winning_bid, total_debt, surplus_amount,
                 estimated_surplus, total_indebtedness, overbid_amount,
                 completeness_score, confidence_score, data_grade,
                 vertex_processed, source_file, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?)
            """, [
                asset_id, county, "CO", f"{county.lower()}_co",
                case_number, "FORECLOSURE_SURPLUS",
                "vertex_ai_titanium",
                "180 days from sale_date (C.R.S. § 38-38-111)",
                days_remaining, owner, address, extracted_date, claim_deadline,
                bid, debt, surplus,
                surplus, debt, max(0.0, bid - debt),
                completeness, confidence, grade,
                str(pdf_path), now, now,
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

            conn.execute(
                "UPDATE assets_staging SET status = 'PROCESSED', engine_version = 'titanium_v1', processed_at = ? WHERE asset_id = ?",
                [now, asset_id],
            )

        stats["ingested"] += 1
        log.info("    OK: bid=$%.2f debt=$%.2f surplus=$%.2f conf=%.2f grade=%s",
                 bid, debt, surplus, confidence, grade)

        time.sleep(1.0)  # Rate limit courtesy

    # ── Pipeline event ───────────────────────────────────────────
    db.log_pipeline_event(
        "SYSTEM", "TITANIUM_ENGINE4_BATCH",
        f"Processed {stats['processed']} PDFs",
        f"Ingested {stats['ingested']}, Failed {stats['failed']}, "
        f"Safety rejected {stats['safety_reject']}, Idempotent skip {stats['idempotent_skip']}",
        actor="vertex_engine_production",
        reason=f"model={model}, project={project}",
    )

    return stats


# ── CLI ──────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Engine #4 — Vertex AI (Titanium Production)")
    ap.add_argument("--preflight-only", action="store_true", help="Run pre-flight checks only")
    ap.add_argument("--limit", type=int, default=50, help="Max records to process")
    ap.add_argument("--project", help="GCP project ID")
    ap.add_argument("--model", default="gemini-2.0-flash", help="Gemini model")
    ap.add_argument("--dry-run", action="store_true", help="Validate PDFs without calling Vertex AI")
    args = ap.parse_args()

    if args.preflight_only:
        ok = run_preflight()
        sys.exit(0 if ok else 1)

    if not run_preflight():
        sys.exit(1)

    # Acquire atomic lockfile
    lock = LockFile(LOCK_FILE)
    if not lock.acquire():
        log.error("Another instance is running (lockfile: %s). Exiting.", LOCK_FILE)
        sys.exit(1)

    try:
        result = process_batch(
            limit=args.limit,
            project=args.project,
            model=args.model,
            dry_run=args.dry_run,
        )
    finally:
        lock.release()

    print("\n" + "=" * 60)
    print("  ENGINE #4 — TITANIUM RESULTS")
    print("=" * 60)
    for k, v in result.items():
        if k != "errors":
            print(f"  {k}: {v}")
    if result["errors"]:
        print(f"  errors: {result['errors']}")
    print("=" * 60)

    if result["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
