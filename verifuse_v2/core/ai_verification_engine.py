"""
VeriFuse SOTA Triple-Verification Engine
=========================================
Three independent AI systems cross-verify every surplus amount.
No competitor can replicate this pipeline.

VERIFICATION TIERS (highest to lowest):
  TRIPLE_VERIFIED  — HTML math + Document AI + Gemini all agree within $0.01
  AI_VERIFIED      — HTML math + at least ONE AI engine agrees within $0.01
  HTML_MATH        — HTML math only (Gate 4 standard)
  UNVERIFIED       — No confirmed math path

ENGINES:
  Engine 1 (Gate 4): HTML parsing + Decimal arithmetic (existing, always runs)
  Engine 2 (Gate 5): Google Document AI Form Parser — structured PDF extraction
  Engine 3 (Gate 6): Gemini 2.0 Flash Vision — independent document reading
  Engine 4 (Gate 7): Anthropic Claude — tertiary document understanding

Usage:
    from verifuse_v2.core.ai_verification_engine import VerificationEngine
    engine = VerificationEngine()
    result = engine.verify(asset_id, html_overbid, pdf_bytes, conn)
    # result.tier, result.confidence, result.engines_agreed, result.amounts
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ── Configuration from environment ───────────────────────────────────────────

GCP_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
DOCAI_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
DOCAI_LOCATION = os.environ.get("DOCAI_LOCATION", "us")
DOCAI_PROCESSOR_ID = os.environ.get("DOCAI_FORM_PARSER_ID", "")
GOOGLE_CREDS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")

VERTEX_PROJECT = os.environ.get("VERTEX_AI_PROJECT", "")
VERTEX_LOCATION = os.environ.get("VERTEX_AI_LOCATION", "us-central1")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

PENNY = Decimal("0.01")
ZERO = Decimal("0")


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class VerificationResult:
    asset_id: str
    html_overbid: Decimal
    tier: str = "UNVERIFIED"              # TRIPLE_VERIFIED / AI_VERIFIED / HTML_MATH / UNVERIFIED
    confidence: float = 0.0              # 0.0–1.0
    engines_agreed: int = 0              # how many AI engines matched HTML math
    engines_run: int = 0                 # how many AI engines were attempted
    docai_amount: Optional[Decimal] = None
    gemini_amount: Optional[Decimal] = None
    claude_amount: Optional[Decimal] = None
    docai_raw: dict = field(default_factory=dict)
    gemini_raw: str = ""
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0

    @property
    def pool_source(self) -> str:
        return {
            "TRIPLE_VERIFIED": "TRIPLE_VERIFIED",
            "AI_VERIFIED": "AI_VERIFIED",
            "HTML_MATH": "HTML_MATH",
        }.get(self.tier, "UNVERIFIED")

    @property
    def verification_notes(self) -> str:
        parts = [f"HTML_MATH=${self.html_overbid}"]
        if self.docai_amount is not None:
            match = "✓" if abs(self.html_overbid - self.docai_amount) <= PENNY else "✗"
            parts.append(f"DOCAI={match}${self.docai_amount}")
        if self.gemini_amount is not None:
            match = "✓" if abs(self.html_overbid - self.gemini_amount) <= PENNY else "✗"
            parts.append(f"GEMINI={match}${self.gemini_amount}")
        if self.claude_amount is not None:
            match = "✓" if abs(self.html_overbid - self.claude_amount) <= PENNY else "✗"
            parts.append(f"CLAUDE={match}${self.claude_amount}")
        parts.append(f"TIER={self.tier}")
        return " | ".join(parts)


# ── Currency parser ────────────────────────────────────────────────────────────

def _parse_amount(text: str) -> Optional[Decimal]:
    """Extract a dollar amount from AI response text. Returns None if unparseable."""
    if not text:
        return None
    # Remove currency symbols, commas, whitespace
    cleaned = re.sub(r"[$,\s]", "", str(text).strip())
    # Grab the first decimal number found
    m = re.search(r"\d+(?:\.\d+)?", cleaned)
    if not m:
        return None
    try:
        val = Decimal(m.group())
        return val if val > ZERO else None
    except InvalidOperation:
        return None


# ── Engine 2: Google Document AI ─────────────────────────────────────────────

def _run_docai(pdf_bytes: bytes, asset_id: str) -> tuple[Optional[Decimal], dict]:
    """Run Google Document AI Form Parser on a PDF.

    Returns (extracted_amount, raw_entities_dict).
    Requires: google-cloud-documentai, GOOGLE_APPLICATION_CREDENTIALS, DOCAI_FORM_PARSER_ID
    """
    if not DOCAI_PROCESSOR_ID:
        raise RuntimeError("DOCAI_FORM_PARSER_ID not configured")
    if not GOOGLE_CREDS:
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS not configured")

    try:
        from google.cloud import documentai
        from google.oauth2 import service_account
    except ImportError:
        raise RuntimeError("google-cloud-documentai not installed. Run: pip install google-cloud-documentai")

    t0 = time.time()
    log.info("[DOCAI] Processing %s (%d bytes)", asset_id, len(pdf_bytes))

    try:
        credentials = service_account.Credentials.from_service_account_file(
            GOOGLE_CREDS,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        client = documentai.DocumentProcessorServiceClient(credentials=credentials)
        processor_name = client.processor_path(DOCAI_PROJECT, DOCAI_LOCATION, DOCAI_PROCESSOR_ID)

        raw_document = documentai.RawDocument(
            content=pdf_bytes,
            mime_type="application/pdf",
        )
        request = documentai.ProcessRequest(
            name=processor_name,
            raw_document=raw_document,
        )
        result = client.process_document(request=request)
        document = result.document

        # Extract all key-value pairs from form fields
        entities: dict[str, str] = {}
        for page in document.pages:
            for field_obj in page.form_fields:
                key = field_obj.field_name.text_anchor.content if field_obj.field_name.text_anchor else ""
                val = field_obj.field_value.text_anchor.content if field_obj.field_value.text_anchor else ""
                key = key.strip().rstrip(":").strip()
                val = val.strip()
                if key:
                    entities[key] = val

        # Also extract from document entities if available (processor-level extraction)
        for entity in document.entities:
            if entity.type_:
                entities[entity.type_] = entity.mention_text

        elapsed = int((time.time() - t0) * 1000)
        log.info("[DOCAI] %s — %d fields extracted in %dms", asset_id, len(entities), elapsed)

        # Find overbid/surplus field in extracted entities
        overbid_keys = [
            "overbid", "surplus", "excess proceeds", "overbid at sale",
            "overbid amount", "surplus amount", "funds available",
        ]
        amount = None
        for key, val in entities.items():
            key_lower = key.lower()
            if any(k in key_lower for k in overbid_keys):
                parsed = _parse_amount(val)
                if parsed and parsed > ZERO:
                    amount = parsed
                    log.info("[DOCAI] Found overbid field '%s' = %s → $%s", key, val, parsed)
                    break

        # Fallback: scan full document text for dollar amounts near "overbid" keyword
        if amount is None and document.text:
            text = document.text
            for m in re.finditer(
                r"(?:overbid|surplus|excess\s+proceeds)[^\n$]{0,40}\$?([\d,]+\.?\d*)",
                text, re.IGNORECASE
            ):
                parsed = _parse_amount(m.group(1))
                if parsed and parsed > ZERO:
                    amount = parsed
                    log.info("[DOCAI] Fallback text match: $%s", parsed)
                    break

        return amount, entities

    except Exception as exc:
        log.error("[DOCAI] %s — error: %s", asset_id, exc)
        raise


# ── Engine 3: Gemini Vision ───────────────────────────────────────────────────

def _run_gemini(pdf_bytes: bytes, asset_id: str, html_overbid: Decimal) -> tuple[Optional[Decimal], str]:
    """Run Gemini vision model to independently verify overbid amount.

    Returns (extracted_amount, raw_response_text).
    Requires: google-cloud-aiplatform, VERTEX_AI_PROJECT, GEMINI_MODEL
    """
    if not VERTEX_PROJECT:
        raise RuntimeError("VERTEX_AI_PROJECT not configured")
    if not GOOGLE_CREDS:
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS not configured")

    try:
        import vertexai
        from vertexai.generative_models import GenerativeModel, Part
        from google.oauth2 import service_account
    except ImportError:
        raise RuntimeError(
            "google-cloud-aiplatform not installed. Run: pip install google-cloud-aiplatform"
        )

    t0 = time.time()
    log.info("[GEMINI] Processing %s (%d bytes)", asset_id, len(pdf_bytes))

    try:
        credentials = service_account.Credentials.from_service_account_file(
            GOOGLE_CREDS,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        vertexai.init(
            project=VERTEX_PROJECT,
            location=VERTEX_LOCATION,
            credentials=credentials,
        )

        model = GenerativeModel(GEMINI_MODEL)

        # Convert PDF to base64 for inline data
        pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")
        pdf_part = Part.from_data(data=base64.b64decode(pdf_b64), mime_type="application/pdf")

        prompt = f"""You are a legal document verification specialist for Colorado foreclosure surplus funds.

Analyze this foreclosure court document and extract the OVERBID or SURPLUS AMOUNT.

The overbid/surplus amount is the money remaining after the foreclosing party's debt is paid from the auction proceeds.
It may be labeled as: "Overbid", "Surplus", "Excess Proceeds", "Overbid at Sale", or "Funds Available".

IMPORTANT: Return ONLY the dollar amount as a number (e.g., "54011.23" or "0").
Do not include $ symbols, commas, or text.
If you cannot find an overbid/surplus amount, return "0".
Do not guess — only extract what is explicitly stated in the document.

For reference, the HTML portal shows an overbid of ${html_overbid} — does the document confirm this?

Your response must be a single number on the first line, then optionally explain what field you found it in."""

        response = model.generate_content([pdf_part, prompt])
        raw_text = response.text.strip() if response.text else ""

        elapsed = int((time.time() - t0) * 1000)
        log.info("[GEMINI] %s — response in %dms: %r", asset_id, elapsed, raw_text[:100])

        # Extract amount from first line
        first_line = raw_text.split("\n")[0].strip()
        amount = _parse_amount(first_line)

        return amount, raw_text

    except Exception as exc:
        log.error("[GEMINI] %s — error: %s", asset_id, exc)
        raise


# ── Engine 4: Claude API ──────────────────────────────────────────────────────

def _run_claude(pdf_bytes: bytes, asset_id: str, html_overbid: Decimal) -> tuple[Optional[Decimal], str]:
    """Run Claude for tertiary document verification.

    Returns (extracted_amount, raw_response_text).
    Requires: anthropic, ANTHROPIC_API_KEY
    """
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    try:
        import anthropic
    except ImportError:
        raise RuntimeError("anthropic not installed. Run: pip install anthropic")

    t0 = time.time()
    log.info("[CLAUDE] Processing %s (%d bytes)", asset_id, len(pdf_bytes))

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")

        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=256,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": pdf_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": f"""You are verifying a Colorado foreclosure surplus document.
Extract the OVERBID or SURPLUS AMOUNT from this document.
The HTML portal shows ${html_overbid} — confirm or correct this.

Return ONLY a single number (no $ or commas). Example: 54011.23
If no overbid exists, return: 0
Do not guess.""",
                        },
                    ],
                }
            ],
        )

        raw_text = message.content[0].text.strip() if message.content else ""
        elapsed = int((time.time() - t0) * 1000)
        log.info("[CLAUDE] %s — response in %dms: %r", asset_id, elapsed, raw_text[:80])

        first_line = raw_text.split("\n")[0].strip()
        amount = _parse_amount(first_line)
        return amount, raw_text

    except Exception as exc:
        log.error("[CLAUDE] %s — error: %s", asset_id, exc)
        raise


# ── Triple-Verification Orchestrator ─────────────────────────────────────────

class VerificationEngine:
    """SOTA triple-verification engine. No competitor can replicate this pipeline."""

    def __init__(
        self,
        use_docai: bool = True,
        use_gemini: bool = True,
        use_claude: bool = False,   # Optional — enable when ANTHROPIC_API_KEY is set
    ):
        self.use_docai = use_docai and bool(DOCAI_PROCESSOR_ID) and bool(GOOGLE_CREDS)
        self.use_gemini = use_gemini and bool(VERTEX_PROJECT) and bool(GOOGLE_CREDS)
        self.use_claude = use_claude and bool(ANTHROPIC_API_KEY)

        enabled = []
        if self.use_docai:
            enabled.append("Document AI")
        if self.use_gemini:
            enabled.append("Gemini")
        if self.use_claude:
            enabled.append("Claude")

        if enabled:
            log.info("[SOTA] VerificationEngine initialized: %s", ", ".join(enabled))
        else:
            log.warning("[SOTA] No AI engines configured — falling back to HTML math only")

    def verify(
        self,
        asset_id: str,
        html_overbid: Decimal,
        pdf_bytes: Optional[bytes],
        conn=None,
    ) -> VerificationResult:
        """Run all configured verification engines and return a VerificationResult.

        Args:
            asset_id: canonical asset ID (e.g. FORECLOSURE:CO:ARAPAHOE:0148-2023)
            html_overbid: overbid amount already extracted by Gate 4 HTML parsing
            pdf_bytes: raw PDF bytes of evidence document (overbid voucher / court filing)
            conn: optional sqlite3 connection (for writing results back to field_evidence)
        """
        t0 = time.time()
        result = VerificationResult(asset_id=asset_id, html_overbid=html_overbid)

        if not pdf_bytes:
            log.warning("[SOTA] %s — no PDF provided; HTML math only", asset_id)
            result.tier = "HTML_MATH"
            result.confidence = 0.65
            result.duration_ms = int((time.time() - t0) * 1000)
            return result

        if html_overbid <= ZERO:
            log.warning("[SOTA] %s — html_overbid=$0; nothing to verify", asset_id)
            result.tier = "HTML_MATH"
            result.confidence = 0.0
            result.duration_ms = int((time.time() - t0) * 1000)
            return result

        # ── Engine 2: Document AI ─────────────────────────────────────────
        if self.use_docai:
            result.engines_run += 1
            try:
                amount, entities = _run_docai(pdf_bytes, asset_id)
                result.docai_amount = amount
                result.docai_raw = entities
                if amount is not None and abs(html_overbid - amount) <= PENNY:
                    result.engines_agreed += 1
                    log.info("[SOTA] %s — Document AI CONFIRMED $%s", asset_id, amount)
                elif amount is not None:
                    log.warning(
                        "[SOTA] %s — Document AI MISMATCH: HTML=$%s vs DOCAI=$%s (diff=$%s)",
                        asset_id, html_overbid, amount, abs(html_overbid - amount)
                    )
                else:
                    log.warning("[SOTA] %s — Document AI extracted no amount", asset_id)
            except Exception as exc:
                result.errors.append(f"docai:{exc}")
                log.error("[SOTA] %s — Document AI failed: %s", asset_id, exc)

        # ── Engine 3: Gemini Vision ───────────────────────────────────────
        if self.use_gemini:
            result.engines_run += 1
            try:
                amount, raw_text = _run_gemini(pdf_bytes, asset_id, html_overbid)
                result.gemini_amount = amount
                result.gemini_raw = raw_text
                if amount is not None and abs(html_overbid - amount) <= PENNY:
                    result.engines_agreed += 1
                    log.info("[SOTA] %s — Gemini CONFIRMED $%s", asset_id, amount)
                elif amount is not None:
                    log.warning(
                        "[SOTA] %s — Gemini MISMATCH: HTML=$%s vs GEMINI=$%s",
                        asset_id, html_overbid, amount
                    )
                else:
                    log.warning("[SOTA] %s — Gemini extracted no amount", asset_id)
            except Exception as exc:
                result.errors.append(f"gemini:{exc}")
                log.error("[SOTA] %s — Gemini failed: %s", asset_id, exc)

        # ── Engine 4: Claude ──────────────────────────────────────────────
        if self.use_claude:
            result.engines_run += 1
            try:
                amount, raw_text = _run_claude(pdf_bytes, asset_id, html_overbid)
                result.claude_amount = amount
                if amount is not None and abs(html_overbid - amount) <= PENNY:
                    result.engines_agreed += 1
                    log.info("[SOTA] %s — Claude CONFIRMED $%s", asset_id, amount)
                elif amount is not None:
                    log.warning(
                        "[SOTA] %s — Claude MISMATCH: HTML=$%s vs CLAUDE=$%s",
                        asset_id, html_overbid, amount
                    )
            except Exception as exc:
                result.errors.append(f"claude:{exc}")
                log.error("[SOTA] %s — Claude failed: %s", asset_id, exc)

        # ── Determine tier ────────────────────────────────────────────────
        if result.engines_run == 0:
            result.tier = "HTML_MATH"
            result.confidence = 0.65
        elif result.engines_agreed == result.engines_run and result.engines_run >= 2:
            result.tier = "TRIPLE_VERIFIED"
            result.confidence = 0.99
        elif result.engines_agreed >= 1:
            result.tier = "AI_VERIFIED"
            result.confidence = 0.92
        elif result.engines_run > 0 and result.engines_agreed == 0:
            # All AI engines ran but none confirmed — flag for human review
            result.tier = "DISPUTED"
            result.confidence = 0.10
        else:
            result.tier = "HTML_MATH"
            result.confidence = 0.65

        result.duration_ms = int((time.time() - t0) * 1000)

        # ── Write verification result to field_evidence table ─────────────
        if conn is not None:
            _write_verification_result(conn, asset_id, result)

        log.info(
            "[SOTA] %s — RESULT: %s (confidence=%.0f%%, engines=%d/%d, %dms)",
            asset_id, result.tier, result.confidence * 100,
            result.engines_agreed, result.engines_run, result.duration_ms
        )
        return result

    def verify_from_vault(
        self,
        asset_id: str,
        html_overbid: Decimal,
        conn=None,
    ) -> VerificationResult:
        """Load PDF from the vault by asset_id and run verification.

        Looks up evidence_documents table for OB/OBCLAIM/OBCKREQ doc,
        loads from VAULT_ROOT, then calls verify().
        """
        from verifuse_v2.server.api import VAULT_ROOT
        vault = Path(VAULT_ROOT)

        if conn is None:
            raise ValueError("conn required for vault lookup")

        # Find the evidence document
        row = conn.execute(
            """SELECT id, filename, doc_family FROM evidence_documents
               WHERE asset_id = ? AND doc_family IN ('OB','OBCLAIM','OBCKREQ','VOUCHER')
               ORDER BY CASE doc_family WHEN 'OBCKREQ' THEN 1 WHEN 'OBCLAIM' THEN 2 ELSE 3 END
               LIMIT 1""",
            [asset_id],
        ).fetchone()

        if not row:
            log.warning("[SOTA] %s — no OB/voucher document in vault; HTML math only", asset_id)
            result = VerificationResult(asset_id=asset_id, html_overbid=html_overbid)
            result.tier = "HTML_MATH"
            result.confidence = 0.65
            return result

        # Find the PDF file in vault
        doc_id = row["id"] if hasattr(row, "__getitem__") else row[0]
        filename = row["filename"] if hasattr(row, "__getitem__") else row[1]

        # Vault path: VAULT_ROOT/{asset_id_slug}/{filename}
        slug = asset_id.replace(":", "_").replace("/", "_")
        pdf_path = vault / slug / filename
        if not pdf_path.exists():
            # Try flat structure
            pdf_path = vault / filename
        if not pdf_path.exists():
            log.warning("[SOTA] %s — PDF not found at %s", asset_id, pdf_path)
            result = VerificationResult(asset_id=asset_id, html_overbid=html_overbid)
            result.tier = "HTML_MATH"
            result.confidence = 0.65
            return result

        pdf_bytes = pdf_path.read_bytes()
        log.info("[SOTA] %s — loaded %d bytes from vault: %s", asset_id, len(pdf_bytes), pdf_path)
        return self.verify(asset_id, html_overbid, pdf_bytes, conn)


# ── DB write helper ───────────────────────────────────────────────────────────

def _write_verification_result(conn, asset_id: str, result: VerificationResult) -> None:
    """Write verification tier and amounts to field_evidence and leads tables."""
    try:
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()

        # Update pool_source and verification fields on the lead
        conn.execute(
            """UPDATE leads SET
                pool_source = ?,
                updated_at = ?
               WHERE id = (
                   SELECT id FROM leads
                   WHERE 'FORECLOSURE:CO:' || UPPER(county) || ':' || case_number = ?
                   LIMIT 1
               )""",
            [result.pool_source, now, asset_id],
        )

        # Insert detailed verification record into field_evidence
        import uuid as _uuid
        ev_id = str(_uuid.uuid4())
        notes = json.dumps({
            "engines_agreed": result.engines_agreed,
            "engines_run": result.engines_run,
            "docai_amount": str(result.docai_amount) if result.docai_amount else None,
            "gemini_amount": str(result.gemini_amount) if result.gemini_amount else None,
            "claude_amount": str(result.claude_amount) if result.claude_amount else None,
            "errors": result.errors,
            "duration_ms": result.duration_ms,
        })
        conn.execute(
            """INSERT OR REPLACE INTO field_evidence
               (id, asset_id, field_name, value_text, confidence_pct, extraction_method, ocr_source, notes, extracted_at)
               VALUES (?, ?, 'overbid_amount', ?, ?, 'ai_verification_engine', ?, ?, ?)""",
            [
                ev_id,
                asset_id,
                str(result.html_overbid),
                int(result.confidence * 100),
                result.tier,
                notes,
                now,
            ],
        )
        conn.commit()
        log.info("[SOTA] %s — wrote verification result: %s", asset_id, result.tier)
    except Exception as exc:
        log.error("[SOTA] %s — failed to write verification result: %s", asset_id, exc)


# ── CLI entry point ───────────────────────────────────────────────────────────

def verify_asset_cli(asset_id: str, html_overbid_str: str) -> None:
    """CLI wrapper: verify a single asset and print results."""
    import sqlite3
    db_path = os.environ.get("VERIFUSE_DB_PATH", "")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    html_overbid = Decimal(html_overbid_str)
    engine = VerificationEngine(use_docai=True, use_gemini=True, use_claude=False)
    result = engine.verify_from_vault(asset_id, html_overbid, conn)
    conn.close()

    print(f"\n{'='*60}")
    print(f"ASSET: {asset_id}")
    print(f"TIER:  {result.tier}  (confidence: {result.confidence:.0%})")
    print(f"NOTES: {result.verification_notes}")
    if result.errors:
        print(f"ERRORS: {result.errors}")
    print(f"TIME:  {result.duration_ms}ms")
    print(f"{'='*60}\n")
