"""
VeriFuse vNEXT Gate 5 — Hybrid OCR Processor
============================================
Async processor that extracts labeled financial field values with bounding boxes
from financial evidence_documents stored in the vault.

Architecture (Option B — decoupled from crawl loop):
  - Standalone module; NEVER imported inside govsoft_engine.py
  - Queries DB for financial evidence_documents (doc_family IN 'OB','BID','COP','CERTQH')
    belonging to PENDING/EXTRACTED/NEEDS_REVIEW assets that have no field_evidence rows yet
  - Writes ONLY to field_evidence — does NOT mutate asset_registry, leads, or extraction_events

Doc-family targeting (cost guard):
  - Only processes doc_family IN ('OB', 'BID', 'COP', 'CERTQH')
  - Never submits NED, NOTICE, INVOICE, or OTHER docs to pdfplumber or Document AI
  - Prevents unnecessary Google Document AI billing charges

State mutation policy (STRICT — Gate 5):
  - Gate 5 writes ONLY to field_evidence.
  - No changes to processing_status, data_grade, extraction_events, or leads.
  - Post-OCR validation promotion is handled by a dedicated promotion job (Gate 6+),
    NOT by this module. The promote_after_ocr= flag exists for future use, defaults OFF.

OCR strategy:
  - pdfplumber primary (text-layer PDF extraction)
  - Google Document AI FORM_PARSER fallback (scanned / no-text-layer / low-confidence)

TIFF handling:
  - Pillow converts TIFF → temporary PDF → pdfplumber attempt
  - If conversion fails or no text layer, original TIFF sent to Document AI as image

Idempotency:
  - field_evidence.id = sha256(doc_id + ":" + field_name + ":" + str(page_number))[:32]
  - INSERT OR IGNORE — safe to re-run; row count never increases on repeat runs

Thread safety (asyncio.to_thread):
  - run_ocr_queue_async() creates a FRESH SQLite connection INSIDE the worker thread.
  - No connection object is ever shared across threads.
  - All DB work happens on a single connection within the thread; no concurrent writes
    from this module on the same connection.

page_number convention: 1-based (pdfplumber 0-based page index + 1)
Bounding boxes (norm_x1/y1/x2/y2): normalized to [0, 1] of page dimensions

Canonical field_name values (strict — 3 values only):
  "overbid_amount"     — all overbid/surplus/excess-proceeds/funds-available labels
  "successful_bid"     — winning bid at sale
  "total_indebtedness" — total debt / judgment

These 3 values are the only strings inserted into field_evidence.field_name.
Gate 4 govsoft_extract.py lookups use field_name = 'overbid_amount' exclusively.

Graceful degradation:
  - GOOGLE_APPLICATION_CREDENTIALS absent → log.warning, return [], no crash
  - GOOGLE_CLOUD_PROJECT or DOCAI_FORM_PARSER_ID absent → log.warning, return [], no crash
  - google-cloud-documentai not installed → log.warning, return [], no crash
  - Pillow import failure → TIFF sent directly to Document AI as image
  - Any API error → log.warning, return [], no crash

Usage:
  # Queue mode — all pending financial docs, up to --limit:
  python -m verifuse_v2.ingest.ocr_processor --limit 50

  # Single asset:
  python -m verifuse_v2.ingest.ocr_processor --asset-id FORECLOSURE:CO:JEFFERSON:J2400300
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import sqlite3
import tempfile
import time
from pathlib import Path

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# Only financial voucher doc families are processed.
# NED, NOTICE, INVOICE, OTHER are explicitly excluded to avoid wasted OCR billing.
_OCR_TARGET_DOC_FAMILIES = frozenset({"OB", "BID", "COP", "CERTQH"})

# Confidence threshold: pdfplumber fields below this trigger Document AI fallback
_CONFIDENCE_THRESHOLD = 0.80

# Minimum words per page to consider a text layer usable
_MIN_WORDS_TEXT_LAYER = 10

# ── Canonical field_name values (strict — 3 values, no others inserted) ──────
#
# ALL labels are mapped to one of exactly these three strings:
#   "overbid_amount"     — overbid / surplus / excess proceeds / funds available
#   "successful_bid"     — winning bid at sale
#   "total_indebtedness" — total debt / total indebtedness
#
# This set is the ONLY valid output for field_evidence.field_name from Gate 5.
# Gate 4 govsoft_extract.py field_evidence lookup uses field_name = 'overbid_amount'.
#
_FIELD_OVERBID     = "overbid_amount"
_FIELD_BID         = "successful_bid"
_FIELD_INDEBTEDNESS = "total_indebtedness"

# Target label patterns → canonical field_name (3 values only, order is significant)
_TARGET_LABELS: list[tuple[re.Pattern, str]] = [
    # ── overbid_amount ────────────────────────────────────────────────────────
    (re.compile(r"overbid\s+at\s+sale",        re.I), _FIELD_OVERBID),
    (re.compile(r"overbid\s+amount",            re.I), _FIELD_OVERBID),
    (re.compile(r"overbid\s+transferred",       re.I), _FIELD_OVERBID),
    (re.compile(r"funds\s+available",           re.I), _FIELD_OVERBID),
    (re.compile(r"surplus\s+proceeds",          re.I), _FIELD_OVERBID),
    (re.compile(r"excess\s+proceeds",           re.I), _FIELD_OVERBID),
    (re.compile(r"\bsurplus\s*:",               re.I), _FIELD_OVERBID),
    # Generic "Overbid:" label — colon REQUIRED to avoid matching doc headers/titles
    # (e.g. "CERTIFICATE OF PURCHASE / OVERBID CLAIM" must NOT match here)
    (re.compile(r"\boverbid\s*:",               re.I), _FIELD_OVERBID),
    # ── successful_bid ────────────────────────────────────────────────────────
    (re.compile(r"successful\s+bid(\s+at\s+sale)?", re.I), _FIELD_BID),
    # ── total_indebtedness ────────────────────────────────────────────────────
    (re.compile(r"total\s+indebtedness",        re.I), _FIELD_INDEBTEDNESS),
    (re.compile(r"total\s+debt\b",              re.I), _FIELD_INDEBTEDNESS),
    (re.compile(r"judgment\s+amount",           re.I), _FIELD_INDEBTEDNESS),
]

# Currency value pattern — matches $1,234.56 and variants
_CURRENCY_RE = re.compile(r"\$\s*[\d,]+\.?\d{0,2}")


# ── DB path ───────────────────────────────────────────────────────────────────

def _default_db_path() -> str:
    return os.getenv(
        "VERIFUSE_DB_PATH",
        str(Path(__file__).resolve().parent.parent / "data" / "verifuse_v2.db"),
    )


# ── Stable, idempotent field_evidence ID ─────────────────────────────────────

def _make_field_id(doc_id: str, field_name: str, page_number: int) -> str:
    """sha256(doc_id:field_name:page_number)[:32] — deterministic, collision-resistant.

    Guarantees that re-running OCR on the same document produces the same IDs,
    so INSERT OR IGNORE correctly suppresses duplicates.
    """
    raw = f"{doc_id}:{field_name}:{page_number}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ── Label matching ────────────────────────────────────────────────────────────

def _match_target_label(text: str) -> str | None:
    """Return canonical field_name (one of 3 strict values) if text matches, else None."""
    for pattern, field_name in _TARGET_LABELS:
        if pattern.search(text):
            return field_name
    return None


# ── pdfplumber line grouping ──────────────────────────────────────────────────

def _group_words_into_lines(
    words: list[dict], y_tolerance: float = 3.0
) -> list[list[dict]]:
    """Group pdfplumber extract_words() output into text lines by vertical proximity.

    Words within y_tolerance points of each other on the y-axis share a line.
    Lines are returned in top-to-bottom, left-to-right order.
    """
    if not words:
        return []
    sorted_words = sorted(words, key=lambda w: (w["top"], w["x0"]))
    lines: list[list[dict]] = []
    current_line = [sorted_words[0]]
    current_top = sorted_words[0]["top"]
    for word in sorted_words[1:]:
        if abs(word["top"] - current_top) <= y_tolerance:
            current_line.append(word)
        else:
            lines.append(current_line)
            current_line = [word]
            current_top = word["top"]
    lines.append(current_line)
    return lines


def _line_text(line: list[dict]) -> str:
    return " ".join(w["text"] for w in line)


def _extract_currency_from_line(line: list[dict]) -> tuple[str | None, dict | None]:
    """Find the first currency value in a line; return (value_str, bbox) or (None, None)."""
    full_text = _line_text(line)
    m = _CURRENCY_RE.search(full_text)
    if not m:
        return None, None
    # Prefer the specific word containing the currency symbol
    for word in line:
        if _CURRENCY_RE.search(word["text"]):
            return word["text"], {
                "x0": word["x0"], "top": word["top"],
                "x1": word["x1"], "bottom": word["bottom"],
            }
    # Fallback: bounding box of the whole line
    return m.group(0), {
        "x0":     min(w["x0"] for w in line),
        "top":    min(w["top"] for w in line),
        "x1":     max(w["x1"] for w in line),
        "bottom": max(w["bottom"] for w in line),
    }


# ── pdfplumber primary extraction ─────────────────────────────────────────────

def extract_with_pdfplumber(
    file_path: Path, doc_family: str = "BID"
) -> tuple[list[dict], bool]:
    """Extract labeled financial fields from a PDF using pdfplumber text-layer.

    Returns (fields, has_text_layer):
      - fields: list of field dicts ready for field_evidence INSERT
      - has_text_layer: True if total words across all pages >= _MIN_WORDS_TEXT_LAYER

    Each field dict:
      field_name (one of 3 canonical values), extracted_value, confidence,
      norm_x1/y1/x2/y2 (normalized [0,1]), page_number (1-based), ocr_source='pdfplumber'

    Near-empty pages (< _MIN_WORDS_TEXT_LAYER words) are skipped — Document AI handles them.
    Text-layer pages get confidence=0.95; empty/near-empty get confidence=0.30.
    """
    try:
        import pdfplumber  # type: ignore[import]
    except ImportError:
        log.error("[pdfplumber] pdfplumber not installed — cannot extract text layer")
        return [], False

    fields: list[dict] = []
    total_words = 0

    try:
        with pdfplumber.open(str(file_path)) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                page_number = page_idx + 1  # 1-based
                words = page.extract_words()
                page_word_count = len(words)
                total_words += page_word_count

                if page_word_count < _MIN_WORDS_TEXT_LAYER:
                    log.debug(
                        "[pdfplumber] %s pg%d: %d words — below threshold, skipping",
                        file_path.name, page_number, page_word_count,
                    )
                    continue

                page_w = float(page.width) if page.width else 1.0
                page_h = float(page.height) if page.height else 1.0

                lines = _group_words_into_lines(words)
                for line_idx, line in enumerate(lines):
                    lt = _line_text(line)
                    field_name = _match_target_label(lt)
                    if field_name is None:
                        continue

                    # Currency on same line takes priority; fall to next line if not found
                    value_str, value_bbox = _extract_currency_from_line(line)
                    if value_str is None and line_idx + 1 < len(lines):
                        value_str, value_bbox = _extract_currency_from_line(
                            lines[line_idx + 1]
                        )

                    if value_str is None:
                        log.debug(
                            "[pdfplumber] %s pg%d: label %r — no currency nearby",
                            file_path.name, page_number, lt[:50],
                        )
                        continue

                    # value_bbox guaranteed non-None when value_str is non-None
                    assert value_bbox is not None
                    fields.append({
                        "field_name":      field_name,
                        "extracted_value": value_str,
                        "confidence":      0.95,
                        "norm_x1":         value_bbox["x0"] / page_w,
                        "norm_y1":         value_bbox["top"] / page_h,
                        "norm_x2":         value_bbox["x1"] / page_w,
                        "norm_y2":         value_bbox["bottom"] / page_h,
                        "page_number":     page_number,
                        "ocr_source":      "pdfplumber",
                    })

    except Exception as exc:
        log.warning("[pdfplumber] Error processing %s: %s", file_path, exc)
        return [], False

    has_text_layer = total_words >= _MIN_WORDS_TEXT_LAYER
    log.info(
        "[pdfplumber] %s: %d words, has_text_layer=%s, %d fields found",
        file_path.name, total_words, has_text_layer, len(fields),
    )
    return fields, has_text_layer


# ── TIFF → PDF conversion ─────────────────────────────────────────────────────

def _convert_tiff_to_pdf(tiff_path: Path) -> Path | None:
    """Convert a TIFF image to a temporary PDF using Pillow.

    Returns temp PDF Path (caller must delete), or None on failure.
    Failure is non-fatal — caller falls back to Document AI with original TIFF.
    """
    try:
        from PIL import Image  # type: ignore[import]
    except ImportError:
        log.warning(
            "[tiff] Pillow not installed — TIFF→PDF conversion unavailable; "
            "will send original TIFF to Document AI"
        )
        return None

    try:
        img = Image.open(str(tiff_path))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp.close()
        tmp_path = Path(tmp.name)
        img.save(str(tmp_path), format="PDF", save_all=True)
        log.info("[tiff] Converted %s → temp PDF %s", tiff_path.name, tmp_path.name)
        return tmp_path
    except Exception as exc:
        log.warning("[tiff] TIFF→PDF conversion failed for %s: %s", tiff_path, exc)
        return None


# ── Vertex AI Gemini 1.5 Flash extraction (primary cloud OCR) ────────────────

def extract_with_gemini(file_path: Path, content_type: str) -> list[dict]:
    """Extract labeled financial fields via Vertex AI Gemini 1.5 Flash.

    Graceful degradation — returns [] without crashing when:
      - VERTEX_AI_PROJECT not set (falls through to FORM_PARSER)
      - google-cloud-aiplatform not installed
      - Any API error (quota, network failure, malformed response)

    Required env vars:
      VERTEX_AI_PROJECT  — GCP project ID (e.g. canvas-sum-481614-f6)
      GEMINI_MODEL       — model ID (default: gemini-1.5-flash-002)
      GOOGLE_APPLICATION_CREDENTIALS — path to service account JSON

    Force JSON output with strict schema:
      { overbid_amount: str|null, successful_bid: str|null, total_indebtedness: str|null }

    Returns list of field dicts compatible with _insert_field_evidence().
    page_number is always 1 (Gemini processes whole document, not per-page).
    """
    project_id = os.getenv("VERTEX_AI_PROJECT", "")
    model_id = os.getenv("GEMINI_MODEL", "gemini-1.5-flash-002")
    location = os.getenv("VERTEX_AI_LOCATION", "us-central1")

    if not project_id:
        log.debug(
            "[gemini] VERTEX_AI_PROJECT not set — skipping Gemini OCR"
        )
        return []

    try:
        import vertexai  # type: ignore[import]
        from vertexai.generative_models import GenerativeModel, Part, GenerationConfig  # type: ignore[import]
    except ImportError:
        log.warning(
            "[gemini] google-cloud-aiplatform not installed — skipping Gemini OCR. "
            "pip install google-cloud-aiplatform"
        )
        return []

    try:
        vertexai.init(project=project_id, location=location)
        model = GenerativeModel(model_id)

        file_bytes = file_path.read_bytes()

        # Determine MIME type for inline data
        mime = content_type or "application/pdf"

        prompt = (
            "You are a financial document extractor for Colorado foreclosure surplus cases. "
            "Extract exactly these three fields from the document and return ONLY a JSON object:\n"
            '  "overbid_amount"     — the overbid/surplus/excess proceeds amount (e.g. "$12,345.67")\n'
            '  "successful_bid"     — the winning bid amount at sale\n'
            '  "total_indebtedness" — total debt / total indebtedness / judgment amount\n\n'
            "Return null for any field not found. Return only the JSON, no other text.\n"
            "Example: "
            '{"overbid_amount": "$12,345.67", "successful_bid": "$210,000.00", "total_indebtedness": "$197,654.33"}'
        )

        doc_part = Part.from_data(data=file_bytes, mime_type=mime)
        generation_config = GenerationConfig(
            response_mime_type="application/json",
            temperature=0.0,
            max_output_tokens=256,
        )

        response = model.generate_content(
            [doc_part, prompt],
            generation_config=generation_config,
        )

        import json as _json
        import re as _re
        raw_text = response.text.strip()

        # Strip markdown fences the model may include despite response_mime_type
        if raw_text.startswith("```"):
            raw_text = _re.sub(r"^```(?:json)?\s*", "", raw_text)
            raw_text = _re.sub(r"\s*```\s*$", "", raw_text).strip()

        extracted = _json.loads(raw_text)

    except Exception as exc:
        log.warning("[gemini] Gemini API error for %s: %s", file_path.name, exc)
        return []

    # Map extracted JSON → canonical field dicts
    # NOTE: confidence is set to 0.0 — Gemini does not return per-field confidence scores.
    # ocr_source="gemini_unverified" signals that these values require cross-validation
    # (pdfplumber parse or human review) before they can promote a lead to GOLD.
    FIELD_MAP = {
        "overbid_amount":     _FIELD_OVERBID,
        "successful_bid":     _FIELD_BID,
        "total_indebtedness": _FIELD_INDEBTEDNESS,
    }

    fields: list[dict] = []
    for json_key, canonical_name in FIELD_MAP.items():
        value = extracted.get(json_key)
        if not value:
            continue
        # Verify it looks like a currency string
        if not _CURRENCY_RE.search(str(value)):
            log.debug("[gemini] Skipping non-currency value for %s: %r", json_key, value)
            continue
        fields.append({
            "field_name":      canonical_name,
            "extracted_value": str(value).strip(),
            "confidence":      0.0,   # Model does not return confidence — do not invent one
            "norm_x1":         0.0,
            "norm_y1":         0.0,
            "norm_x2":         1.0,
            "norm_y2":         1.0,
            "page_number":     1,
            "ocr_source":      "gemini_unverified",  # Requires validation before GOLD promotion
        })

    log.info(
        "[gemini] %s: %d fields extracted (model=%s)",
        file_path.name, len(fields), model_id,
    )
    return fields


# ── Google Document AI FORM_PARSER fallback ───────────────────────────────────

def extract_with_document_ai(file_path: Path, content_type: str) -> list[dict]:
    """Extract labeled fields via Google Document AI FORM_PARSER processor.

    Graceful degradation — returns [] without crashing when:
      - GOOGLE_APPLICATION_CREDENTIALS not set
      - GOOGLE_CLOUD_PROJECT or DOCAI_FORM_PARSER_ID absent
      - google-cloud-documentai package not installed
      - Any API error (timeout, quota, network failure)

    Required env vars:
      GOOGLE_APPLICATION_CREDENTIALS — path to service account JSON
      GOOGLE_CLOUD_PROJECT           — GCP project ID
      DOCAI_FORM_PARSER_ID           — Document AI processor ID
      DOCAI_LOCATION                 — processor region (default: "us")

    page_number is 1-based. Bounding boxes normalized to [0, 1].
    field_name output is strictly limited to the 3 canonical values.
    """
    creds_path   = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    project_id   = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    processor_id = os.getenv("DOCAI_FORM_PARSER_ID", "")
    location     = os.getenv("DOCAI_LOCATION", "us")

    if not creds_path:
        log.warning(
            "[docai] GOOGLE_APPLICATION_CREDENTIALS not set — skipping Document AI fallback"
        )
        return []

    if not project_id or not processor_id:
        log.warning(
            "[docai] GOOGLE_CLOUD_PROJECT or DOCAI_FORM_PARSER_ID not configured — "
            "skipping Document AI fallback"
        )
        return []

    try:
        from google.cloud import documentai_v1 as documentai  # type: ignore[import]
    except ImportError:
        log.warning(
            "[docai] google-cloud-documentai not installed — skipping Document AI fallback"
        )
        return []

    try:
        client = documentai.DocumentProcessorServiceClient()
        processor_name = (
            f"projects/{project_id}/locations/{location}/processors/{processor_id}"
        )
        file_bytes = file_path.read_bytes()
        raw_doc = documentai.RawDocument(content=file_bytes, mime_type=content_type)
        request = documentai.ProcessRequest(name=processor_name, raw_document=raw_doc)
        result = client.process_document(request=request)
        document = result.document

        fields: list[dict] = []
        for page_idx, page in enumerate(document.pages):
            page_number = page_idx + 1  # 1-based
            for form_field in page.form_fields:
                label_text = (
                    form_field.field_name.text_anchor.content
                    if form_field.field_name.text_anchor.content else ""
                ).strip()
                value_text = (
                    form_field.field_value.text_anchor.content
                    if form_field.field_value.text_anchor.content else ""
                ).strip()

                # Strict canonical mapping — only 3 output values
                field_name = _match_target_label(label_text)
                if field_name is None:
                    continue

                confidence = float(form_field.field_value.confidence or 0.0)

                layout = form_field.field_value.layout
                if layout.bounding_poly.normalized_vertices:
                    verts = layout.bounding_poly.normalized_vertices
                    xs = [v.x for v in verts]
                    ys = [v.y for v in verts]
                    norm_x1, norm_y1 = min(xs), min(ys)
                    norm_x2, norm_y2 = max(xs), max(ys)
                else:
                    norm_x1 = norm_y1 = norm_x2 = norm_y2 = 0.0

                fields.append({
                    "field_name":      field_name,
                    "extracted_value": value_text,
                    "confidence":      confidence,
                    "norm_x1":         norm_x1,
                    "norm_y1":         norm_y1,
                    "norm_x2":         norm_x2,
                    "norm_y2":         norm_y2,
                    "page_number":     page_number,
                    "ocr_source":      "document_ai",
                })

        log.info(
            "[docai] %s: %d fields extracted", file_path.name, len(fields)
        )
        return fields

    except Exception as exc:
        log.warning("[docai] Document AI error for %s: %s", file_path, exc)
        return []


# ── field_evidence INSERT (idempotent) ────────────────────────────────────────

def _insert_field_evidence(
    conn: sqlite3.Connection, doc_id: str, fields: list[dict]
) -> int:
    """INSERT OR IGNORE field_evidence rows. Returns count of NEW rows inserted.

    Uses a single BEGIN IMMEDIATE transaction for atomicity.
    Stable sha256-based IDs guarantee re-runs insert 0 new rows (idempotent).
    """
    if not fields:
        return 0

    now_ts = int(time.time())
    inserted = 0

    conn.execute("BEGIN IMMEDIATE")
    try:
        for f in fields:
            fid = _make_field_id(doc_id, f["field_name"], f["page_number"])
            result = conn.execute(
                """INSERT OR IGNORE INTO field_evidence
                   (id, evidence_doc_id, field_name, extracted_value, confidence,
                    norm_x1, norm_y1, norm_x2, norm_y2, page_number, ocr_source, created_ts)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    fid, doc_id,
                    f["field_name"], f["extracted_value"], f["confidence"],
                    f.get("norm_x1", 0.0), f.get("norm_y1", 0.0),
                    f.get("norm_x2", 0.0), f.get("norm_y2", 0.0),
                    f["page_number"], f["ocr_source"],
                    now_ts,
                ],
            )
            inserted += result.rowcount
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise

    return inserted


# ── Per-document processor ────────────────────────────────────────────────────

def process_doc(doc_row: sqlite3.Row, conn: sqlite3.Connection) -> dict:
    """Run the OCR pipeline for a single evidence_document row.

    ONLY processes doc_family IN ('OB', 'BID', 'COP', 'CERTQH').
    All other doc families are skipped immediately (cost guard).

    ONLY writes to field_evidence — no asset_registry, leads, or extraction_events mutations.

    Pipeline:
      1. pdfplumber primary (text-layer PDFs)
      2. Document AI fallback (scanned, TIFF, no text layer, low confidence)

    Returns dict: {doc_id, file_path, doc_family, status, fields_extracted, rows_inserted, notes}
    """
    doc_id        = doc_row["id"]
    file_path_str = doc_row["file_path"]
    content_type  = doc_row["content_type"] or "application/pdf"
    doc_family    = doc_row["doc_family"]

    result: dict = {
        "doc_id":           doc_id,
        "file_path":        file_path_str,
        "doc_family":       doc_family,
        "status":           "skipped",
        "fields_extracted": 0,
        "rows_inserted":    0,
        "notes":            "",
    }

    # Cost guard — skip non-financial doc families
    if doc_family not in _OCR_TARGET_DOC_FAMILIES:
        result["notes"] = f"doc_family={doc_family!r} not in OCR target set — skipped"
        log.debug("[ocr] Skipping %s (doc_family=%s)", file_path_str, doc_family)
        return result

    file_path = Path(file_path_str)
    if not file_path.exists():
        result["status"] = "file_missing"
        result["notes"]  = f"File not found: {file_path_str}"
        log.warning("[ocr] File not found: %s", file_path_str)
        return result

    is_tiff = (
        content_type in ("image/tiff", "image/tif")
        or file_path.suffix.lower() in (".tif", ".tiff")
    )
    tmp_pdf: Path | None = None

    try:
        # ── TIFF: convert to temp PDF for pdfplumber ──────────────────────────
        if is_tiff:
            tmp_pdf = _convert_tiff_to_pdf(file_path)
            plumber_path = tmp_pdf if tmp_pdf else file_path
        else:
            plumber_path = file_path

        # ── pdfplumber primary ────────────────────────────────────────────────
        plumber_fields, has_text_layer = extract_with_pdfplumber(plumber_path, doc_family)

        all_high_confidence = (
            all(f["confidence"] >= _CONFIDENCE_THRESHOLD for f in plumber_fields)
            if plumber_fields else False
        )

        # Fall to Document AI when no usable text layer, no fields found, or low confidence
        use_document_ai = (
            not has_text_layer
            or not plumber_fields
            or not all_high_confidence
        )

        if use_document_ai:
            log.info(
                "[ocr] %s: cloud OCR fallback "
                "(has_text_layer=%s, plumber_fields=%d, all_high_conf=%s)",
                file_path.name, has_text_layer, len(plumber_fields), all_high_confidence,
            )
            # TIFF → send original; PDF → send the plumber path
            cloud_path = file_path if is_tiff else plumber_path

            # Try Gemini 1.5 Flash first (VERTEX_AI_PROJECT env var required)
            cloud_fields = extract_with_gemini(cloud_path, content_type)

            # Fallback to Document AI FORM_PARSER if Gemini not configured or failed
            if not cloud_fields:
                cloud_fields = extract_with_document_ai(cloud_path, content_type)

            # Prefer cloud OCR; fall back to pdfplumber if cloud gracefully degraded
            final_fields = cloud_fields if cloud_fields else plumber_fields
            if not final_fields:
                result["notes"] = (
                    "Cloud OCR unavailable (no Vertex AI or Document AI creds/config); "
                    "no text layer — 0 fields extracted"
                )
        else:
            final_fields = plumber_fields

        result["fields_extracted"] = len(final_fields)

        # ── INSERT field_evidence — ONLY state mutation in Gate 5 ─────────────
        rows = _insert_field_evidence(conn, doc_id, final_fields)
        result["rows_inserted"] = rows
        result["status"] = "processed"
        log.info(
            "[ocr] %s (family=%s): %d fields → %d new field_evidence rows",
            file_path.name, doc_family, len(final_fields), rows,
        )

    except Exception as exc:
        log.exception("[ocr] process_doc failed for doc_id=%s: %s", doc_id, exc)
        result["status"] = "error"
        result["notes"]  = str(exc)

    finally:
        if tmp_pdf and tmp_pdf.exists():
            try:
                tmp_pdf.unlink()
            except Exception:
                pass

    return result


# ── OCR queue runner ──────────────────────────────────────────────────────────

def run_ocr_queue(conn: sqlite3.Connection, limit: int = 100) -> dict:
    """Query DB for unprocessed financial evidence_documents and run OCR on each.

    Selects evidence_documents where:
      - doc_family IN ('OB', 'BID', 'COP', 'CERTQH')  ← cost guard at SQL level
      - Parent asset processing_status IN ('PENDING', 'EXTRACTED', 'NEEDS_REVIEW')
      - No field_evidence rows exist for this doc yet

    ONLY writes to field_evidence. No mutations to asset_registry, leads, or
    extraction_events. Post-OCR validation promotion is handled by a separate job.
    """
    docs = conn.execute(
        """
        SELECT ed.id, ed.asset_id, ed.file_path, ed.content_type, ed.doc_family
        FROM evidence_documents ed
        JOIN asset_registry ar ON ar.asset_id = ed.asset_id
        WHERE ed.doc_family IN ('OB', 'BID', 'COP', 'CERTQH')
          AND ar.processing_status IN ('PENDING', 'EXTRACTED', 'NEEDS_REVIEW')
          AND NOT EXISTS (
              SELECT 1 FROM field_evidence fe WHERE fe.evidence_doc_id = ed.id
          )
        ORDER BY ed.asset_id, ed.doc_family
        LIMIT ?
        """,
        [limit],
    ).fetchall()

    if not docs:
        log.info("[ocr_queue] No unprocessed financial docs found")
        return {"assets_processed": 0, "docs_processed": 0, "rows_inserted": 0}

    log.info("[ocr_queue] %d financial docs to process", len(docs))

    total_assets: set[str] = set()
    total_docs   = 0
    total_rows   = 0

    for doc_row in docs:
        r = process_doc(doc_row, conn)
        total_docs += 1
        total_rows += r.get("rows_inserted", 0)
        total_assets.add(doc_row["asset_id"])

    summary = {
        "assets_processed": len(total_assets),
        "docs_processed":   total_docs,
        "rows_inserted":    total_rows,
    }
    log.info("[ocr_queue] Complete: %s", summary)
    return summary


# ── Async wrapper ─────────────────────────────────────────────────────────────

async def run_ocr_queue_async(
    db_path: str | None = None, limit: int = 100
) -> dict:
    """Async wrapper: runs the sync OCR queue in a thread pool via asyncio.to_thread.

    Thread safety: a FRESH SQLite connection is opened INSIDE the worker thread.
    No connection object is shared between the calling thread and the worker thread.
    All DB reads and writes for this invocation happen on that single connection
    within the worker thread — no concurrent SQLite access from this async wrapper.
    """
    path = db_path or _default_db_path()

    def _run() -> dict:
        # New connection created inside the thread — not shared with caller
        conn = sqlite3.connect(path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            return run_ocr_queue(conn, limit=limit)
        finally:
            conn.close()

    return await asyncio.to_thread(_run)


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import json

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="VeriFuse Gate 5 — Hybrid OCR Processor"
    )
    parser.add_argument(
        "--asset-id",
        help="Process a single asset (e.g. FORECLOSURE:CO:JEFFERSON:J2400300)",
    )
    parser.add_argument(
        "--limit", type=int, default=100,
        help="Max financial evidence_documents to process in queue mode (default: 100)",
    )
    args = parser.parse_args()

    db_path = _default_db_path()
    conn = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")

    try:
        if args.asset_id:
            # Single-asset mode: process all financial docs for this asset
            doc_rows = conn.execute(
                """SELECT id, file_path, content_type, doc_family
                   FROM evidence_documents
                   WHERE asset_id = ?
                     AND doc_family IN ('OB', 'BID', 'COP', 'CERTQH')""",
                [args.asset_id],
            ).fetchall()
            if not doc_rows:
                log.warning(
                    "No financial docs (OB/BID/COP/CERTQH) found for asset %s",
                    args.asset_id,
                )
                output: dict = {
                    "asset_id":    args.asset_id,
                    "docs_found":  0,
                    "status":      "no_financial_docs",
                }
            else:
                results = [process_doc(row, conn) for row in doc_rows]
                output = {
                    "asset_id":            args.asset_id,
                    "docs_processed":      len(results),
                    "total_rows_inserted": sum(r.get("rows_inserted", 0) for r in results),
                    "doc_results":         results,
                }
        else:
            output = run_ocr_queue(conn, limit=args.limit)

        print(json.dumps(output, indent=2, default=str))
    finally:
        conn.close()
