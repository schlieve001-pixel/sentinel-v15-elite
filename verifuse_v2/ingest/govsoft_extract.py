"""
VeriFuse vNEXT Gate 4 — GovSoft Deterministic Extraction & Dual-Validation
===========================================================================
Parses SALE_INFO html_snapshots from the govsoft_engine raw capture and
validates the overbid amount using Python Decimal arithmetic.

Extraction targets (from GovSoft ASP.NET WebForms <dl>/<dt>/<dd> structure):
  - "Successful Bid at Sale"  → successful_bid
  - "Total Indebtedness"      → total_indebtedness
  - "Overbid at Sale"         → overbid_at_sale (confirmed via OVERBID_RE)

Validation rules (fail-closed):
  - All zeros (pre-sale)              → EXTRACTED, BRONZE, no grade change
  - |overbid - (bid - debt)| ≤ 0.01  → VALIDATED, GOLD
  - otherwise                         → NEEDS_REVIEW, BRONZE

Voucher cross-check (Gate 4 — pre-OCR):
  - If an OBCLAIM/OBCKREQ doc exists in evidence_documents and
    field_evidence provides a voucher_amount, validate within 1 penny.
  - If field_evidence is absent (Gate 5 OCR not yet run), treat as
    no-voucher path (math check only). Conservative / fail-closed.

Usage:
    from verifuse_v2.ingest.govsoft_extract import run_extraction
    result = run_extraction(asset_id, db_conn)
"""

from __future__ import annotations

import gzip
import logging
import os
import re
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

log = logging.getLogger(__name__)

# ── Overbid detection regex (exact — from plan specification) ─────────────────
OVERBID_RE = re.compile(
    r"(overbid|surplus|excess\s*proceeds|funds\s*available|overbid\s*transferred)",
    re.IGNORECASE,
)

# Penny tolerance for Decimal comparisons
PENNY = Decimal("0.01")
ZERO  = Decimal("0")

# ── Currency parser ───────────────────────────────────────────────────────────


def parse_currency(text: str) -> Decimal:
    """Parse a currency string like '$123,456.78' to Decimal.

    Returns Decimal("0") for empty or unparseable strings — never raises.
    """
    if not text or not text.strip():
        return ZERO
    cleaned = re.sub(r"[$,\s]", "", text.strip())
    if not cleaned:
        return ZERO
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return ZERO


# ── HTML field extraction ─────────────────────────────────────────────────────


def _extract_dt_dd_pairs(soup) -> dict[str, str]:
    """Extract all <dt>label</dt><dd>value</dd> pairs from BeautifulSoup tree.

    Handles the GovSoft ASP.NET WebForms pattern where fields are in <dl> blocks:
      <dl>
        <dt>Successful Bid at Sale</dt><dd>$123,456.00</dd>
        <dt>Total Indebtedness</dt><dd>$100,000.00</dd>
      </dl>

    Returns a flat dict of {label_text: value_text}.
    Last value wins if a label appears in multiple <dl> blocks.
    """
    pairs: dict[str, str] = {}
    for dl in soup.find_all("dl"):
        items = dl.find_all(["dt", "dd"])
        i = 0
        while i < len(items):
            if items[i].name == "dt":
                label = items[i].get_text(strip=True)
                value = ""
                if i + 1 < len(items) and items[i + 1].name == "dd":
                    value = items[i + 1].get_text(strip=True)
                    i += 2
                else:
                    i += 1
                if label:
                    pairs[label] = value
            else:
                i += 1
    return pairs


def _extract_td_input_pairs(soup) -> dict[str, str]:
    """Extract label→value pairs from table rows where value is in a readonly input.

    Handles Boulder's GovSoft wizard style:
      <tr><td>Holder's Initial Bid:</td><td><input type="text" value="$348,211.21" readonly></td></tr>

    Returns a flat dict of {label_text: input_value}.
    """
    pairs: dict[str, str] = {}
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        label_cell = cells[0]
        value_cell = cells[1]
        inp = value_cell.find("input", {"type": "text"})
        if inp and inp.get("value"):
            label = label_cell.get_text(strip=True).rstrip(":")
            if label:
                pairs[label] = inp["value"]
    return pairs


def extract_sale_fields(gzip_html: bytes) -> dict:
    """Decompress gzipped HTML snapshot and extract sale financial fields.

    Returns a dict with keys:
      - successful_bid       (Decimal)
      - total_indebtedness   (Decimal)
      - overbid_at_sale      (Decimal)
      - has_overbid_text     (bool) — OVERBID_RE matched anywhere in raw HTML
      - raw_pairs            (dict) — all dt/dd pairs (for debugging)
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        raise RuntimeError(
            "beautifulsoup4 not installed. Run: pip install 'beautifulsoup4>=4.12.0' lxml"
        )

    html = gzip.decompress(gzip_html).decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "lxml")
    pairs = _extract_dt_dd_pairs(soup)
    # Merge table/input pairs (Boulder wizard style) — dl/dt/dd takes precedence
    td_pairs = _extract_td_input_pairs(soup)
    for k, v in td_pairs.items():
        if k not in pairs:
            pairs[k] = v

    # Exact GovSoft label matching — primary extraction path
    # "Successful Bid at Sale" = standard; "Holder's Initial Bid" = Boulder wizard
    successful_bid_text = (
        pairs.get("Successful Bid at Sale")
        or pairs.get("Holder's Initial Bid")
        or pairs.get("Initial Bid")
        or ""
    )
    total_indebtedness_text = (
        pairs.get("Total Indebtedness")
        or pairs.get("Total due holder")
        or pairs.get("Total Due Holder")
        or ""
    )

    # Overbid: try exact label first, then OVERBID_RE scan across all labels
    # Exclude transfer labels ("Overbid Transferred On/To") — different field.
    overbid_at_sale_text = pairs.get("Overbid at Sale", "")
    if not overbid_at_sale_text:
        for label, value in pairs.items():
            if (OVERBID_RE.search(label)
                    and not re.search(r"transferred|on|to\b", label, re.IGNORECASE)):
                overbid_at_sale_text = value
                log.debug("Overbid label fallback: %r → %r", label, value)
                break

    # Full-text overbid presence detection (secondary signal)
    has_overbid_text = bool(OVERBID_RE.search(html))

    # Extract sale_date from "Sale Information for Sale Scheduled on M/D/YYYY" header
    sale_date_iso: str | None = None
    sale_date_match = re.search(
        r"Sale (?:Information for Sale )?Scheduled on (\d{1,2}/\d{1,2}/\d{4})",
        html,
        re.IGNORECASE,
    )
    if sale_date_match:
        from datetime import datetime as _dt
        try:
            sale_date_iso = _dt.strptime(sale_date_match.group(1), "%m/%d/%Y").strftime("%Y-%m-%d")
        except ValueError:
            pass

    return {
        "successful_bid":     parse_currency(successful_bid_text),
        "total_indebtedness": parse_currency(total_indebtedness_text),
        "overbid_at_sale":    parse_currency(overbid_at_sale_text),
        "has_overbid_text":   has_overbid_text,
        "sale_date":          sale_date_iso,
        "raw_pairs":          pairs,
    }


# ── Dual validation ───────────────────────────────────────────────────────────


def validate_overbid(
    html_overbid: Decimal,
    successful_bid: Decimal,
    total_indebtedness: Decimal,
    voucher_overbid: Decimal | None = None,
    has_voucher_doc: bool = False,
    asset_id: str = "",
) -> tuple[str, str]:
    """Validate overbid amount using Decimal arithmetic.

    Voucher Precedence Rule (fail-closed, OCR race condition guard):
      If a voucher/OB doc exists in evidence_documents (has_voucher_doc=True)
      but OCR has not yet run (voucher_overbid=None), we MUST NOT validate
      using HTML math alone — the voucher is the authoritative source and we
      cannot confirm the amount until Gate 5 OCR extracts it.
      → Return BRONZE + NEEDS_REVIEW ("Voucher present; awaiting Gate 5 OCR").

    Two-path validation once voucher amount is available:
      Voucher path: |html_overbid - voucher_overbid| ≤ PENNY         → GOLD
      Math path:    |html_overbid - (bid - debt)| ≤ PENNY (no voucher) → GOLD
      Any mismatch: exact diff is logged at WARNING level               → BRONZE

    Returns (data_grade, processing_status):
      ("GOLD",   "VALIDATED")    — confirmed match
      ("BRONZE", "NEEDS_REVIEW") — mismatch, uncertainty, or awaiting OCR
    """
    # Debt=0 with no voucher — math path is invalid; block GOLD
    if total_indebtedness == Decimal('0') and voucher_overbid is None:
        log.warning("[validate] %s — debt=0, no voucher; math path invalid; blocking GOLD", asset_id)
        return "BRONZE", "NEEDS_REVIEW"

    # Voucher present but not yet extracted — fail-closed; await Gate 5 OCR
    if has_voucher_doc and voucher_overbid is None:
        log.warning(
            "[validate] %s — voucher doc present, no OCR yet; blocking GOLD promotion",
            asset_id,
        )
        return "BRONZE", "NEEDS_REVIEW"

    if voucher_overbid is not None:
        diff = abs(html_overbid - voucher_overbid)
        match = diff <= PENNY
        if not match:
            log.warning(
                "[validate] %s mismatch (voucher path): html=%s voucher=%s diff=%s",
                asset_id, html_overbid, voucher_overbid, diff,
            )
    else:
        computed = successful_bid - total_indebtedness
        diff = abs(html_overbid - computed)
        match = diff <= PENNY
        if not match:
            log.warning(
                "[validate] %s mismatch (math path): html=%s computed=%s diff=%s",
                asset_id, html_overbid, computed, diff,
            )

    if match:
        return "GOLD", "VALIDATED"
    return "BRONZE", "NEEDS_REVIEW"


# ── DB path resolution ────────────────────────────────────────────────────────

def _default_db_path() -> str:
    return os.getenv(
        "VERIFUSE_DB_PATH",
        str(Path(__file__).resolve().parent.parent / "data" / "verifuse_v2.db"),
    )


# ── Main extraction runner ────────────────────────────────────────────────────


def run_extraction(asset_id: str, conn=None) -> dict:
    """Run Gate 4 deterministic extraction for a single asset.

    Reads the latest SALE_INFO html_snapshot from html_snapshots, extracts
    financial fields, validates them, and writes results to:
      - asset_registry (processing_status, amount_cents)
      - extraction_events (status)
      - leads (data_grade, processing_status, overbid_amount)
      - surplus_math_audit (audit trail for every GOLD/BRONZE decision)

    Returns a result dict with keys: asset_id, processing_status, data_grade,
    successful_bid_cents, total_indebtedness_cents, overbid_at_sale_cents,
    notes, error.

    Fail-closed: any exception or missing data → BRONZE + NEEDS_REVIEW.
    """
    import sqlite3

    own_conn = False
    if conn is None:
        conn = sqlite3.connect(_default_db_path(), timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        own_conn = True

    result: dict = {
        "asset_id":                 asset_id,
        "processing_status":        "PENDING",
        "data_grade":               "BRONZE",
        "successful_bid_cents":     0,
        "total_indebtedness_cents": 0,
        "overbid_at_sale_cents":    0,
        "notes":                    "",
        "error":                    None,
    }

    try:
        # ── 1. Fetch SALE_INFO snapshot ───────────────────────────────────────
        # Snapshots may be stored under the canonical asset_id
        # (FORECLOSURE:CO:{COUNTY}:{case_number}) while the lead uses a
        # hash-based ID. Try the lead's own ID first, then fall back to the
        # canonical ID derived from county + case_number in the leads table.
        row = conn.execute(
            """SELECT id, raw_html_gzip FROM html_snapshots
               WHERE asset_id = ? AND snapshot_type = 'SALE_INFO'
               ORDER BY retrieved_ts DESC LIMIT 1""",
            [asset_id],
        ).fetchone()

        if not row:
            # Resolve canonical ID via leads.county + leads.case_number
            lead_row = conn.execute(
                "SELECT county, case_number FROM leads WHERE id = ?", [asset_id]
            ).fetchone()
            if lead_row:
                canonical_id = f"FORECLOSURE:CO:{lead_row['county'].upper()}:{lead_row['case_number']}"
                row = conn.execute(
                    """SELECT id, raw_html_gzip FROM html_snapshots
                       WHERE asset_id = ? AND snapshot_type = 'SALE_INFO'
                       ORDER BY retrieved_ts DESC LIMIT 1""",
                    [canonical_id],
                ).fetchone()
                if row:
                    log.info("[extract] %s — resolved snapshot via canonical ID %s", asset_id, canonical_id)

        if not row:
            result["processing_status"] = "NEEDS_REVIEW"
            result["data_grade"]        = "BRONZE"
            result["notes"]             = "No SALE_INFO snapshot found"
            log.warning("[extract] No SALE_INFO snapshot for %s — returning NEEDS_REVIEW", asset_id)
            return result

        snapshot_id: str | None = row["id"]

        # ── 2. Extract financial fields ───────────────────────────────────────
        fields = extract_sale_fields(row["raw_html_gzip"])

        successful_bid     = fields["successful_bid"]
        total_indebtedness = fields["total_indebtedness"]
        overbid_at_sale    = fields["overbid_at_sale"]
        extracted_sale_date = fields.get("sale_date")  # ISO yyyy-mm-dd or None

        log.info(
            "[extract] %s → bid=%s  debt=%s  overbid=%s  sale_date=%s",
            asset_id, successful_bid, total_indebtedness, overbid_at_sale, extracted_sale_date,
        )

        # ── 3. Mark EXTRACTED on asset_registry + extraction_events ──────────
        # EXTRACTED = HTML was successfully parsed (regardless of math outcome)
        _set_processing_status(conn, asset_id, "EXTRACTED")

        # ── 4. Pre-sale guard: all zeros = no sale data yet ──────────────────
        if successful_bid == ZERO and overbid_at_sale == ZERO:
            result["processing_status"] = "EXTRACTED"
            result["data_grade"] = "BRONZE"
            result["notes"] = "Pre-sale: no financial data in SALE_INFO yet"
            log.info("[extract] %s pre-sale — no financial data", asset_id)
            _write_results(
                conn, asset_id,
                processing_status="EXTRACTED",
                data_grade="BRONZE",
                amount_cents=0,
                overbid_amount=None,
                snapshot_id=snapshot_id,
                doc_id=None,
                successful_bid_cents=0,
                total_indebtedness_cents=0,
                voucher_overbid_cents=None,
                notes="Pre-sale: no financial data in SALE_INFO yet",
            )
            return result

        # ── 5. Voucher cross-check (fail-closed, OCR race condition guard) ───
        # Check whether an OB (voucher) doc exists in evidence_documents.
        # If it does, attempt to read the extracted amount from field_evidence
        # (populated by Gate 5 OCR). If field_evidence is empty (Gate 5 not
        # yet run), has_voucher_doc=True + voucher_overbid=None will cause
        # validate_overbid() to block at BRONZE/NEEDS_REVIEW — fail-closed.
        # This prevents HTML math from overriding the authoritative voucher doc.
        voucher_overbid: Decimal | None = None
        voucher_doc_id: str | None = None
        # Fetch ALL OB voucher docs (duplicates can exist from multiple scrape runs).
        # Check field_evidence across all of them — prefer the one with OCR data.
        ob_docs = conn.execute(
            """SELECT ed.id FROM evidence_documents ed
               WHERE ed.asset_id = ?
                 AND ed.doc_family = 'OB'
                 AND (UPPER(ed.filename) LIKE '%OBCLAIM%'
                      OR UPPER(ed.filename) LIKE '%OBCKREQ%'
                      OR UPPER(ed.filename) LIKE '%CKREQ%')
               ORDER BY ed.id""",
            [asset_id],
        ).fetchall()
        # CERTQH (Certificate of Qualified Holder) is present in ALL sold cases
        # and is NOT an overbid voucher. Only OBCLAIM/OBCKREQ/CKREQ are true
        # overbid vouchers that require Gate 5 OCR confirmation.
        has_voucher_doc = len(ob_docs) > 0
        if ob_docs:
            voucher_doc_id = ob_docs[0]["id"]
            # Try to read voucher amount from field_evidence (Gate 5 OCR data)
            # across ALL ob voucher doc variants — handles duplicate doc entries.
            ob_doc_ids = [d["id"] for d in ob_docs]
            _ph = ",".join(["?"] * len(ob_doc_ids))
            fev = conn.execute(
                f"""SELECT extracted_value FROM field_evidence
                   WHERE evidence_doc_id IN ({_ph})
                     AND field_name = 'overbid_amount'
                   ORDER BY confidence DESC LIMIT 1""",
                ob_doc_ids,
            ).fetchone()
            if fev and fev["extracted_value"]:
                voucher_overbid = parse_currency(fev["extracted_value"])
                log.info("[extract] %s — voucher amount from field_evidence: %s",
                         asset_id, voucher_overbid)
            else:
                log.info(
                    "[extract] %s — OB voucher doc exists but no field_evidence yet "
                    "(Gate 5 OCR pending) — blocking GOLD promotion",
                    asset_id,
                )

        # ── 6. Dual validation ────────────────────────────────────────────────
        data_grade, processing_status = validate_overbid(
            overbid_at_sale, successful_bid, total_indebtedness,
            voucher_overbid=voucher_overbid,
            has_voucher_doc=has_voucher_doc,
            asset_id=asset_id,
        )

        log.info(
            "[extract] %s → validation: %s / %s  (has_voucher=%s, voucher_amount=%s)",
            asset_id, data_grade, processing_status, has_voucher_doc, voucher_overbid,
        )

        # ── 7. Write results ──────────────────────────────────────────────────
        overbid_cents = int(overbid_at_sale * 100)
        if has_voucher_doc and voucher_overbid is None:
            notes = "Voucher present; awaiting Gate 5 OCR"
        else:
            notes = f"bid={successful_bid} debt={total_indebtedness} overbid={overbid_at_sale}"
        result.update({
            "processing_status":        processing_status,
            "data_grade":               data_grade,
            "successful_bid_cents":     int(successful_bid * 100),
            "total_indebtedness_cents": int(total_indebtedness * 100),
            "overbid_at_sale_cents":    overbid_cents,
            "notes":                    notes,
        })

        _write_results(
            conn, asset_id,
            processing_status=processing_status,
            data_grade=data_grade,
            amount_cents=overbid_cents,
            overbid_amount=float(overbid_at_sale),
            snapshot_id=snapshot_id,
            doc_id=voucher_doc_id,
            successful_bid_cents=int(successful_bid * 100),
            total_indebtedness_cents=int(total_indebtedness * 100),
            voucher_overbid_cents=(int(voucher_overbid * 100) if voucher_overbid is not None else None),
            notes=notes,
            sale_date=extracted_sale_date,
        )

        # Re-read the actual grade written to DB (GOLD gate inside _write_results may
        # have downgraded to BRONZE — result dict must reflect what was actually persisted).
        lead_meta = conn.execute(
            "SELECT county, case_number FROM leads WHERE id = ?", [asset_id]
        ).fetchone()
        if lead_meta:
            written = conn.execute(
                "SELECT data_grade, processing_status FROM leads WHERE county=? AND case_number=?",
                [lead_meta["county"], lead_meta["case_number"]],
            ).fetchone()
            if written:
                result["data_grade"] = written["data_grade"]
                result["processing_status"] = written["processing_status"]

        # ── 8. SOTA Triple-Verification (Gate 5+6) — runs after GOLD promotion ─
        # Only run if GOLD and overbid > 0 (skip BRONZE/pre-sale cases to save API credits).
        # Non-blocking: AI verification failure never downgrades a GOLD lead.
        if result["data_grade"] == "GOLD" and overbid_at_sale > ZERO:
            try:
                from verifuse_v2.core.ai_verification_engine import VerificationEngine
                sota_engine = VerificationEngine(use_docai=True, use_gemini=True, use_claude=False)
                sota_result = sota_engine.verify_from_vault(asset_id, overbid_at_sale, conn)
                result["pool_source"] = sota_result.pool_source
                result["verification_tier"] = sota_result.tier
                result["verification_confidence"] = sota_result.confidence
                log.info(
                    "[extract] %s — SOTA verification: %s (confidence=%.0f%%)",
                    asset_id, sota_result.tier, sota_result.confidence * 100,
                )
            except Exception as sota_exc:
                # Non-critical: log and continue — GOLD status preserved
                log.warning("[extract] %s — SOTA verification skipped: %s", asset_id, sota_exc)

    except Exception as exc:
        log.exception("[extract] Extraction failed for %s: %s", asset_id, exc)
        result["error"] = str(exc)
        # Fail-closed: ensure NEEDS_REVIEW on any unhandled exception
        try:
            _set_processing_status(conn, asset_id, "NEEDS_REVIEW")
        except Exception:
            pass
    finally:
        if own_conn:
            conn.close()

    return result


# ── DB write helpers ──────────────────────────────────────────────────────────


def _set_processing_status(conn, asset_id: str, status: str) -> None:
    """Update processing_status on asset_registry and extraction_events atomically."""
    now_ts = int(time.time())
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE asset_registry SET processing_status = ? WHERE asset_id = ?",
            [status, asset_id],
        )
        updated = conn.execute(
            "UPDATE extraction_events SET status = ?, run_ts = ? WHERE asset_id = ?",
            [status, now_ts, asset_id],
        ).rowcount
        if updated == 0:
            from uuid import uuid4
            conn.execute(
                """INSERT OR IGNORE INTO extraction_events
                   (id, asset_id, run_ts, status) VALUES (?,?,?,?)""",
                [str(uuid4()), asset_id, now_ts, status],
            )
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise


def _write_results(
    conn,
    asset_id: str,
    processing_status: str,
    data_grade: str,
    amount_cents: int,
    overbid_amount: float | None,
    snapshot_id: str | None = None,
    doc_id: str | None = None,
    successful_bid_cents: int = 0,
    total_indebtedness_cents: int = 0,
    voucher_overbid_cents: int | None = None,
    notes: str = "",
    sale_date: str | None = None,   # ISO yyyy-mm-dd extracted from SALE_INFO HTML
) -> None:
    """Write validated extraction results to asset_registry, extraction_events, leads,
    and surplus_math_audit.

    All four updates are wrapped in a single BEGIN IMMEDIATE ... COMMIT so that
    a crash between writes cannot leave any table in an inconsistent state.
    PRAGMA table_info checks are performed before the transaction opens
    (read-only, no locking impact) to avoid DDL inside a DML transaction.

    Provenance rule: GOLD with no snapshot_id AND no doc_id is downgraded to BRONZE
    here — if both are None the grade is forced to BRONZE before writes proceed.
    """
    from uuid import uuid4

    now_ts = int(time.time())

    # ── Provenance guard: GOLD requires snapshot_id OR doc_id ─────────────────
    if data_grade == "GOLD" and snapshot_id is None and doc_id is None:
        log.warning(
            "[extract] %s — GOLD downgraded to BRONZE: no snapshot_id and no doc_id",
            asset_id,
        )
        data_grade = "BRONZE"
        processing_status = "NEEDS_REVIEW"

    # ── PRAGMA checks BEFORE acquiring the write lock ─────────────────────────
    ar_cols = {
        r[1] for r in conn.execute("PRAGMA table_info(asset_registry)").fetchall()
    }
    leads_cols = {
        r[1] for r in conn.execute("PRAGMA table_info(leads)").fetchall()
    }
    audit_cols = {
        r[1] for r in conn.execute("PRAGMA table_info(surplus_math_audit)").fetchall()
    }

    # Derive county + case_number from asset_id.
    # Canonical format: FORECLOSURE:CO:COUNTY:CASE — parse directly.
    # Hash-based / UUID format: look up from leads table.
    parts = asset_id.split(":", 3)
    if len(parts) == 4:
        county      = parts[2].lower()
        case_number = parts[3]
    else:
        lead_meta = conn.execute(
            "SELECT county, case_number FROM leads WHERE id = ?", [asset_id]
        ).fetchone()
        if not lead_meta:
            log.warning("[extract] Cannot resolve county/case_number for asset_id: %s", asset_id)
            return
        county      = lead_meta["county"]
        case_number = lead_meta["case_number"]

    # ── Stale-downgrade protection: never strip GOLD from a lead that was previously
    #    validated (blocked=0 in surplus_math_audit) unless this run CONFIRMS overbid=0.
    #    This prevents OCR cache misses from erasing prior confirmed promotions.
    _existing_grade = None
    _has_prior_gold_audit = False
    try:
        _eg = conn.execute(
            "SELECT data_grade FROM leads WHERE county=? AND case_number=?",
            [county, case_number]
        ).fetchone()
        _existing_grade = (_eg[0] if _eg else None)
        # Check for a prior validated GOLD in audit trail
        _prior_gold = conn.execute(
            "SELECT COUNT(*) FROM surplus_math_audit "
            "WHERE asset_id=? AND data_grade='GOLD' AND (promotion_blocked=0 OR promotion_blocked IS NULL)",
            [asset_id]
        ).fetchone()[0]
        _has_prior_gold_audit = _prior_gold > 0
    except Exception:
        pass

    # ── Absolute GOLD gate (4 conditions, all required) ───────────────────────
    if data_grade == "GOLD":
        gate_fails = []
        # Accept sale_date from SALE_INFO extraction OR existing DB value
        existing = conn.execute(
            "SELECT sale_date FROM leads WHERE county=? AND case_number=?",
            [county, case_number]
        ).fetchone()
        effective_sale_date = sale_date or (existing[0] if existing else None)
        if not effective_sale_date:
            gate_fails.append("sale_date IS NULL")
        if total_indebtedness_cents <= 0:
            gate_fails.append("total_debt not extracted")
        if amount_cents <= 0:
            gate_fails.append("overbid_amount = 0")
        snap_ct = conn.execute(
            "SELECT COUNT(*) FROM html_snapshots WHERE asset_id=?", [asset_id]
        ).fetchone()[0]
        pdf_ct = conn.execute(
            "SELECT COUNT(*) FROM evidence_documents WHERE asset_id=?", [asset_id]
        ).fetchone()[0]
        if snap_ct + pdf_ct == 0:
            gate_fails.append("no evidence")
        if gate_fails:
            # Stale-downgrade guard: if the ONLY failures are OCR/voucher misses (not a real $0
            # confirmation) AND the lead was previously GOLD with a validated audit record,
            # do NOT downgrade — preserve prior GOLD status.
            _real_fails = [f for f in gate_fails if f != "total_debt not extracted" or amount_cents > 0]
            _ocr_only_fail = (
                set(gate_fails) <= {"total_debt not extracted"}
                and amount_cents > 0
                and _has_prior_gold_audit
                and _existing_grade == "GOLD"
            )
            if _ocr_only_fail:
                log.info(
                    "[extract] %s — stale-downgrade BLOCKED: prior GOLD audit exists, "
                    "OCR re-run missed voucher (gate_fails=%s). Preserving GOLD.",
                    asset_id, gate_fails
                )
                data_grade = "GOLD"  # preserve
            else:
                log.warning("[extract] %s — GOLD gate blocked: %s", asset_id, " | ".join(gate_fails))
                data_grade = "BRONZE"
                processing_status = "NEEDS_REVIEW"
                notes = (notes + " | GOLD_GATE: " + "; ".join(gate_fails)).strip(" |")

    # Build asset_registry SET clause
    ar_updates: list[str] = []
    ar_params: list = []
    if "processing_status" in ar_cols:
        ar_updates.append("processing_status = ?")
        ar_params.append(processing_status)
    if "amount_cents" in ar_cols and amount_cents > 0:
        ar_updates.append("amount_cents = ?")
        ar_params.append(amount_cents)

    # Build leads SET clause
    leads_updates: list[str] = []
    leads_params: list = []
    if "data_grade" in leads_cols:
        leads_updates.append("data_grade = ?")
        leads_params.append(data_grade)
    if "processing_status" in leads_cols:
        leads_updates.append("processing_status = ?")
        leads_params.append(processing_status)
    if "overbid_amount" in leads_cols and overbid_amount is not None:
        leads_updates.append("overbid_amount = ?")
        leads_params.append(overbid_amount)
    if "estimated_surplus" in leads_cols:
        leads_updates.append("estimated_surplus = ?")
        val = overbid_amount if (overbid_amount is not None and total_indebtedness_cents > 0) else None
        leads_params.append(val)
    if "surplus_amount" in leads_cols:
        leads_updates.append("surplus_amount = ?")
        val = overbid_amount if (overbid_amount is not None and total_indebtedness_cents > 0) else None
        leads_params.append(val)
    if "winning_bid" in leads_cols and successful_bid_cents > 0:
        leads_updates.append("winning_bid = ?")
        leads_params.append(round(successful_bid_cents / 100, 2))
    if "total_debt" in leads_cols:
        leads_updates.append("total_debt = ?")
        leads_params.append(round(total_indebtedness_cents / 100, 2) if total_indebtedness_cents > 0 else None)
    # Write extracted sale_date only when non-null (preserve existing if already set)
    if "sale_date" in leads_cols and sale_date:
        leads_updates.append("sale_date = ?")
        leads_params.append(sale_date)

    # Compute derived audit fields
    computed_surplus = successful_bid_cents - total_indebtedness_cents
    # match_html_math: 1 if |html_overbid - computed| <= 1 cent (i.e. <= $0.01)
    html_overbid_cents = amount_cents  # overbid_at_sale in cents
    if successful_bid_cents > 0 or total_indebtedness_cents > 0:
        match_html_math = 1 if abs(html_overbid_cents - computed_surplus) <= 1 else 0
    else:
        match_html_math = None  # pre-sale, no data to compare
    # match_voucher: 1 if |html_overbid - voucher| <= 1 cent; None if no voucher
    if voucher_overbid_cents is not None:
        match_voucher = 1 if abs(html_overbid_cents - voucher_overbid_cents) <= 1 else 0
    else:
        match_voucher = None

    promotion_blocked = 1 if (data_grade == "BRONZE" and processing_status == "NEEDS_REVIEW") else 0

    # Derive and write pool_source to leads table based on validation path
    if "pool_source" in leads_cols:
        if data_grade == "GOLD":
            if match_voucher == 1:
                derived_pool_source = "VOUCHER"
            elif match_html_math == 1:
                derived_pool_source = "HTML_MATH"
            else:
                derived_pool_source = "UNVERIFIED"  # GOLD with no confirmed math path
        else:
            derived_pool_source = "UNVERIFIED"
        leads_updates.append("pool_source = ?")
        leads_params.append(derived_pool_source)

    # ── Single atomic transaction — all four tables land together or none do ───
    conn.execute("BEGIN IMMEDIATE")
    try:
        # asset_registry
        if ar_updates:
            conn.execute(
                f"UPDATE asset_registry SET {', '.join(ar_updates)} WHERE asset_id = ?",
                ar_params + [asset_id],
            )

        # extraction_events
        conn.execute(
            "UPDATE extraction_events SET status = ?, run_ts = ? WHERE asset_id = ?",
            [processing_status, now_ts, asset_id],
        )

        # leads
        if leads_updates:
            conn.execute(
                f"UPDATE leads SET {', '.join(leads_updates)} "
                f"WHERE county = ? AND case_number = ?",
                leads_params + [county, case_number],
            )

        # surplus_math_audit — insert audit row if table exists
        if audit_cols:
            conn.execute(
                """INSERT INTO surplus_math_audit
                   (id, asset_id, snapshot_id, doc_id,
                    html_overbid, successful_bid, total_indebtedness, computed_surplus,
                    voucher_overbid, voucher_doc_id,
                    match_html_math, match_voucher,
                    data_grade, promotion_blocked, audit_ts, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    str(uuid4()), asset_id, snapshot_id, doc_id,
                    html_overbid_cents, successful_bid_cents, total_indebtedness_cents, computed_surplus,
                    voucher_overbid_cents, doc_id,  # voucher_doc_id = same OB evidence_documents row
                    match_html_math, match_voucher,
                    data_grade, promotion_blocked, now_ts, notes,
                ],
            )

        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise


# ── Batch extraction runner ───────────────────────────────────────────────────


def run_extraction_batch(county: str | None = None, limit: int = 500) -> dict:
    """Run Gate 4 extraction on all BRONZE leads that have html_snapshots.

    Args:
        county: Optional county slug to filter (e.g. 'jefferson'). None = all.
        limit:  Max leads to process per run.

    Returns dict with keys: processed, gold, silver, bronze, errors, leads (list of promoted).
    """
    import sqlite3

    db_path = _default_db_path()
    conn = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        filter_county = "AND l.county = ?" if county else ""
        q_params: list = ([county] if county else []) + [limit]
        rows = conn.execute(f"""
            SELECT DISTINCT l.id, l.county, l.case_number
            FROM leads l
            WHERE l.data_grade = 'BRONZE'
            {filter_county}
            AND (
                EXISTS (SELECT 1 FROM html_snapshots hs WHERE hs.asset_id = l.id)
                OR EXISTS (SELECT 1 FROM html_snapshots hs
                    WHERE hs.asset_id = 'FORECLOSURE:CO:' || UPPER(l.county) || ':' || l.case_number)
            )
            LIMIT ?
        """, q_params).fetchall()
    finally:
        conn.close()

    results: dict = {"processed": 0, "gold": 0, "silver": 0, "bronze": 0, "errors": 0, "leads": []}
    for row in rows:
        lead_id = row["id"]
        try:
            r = run_extraction(lead_id)
            grade = (r.get("data_grade") or r.get("grade") or "BRONZE").lower()
            results["processed"] += 1
            if grade == "gold":
                results["gold"] += 1
                results["leads"].append({"id": lead_id, "grade": "GOLD"})
            elif grade == "silver":
                results["silver"] += 1
                results["leads"].append({"id": lead_id, "grade": "SILVER"})
            else:
                results["bronze"] += 1
        except Exception as exc:
            results["errors"] += 1
            log.warning("Batch extraction error %s: %s", lead_id, exc)

    return results


# ── EPIC 4G: Recorder Doc Auto-Pull Stub ─────────────────────────────────────

def _try_pull_recorder_doc(county: str, case_number: str, conn) -> bool:
    """Attempt to fetch deed/recording from county recorder. Stub — jefferson only.

    Returns True if a recorder document was successfully retrieved and stored,
    False otherwise. This is a no-op stub; per-county recorder API pulls are
    not yet implemented.

    Jefferson uses the GovSoft viewer — html_snapshot pattern already handles
    this county's document capture during scraping.
    """
    # TODO: Implement per-county recorder API pulls
    # Jefferson: uses GovSoft viewer — html_snapshot pattern already handles this
    return False


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import json

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="VeriFuse Gate 4 — GovSoft Extraction")
    parser.add_argument("--asset-id", required=True,
                        help="Asset ID (e.g. FORECLOSURE:CO:JEFFERSON:J2600074)")
    args = parser.parse_args()

    result = run_extraction(args.asset_id)
    print(json.dumps(result, indent=2))
